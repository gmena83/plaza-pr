"""Persistence layer. SQLite (local default) or Postgres/Supabase (hosted).

Backend is selected per call site:
  db.connect(cfg["db_path"])                    -> SQLite file
  db.connect(os.environ["DATABASE_URL"])        -> Postgres (dsn contains "://")
Set DATABASE_URL in the environment to switch scraper/backfill/API to Postgres;
leave it unset to keep the historical SQLite behaviour.
"""
import logging
import os
import sqlite3
from pathlib import Path

from . import units

ROOT = Path(__file__).resolve().parent.parent

log = logging.getLogger("pr-shopper.db")


class OfferIdentityConflict(RuntimeError):
    """The deployed unique key would discard a distinct observed variant."""


def _row_constraint_error(exc):
    """Only a row constraint is safe to skip; operational errors fail the run."""
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    from psycopg2 import IntegrityError
    return isinstance(exc, IntegrityError)

SCHEMA = ROOT / "normalize" / "schema.sql"
SCHEMA_PG = ROOT / "normalize" / "schema_pg.sql"


def _is_pg(path_or_dsn) -> bool:
    return isinstance(path_or_dsn, str) and "://" in path_or_dsn


def connect(path_or_dsn):
    """SQLite path (str/Path) or Postgres DSN (contains '://')."""
    if _is_pg(path_or_dsn):
        from . import pg_compat
        log.info("connecting to Postgres backend")
        return pg_compat.connect(path_or_dsn)
    p = Path(path_or_dsn)
    if not p.is_absolute():
        p = ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def dsn_from_env(cfg: dict) -> str:
    """DATABASE_URL env wins; else the configured sqlite path."""
    return os.environ.get("DATABASE_URL") or cfg["db_path"]


def init_db(conn) -> None:
    # Pick schema by connection type: CompatConnection wraps psycopg2.
    if hasattr(conn, "_conn"):  # pg compat
        conn.executescript(SCHEMA_PG.read_text())
    else:
        conn.executescript(SCHEMA.read_text())
    conn.commit()


def ensure_chain(conn, slug: str, name: str) -> None:
    conn.execute(
        "INSERT INTO chains(slug,name) VALUES(?,?) "
        "ON CONFLICT(slug) DO UPDATE SET name=excluded.name", (slug, name))


def start_run(conn, chain_slug: str, source: str, valid_from, valid_to) -> int:
    cur = conn.execute(
        "INSERT INTO scrape_runs(chain_slug,source,valid_from,valid_to) VALUES(?,?,?,?)",
        (chain_slug, source, valid_from, valid_to))
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id: int, status: str, offers_found: int, error: str | None = None):
    if status != "ok":
        # The running marker was committed by start_run; never commit partial
        # offers/products from a failed chain (including backfill callers).
        conn.rollback()
        offers_found = 0
    else:
        offers_found = conn.execute(
            "SELECT COUNT(*) AS n FROM offers WHERE run_id=?",
            (run_id,)).fetchone()["n"]
    conn.execute(
        "UPDATE scrape_runs SET finished_at=datetime('now'), status=?, offers_found=?, error=? "
        "WHERE id=?", (status, offers_found, error, run_id))
    conn.commit()


def sweep_stale_runs(conn) -> int:
    """Mark any run left in 'running' (killed process) as 'stale'."""
    cur = conn.execute(
        "UPDATE scrape_runs SET status='stale', finished_at=datetime('now') "
        "WHERE status='running'")
    conn.commit()
    if cur.rowcount:
        log.warning("swept %d stale run(s)", cur.rowcount)
    return cur.rowcount


