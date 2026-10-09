"""SQLite persistence layer."""
import logging
import sqlite3
from pathlib import Path

from . import units

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

log = logging.getLogger("pr-shopper.db")

SCHEMA = ROOT / "normalize" / "schema.sql"


def connect(db_path: str | Path) -> sqlite3.Connection:
    p = Path(db_path)
    if not p.is_absolute():
        p = ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
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


def upsert_product(conn, product_norm: str, display: str, brand: str | None,
                   category: str | None) -> None:
    """Maintain the products dimension table (one row per normalized product)."""
    if not product_norm:
        return
    conn.execute(
        """INSERT INTO products(product_norm, display_name, brand, category)
           VALUES(?,?,?,?)
           ON CONFLICT(product_norm) DO UPDATE SET
             display_name = COALESCE(products.display_name, excluded.display_name),
             brand        = COALESCE(products.brand, excluded.brand),
             category     = COALESCE(products.category, excluded.category)""",
        (product_norm, display, brand, category))


def dedup_offers(conn, chain_slug: str, valid_from: str) -> int:
    """Collapse exact duplicate offers for a chain+week: same product_norm and
    price_sale scraped from overlapping pages (e.g. Econo home + category
    screenshots). Keeps the row with the most complete size/unit data, deletes
    the rest. Returns number of rows removed."""
    rows = conn.execute(
        """SELECT id, product_norm, price_sale,
                  (CASE WHEN size_canonical IS NOT NULL THEN 1 ELSE 0 END
                   + CASE WHEN unit_price IS NOT NULL THEN 1 ELSE 0 END
                   + CASE WHEN brand IS NOT NULL THEN 1 ELSE 0 END
                   + CASE WHEN promo IS NOT NULL THEN 1 ELSE 0 END) AS richness
           FROM offers WHERE chain_slug=? AND valid_from=?""",
        (chain_slug, valid_from)).fetchall()
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        groups[(r["product_norm"], r["price_sale"])].append((r["id"], r["richness"]))
    to_delete = []
    for ids in groups.values():
        if len(ids) > 1:
            ids.sort(key=lambda x: x[1], reverse=True)  # richest first
            to_delete.extend(i for i, _ in ids[1:])
    for i in to_delete:
        conn.execute("DELETE FROM offers WHERE id=?", (i,))
    conn.commit()
    if to_delete:
        log.info("[%s] dedup removed %d duplicate rows", chain_slug, len(to_delete))
    return len(to_delete)


def upsert_offers(conn, run_id: int, chain_slug: str, offers: list[dict],
                  valid_from=None, valid_to=None) -> int:
    n = 0
    for o in offers:
        try:
            parsed = units.parse_size(o.get("size_text"))
            uprice, pbasis = units.unit_price(o.get("price_sale"), parsed)
            sku = o.get("sku")
            if not sku:
                # generated key: chain + normalized product + canonical size
                sku = f"{chain_slug}:{o.get('product_norm')}|{(parsed or {}).get('canonical') or o.get('size_text') or ''}"
            conn.execute(
                """INSERT INTO offers
                   (run_id, chain_slug, product_raw, product_norm, sku, brand, size_text,
                    price_sale, price_regular, unit_price, unit_basis, promo, category,
                    page, valid_from, valid_to, source_url,
                    size_canonical, base_qty, base_unit, price_basis)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(chain_slug, product_norm, size_text, price_sale, valid_from)
                   DO NOTHING""",
                (run_id, chain_slug, o.get("product_raw"), o.get("product_norm"), sku,
                 o.get("brand"), o.get("size_text"), o.get("price_sale"),
                 o.get("price_regular"), uprice, o.get("unit_basis"),
                 o.get("promo"), o.get("category"), o.get("page"),
                 valid_from, valid_to, o.get("source_url"),
                 parsed and parsed.get("canonical"),
                 parsed and parsed.get("base_qty"),
                 parsed and parsed.get("base_unit"), pbasis))
            upsert_product(conn, o.get("product_norm"), o.get("product_raw"),
                           o.get("brand"), o.get("category"))
            n += 1
        except sqlite3.Error as e:
            log.warning("offer insert failed: %s -> %s", e, o.get("product_raw"))
    conn.commit()
    return n