def upsert_products(conn, products: list[dict]) -> None:
    """Maintain the products dimension table in batch."""
    merged = {}
    for p in products:
        pnorm = p.get("product_norm")
        if not pnorm:
            continue
        display = p.get("display")
        brand = p.get("brand")
        category = p.get("category")
        if pnorm not in merged:
            merged[pnorm] = {"display": display, "brand": brand, "category": category}
        else:
            m = merged[pnorm]
            if not m["display"] and display:
                m["display"] = display
            if not m["brand"] and brand:
                m["brand"] = brand
            if not m["category"] and category:
                m["category"] = category

    if not merged:
        return

    params = [
        (pnorm, data["display"], data["brand"], data["category"])
        for pnorm, data in merged.items()
    ]
    conn.executemany(
        """INSERT INTO products(product_norm, display_name, brand, category)
           VALUES(?,?,?,?)
           ON CONFLICT(product_norm) DO UPDATE SET
             display_name = COALESCE(products.display_name, excluded.display_name),
             brand        = COALESCE(products.brand, excluded.brand),
             category     = COALESCE(products.category, excluded.category)""",
        params)


def upsert_product(conn, product_norm: str, display: str, brand: str | None,
                   category: str | None) -> None:
    """Maintain the products dimension table (one row per normalized product)."""
    upsert_products(conn, [{"product_norm": product_norm, "display": display,
                            "brand": brand, "category": category}])


def dedup_offers(conn, chain_slug: str, valid_from: str, run_id: int | None = None) -> int:
    """Remove identical printed offers within the current run only.
    Never rewrite completed history or erase uncertain variants."""
    if run_id is None:
        # Backfill and older callers pass only chain/week. Refuse an ambiguous
        # scope rather than sweeping rows belonging to another run.
        running = conn.execute(
            """SELECT id FROM scrape_runs WHERE chain_slug=? AND valid_from=?
               AND status='running'""", (chain_slug, valid_from)).fetchall()
        if len(running) != 1:
            raise ValueError("dedup requires exactly one running run or explicit run_id")
        run_id = running[0]["id"]
    rows = conn.execute(
        """SELECT id, product_norm, product_raw, price_sale, size_canonical,
                  size_text, brand, sku, promo, unit_price, price_regular, valid_to,
                  category
           FROM offers WHERE chain_slug=? AND valid_from=? AND run_id=?""",
        (chain_slug, valid_from, run_id)).fetchall()
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        size = r["size_canonical"] or r["size_text"]
        if not r["product_norm"] or not size or r["price_sale"] is None:
            continue
        key = (r["product_norm"], r["product_raw"], r["price_sale"],
               size, r["brand"], r["sku"], r["promo"], r["category"],
               r["price_regular"], r["valid_to"])
        richness = sum(r[field] is not None for field in
                       ("size_canonical", "unit_price", "brand", "promo"))
        groups[key].append((r["id"], richness))
    to_delete = []
    for ids in groups.values():
        if len(ids) > 1:
            ids.sort(key=lambda x: (-x[1], x[0]))
            to_delete.extend(i for i, _ in ids[1:])
    if to_delete:
        conn.executemany("DELETE FROM offers WHERE id=?", [(i,) for i in to_delete])
        log.info("[%s] dedup removed %d duplicate rows", chain_slug, len(to_delete))
    return len(to_delete)


def upsert_offers(conn, run_id: int, chain_slug: str, offers: list[dict],
                  valid_from=None, valid_to=None) -> int:
    offer_params = []
    generated_keys = []
    for o in offers:
        try:
            parsed = units.parse_size(o.get("size_text"))
            uprice, pbasis = units.unit_price(o.get("price_sale"), parsed)
            sku = o.get("sku")
            if not sku:
                # generated key: chain + normalized product + canonical size
                sku = f"{chain_slug}:{o.get('product_norm')}|{(parsed or {}).get('canonical') or o.get('size_text') or ''}"
            generated_keys.append(not o.get("sku"))
            offer_params.append((
                run_id, chain_slug, o.get("product_raw"), o.get("product_norm"), sku,
                o.get("brand"), o.get("size_text"), o.get("price_sale"),
                o.get("price_regular"), uprice, o.get("unit_basis"),
                o.get("promo"), o.get("category"), o.get("page"),
                valid_from, valid_to, o.get("source_url"),
                parsed and parsed.get("canonical"),
                parsed and parsed.get("base_qty"),
                parsed and parsed.get("base_unit"), pbasis
            ))
        except Exception:
            log.exception("offer processing failed before insert")
            raise

    if not offer_params:
        return 0

    insert_sql = """INSERT INTO offers
        (run_id, chain_slug, product_raw, product_norm, sku, brand, size_text,
         price_sale, price_regular, unit_price, unit_basis, promo, category,
         page, valid_from, valid_to, source_url,
         size_canonical, base_qty, base_unit, price_basis)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT DO NOTHING"""
    # Keep the entire ingestion in the caller's transaction. The run's final
    # status and these rows are committed together by finish_run().
    # SQLite RELEASE of an outermost SAVEPOINT implicitly commits. Open an
    # explicit transaction so the caller still owns the final commit/rollback.
    if isinstance(conn, sqlite3.Connection) and not conn.in_transaction:
        conn.execute("BEGIN")
    conn.execute("SAVEPOINT offer_ingest")
    try:
        # Existing imports may have NULL SKU where this writer now generates
        # one. Neither the old nor the draft index can establish that the two
        # keys are distinct; quarantine the replay instead of duplicating it.
        stable_fields = {"chain_slug": 1, "product_raw": 2,
                         "product_norm": 3, "brand": 5, "size_text": 6,
                         "price_sale": 7, "price_regular": 8, "promo": 11,
                         "category": 12, "valid_from": 14, "valid_to": 15}
        for params, generated in zip(offer_params, generated_keys):
            if not generated:
                continue
            predicates = ["sku IS NULL"]
            values = []
            for column, index in stable_fields.items():
                if params[index] is None:
                    predicates.append(f"{column} IS NULL")
                else:
                    predicates.append(f"{column}=?")
                    values.append(params[index])
            if conn.execute("SELECT id FROM offers WHERE " +
                            " AND ".join(predicates) + " LIMIT 1",
                            values).fetchone():
                raise OfferIdentityConflict(
                    "offer identity collision: legacy NULL SKU requires manual reconciliation")
        legacy_unique = True
        if hasattr(conn, "_conn"):
            legacy_unique = bool(conn.execute(
                """SELECT 1 FROM pg_constraint WHERE conrelid='offers'::regclass
                   AND conname='offers_chain_slug_product_norm_size_text_price_sale_valid_f_key'"""
            ).fetchone())
            if not legacy_unique and not conn.execute(
                """SELECT 1 FROM pg_indexes WHERE schemaname=current_schema()
                   AND tablename='offers' AND indexname='offers_identity_v2'"""
            ).fetchone():
                raise RuntimeError("unsupported offers identity schema")
        # The live unique constraint omits these variant-defining fields. Until
        # an audited migration replaces it, refuse a conflicting observation
        # rather than letting ON CONFLICT silently discard it. This check also
        # catches collisions between rows of the same incoming batch.
        def stored_variant(row):
            return (row["product_raw"], row["sku"], row["brand"],
                    row["price_regular"], row["promo"], row["category"],
                    str(row["valid_to"]) if row["valid_to"] is not None else None)

        seen_keys = {}
        if legacy_unique:
            for params in offer_params:
                key = (params[1], params[3], params[6], params[7], params[14])
                if any(value is None for value in key):
                    continue
                variant = (params[2], params[4], params[5], params[8],
                           params[11], params[12], params[15])
                previous = seen_keys.get(key)
                if previous is None:
                    row = conn.execute(
                        """SELECT product_raw, sku, brand, price_regular, promo,
                                  category, valid_to FROM offers WHERE chain_slug=?
                           AND product_norm=? AND size_text=? AND price_sale=?
                           AND valid_from=? LIMIT 1""", key).fetchone()
                    previous = stored_variant(row) if row else variant
                if previous != variant:
                    raise OfferIdentityConflict(
                        "offer identity collision: legacy unique key excludes a distinct variant")
                seen_keys[key] = variant
        previous_id = conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS id FROM offers WHERE run_id=?",
            (run_id,)).fetchone()["id"]
        def insert_one(params):
            conn.execute("SAVEPOINT offer_row")
            try:
                conn.execute(insert_sql, params)
            except Exception:
                conn.execute("ROLLBACK TO SAVEPOINT offer_row")
                # A rejected row invalidates the whole capture, not just this
                # row. The outer savepoint discards any earlier valid rows.
                raise
            finally:
                conn.execute("RELEASE SAVEPOINT offer_row")

        complete = [p for p in offer_params if all(p[i] is not None for i in
                    (3, 6, 7, 14))]
        incomplete = [p for p in offer_params if any(p[i] is None for i in
                      (3, 6, 7, 14))]
        conn.execute("SAVEPOINT offer_batch")
        try:
            if complete:
                conn.executemany(insert_sql, complete)
        except Exception as e:
            if not _row_constraint_error(e):
                raise
            log.warning("batch offer insert failed: %s; retrying individually", e)
            # SQLite may have inserted a prefix; Postgres aborts the entire
            # transaction. In both cases rollback the batch before retrying.
            conn.execute("ROLLBACK TO SAVEPOINT offer_batch")
            for params in complete:
                insert_one(params)
        finally:
            conn.execute("RELEASE SAVEPOINT offer_batch")

        if legacy_unique:
            # A concurrent writer can commit a distinct variant after our
            # precheck and before ON CONFLICT DO NOTHING resolves. Read the
            # winning row *after* the insert; a missing/invisible row is also
            # unsafe (e.g. stricter transaction isolation).
            for key, variant in seen_keys.items():
                row = conn.execute(
                    """SELECT product_raw, sku, brand, price_regular, promo,
                              category, valid_to FROM offers WHERE chain_slug=?
                       AND product_norm=? AND size_text=? AND price_sale=?
                       AND valid_from=? LIMIT 1""", key).fetchone()
                if row is None or stored_variant(row) != variant:
                    raise OfferIdentityConflict(
                        "offer identity collision: concurrent legacy writer retained a distinct variant")

        # SQL UNIQUE treats NULL as distinct. Match stable printed identity,
        # not the page or fetch URL (which can change between captures).
        # This exact check is provisional until a database uniqueness migration.
        identity = {"chain_slug": 1, "product_raw": 2, "product_norm": 3,
                    "sku": 4, "brand": 5, "size_text": 6, "price_sale": 7,
                    "price_regular": 8, "promo": 11, "category": 12,
                    "valid_from": 14, "valid_to": 15}
        for params in incomplete:
            predicates = []
            values = []
            for column, index in identity.items():
                if params[index] is None:
                    predicates.append(f"{column} IS NULL")
                else:
                    predicates.append(f"{column}=?")
                    values.append(params[index])
            if conn.execute("SELECT id FROM offers WHERE " +
                            " AND ".join(predicates) + " LIMIT 1",
                            values).fetchone() is None:
                insert_one(params)

        inserted = conn.execute(
            """SELECT product_norm, product_raw, brand, category
               FROM offers WHERE run_id=? AND id>? ORDER BY id""",
            (run_id, previous_id)).fetchall()
        upsert_products(conn, [{"product_norm": r["product_norm"],
                                "display": r["product_raw"], "brand": r["brand"],
                                "category": r["category"]} for r in inserted])
        conn.execute("RELEASE SAVEPOINT offer_ingest")
        return len(inserted)
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT offer_ingest")
        conn.execute("RELEASE SAVEPOINT offer_ingest")
        raise
