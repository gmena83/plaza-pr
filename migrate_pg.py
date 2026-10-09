"""Migrate the local SQLite shopper.db to Postgres (Supabase).

Usage:
  DATABASE_URL="postgresql://..." .venv/bin/python migrate_pg.py

- Creates the schema (normalize/schema_pg.sql), chains, runs, offers, products.
- Idempotent: skips run ids / offer rows already present (ON CONFLICT DO NOTHING).
- Safe to re-run; row counts are printed at the end for verification.
"""
import os
import sqlite3
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parent
SQLITE_DB = ROOT / "db" / "shopper.db"
SCHEMA_PG = (ROOT / "normalize" / "schema_pg.sql").read_text()

BATCH = 500

OFFER_COLS = ["run_id", "chain_slug", "product_raw", "product_norm", "sku",
              "brand", "size_text", "price_sale", "price_regular", "unit_price",
              "unit_basis", "promo", "size_canonical", "base_qty", "base_unit",
              "price_basis", "category", "page", "valid_from", "valid_to",
              "source_url", "scraped_at"]

RUN_COLS = ["id", "chain_slug", "started_at", "finished_at", "status",
            "offers_found", "source", "valid_from", "valid_to", "error"]


def main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL is not set")

    src = sqlite3.connect(str(SQLITE_DB))
    src.row_factory = sqlite3.Row
    dst = psycopg2.connect(dsn)
    dst.autocommit = False

    with dst.cursor() as cur:
        cur.execute(SCHEMA_PG)
    dst.commit()
    print("schema ok")

    # 1. chains
    chains = src.execute("SELECT slug, name FROM chains").fetchall()
    with dst.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO chains(slug, name) VALUES %s "
            "ON CONFLICT (slug) DO UPDATE SET name=excluded.name",
            [(c["slug"], c["name"]) for c in chains])
    dst.commit()
    print(f"chains: {len(chains)}")

    # 2. scrape_runs (keep ids so offers.run_id lines up)
    runs = src.execute(f"SELECT {','.join(RUN_COLS)} FROM scrape_runs").fetchall()
    with dst.cursor() as cur:
        for i in range(0, len(runs), BATCH):
            psycopg2.extras.execute_values(
                cur,
                f"INSERT INTO scrape_runs({','.join(RUN_COLS)}) VALUES %s "
                "ON CONFLICT (id) DO NOTHING",
                [tuple(r[c] for c in RUN_COLS) for r in runs[i:i+BATCH]])
    dst.commit()
    # reset identity sequence past the max migrated id
    with dst.cursor() as cur:
        cur.execute("SELECT setval(pg_get_serial_sequence('scrape_runs','id'), "
                    "COALESCE((SELECT MAX(id) FROM scrape_runs), 1))")
    dst.commit()
    print(f"scrape_runs: {len(runs)}")

    # 3. offers
    n_offers = src.execute("SELECT COUNT(*) c FROM offers").fetchone()["c"]
    done = 0
    with dst.cursor() as cur:
        for i in range(0, n_offers, BATCH):
            rows = src.execute(
                f"SELECT {','.join(OFFER_COLS)} FROM offers "
                f"ORDER BY id LIMIT {BATCH} OFFSET {i}").fetchall()
            psycopg2.extras.execute_values(
                cur,
                f"INSERT INTO offers({','.join(OFFER_COLS)}) VALUES %s "
                "ON CONFLICT (chain_slug, product_norm, size_text, price_sale, valid_from) "
                "DO NOTHING",
                [tuple(r[c] for c in OFFER_COLS) for r in rows])
            done += len(rows)
            if done % (BATCH * 4) == 0:
                print(f"  offers {done}/{n_offers}")
    dst.commit()
    print(f"offers: {done}")

    # 4. products
    prods = src.execute(
        "SELECT product_norm, display_name, brand, category, first_seen "
        "FROM products").fetchall()
    with dst.cursor() as cur:
        for i in range(0, len(prods), BATCH):
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO products(product_norm, display_name, brand, category, first_seen) "
                "VALUES %s ON CONFLICT (product_norm) DO NOTHING",
                [(p["product_norm"], p["display_name"], p["brand"],
                  p["category"], p["first_seen"]) for p in prods[i:i+BATCH]])
    dst.commit()
    print(f"products: {len(prods)}")

    # verify
    with dst.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for t in ("chains", "scrape_runs", "offers", "products"):
            cur.execute(f"SELECT COUNT(*) c FROM {t}")
            print(f"pg.{t}: {cur.fetchone()['c']}")

    dst.close()
    src.close()


if __name__ == "__main__":
    main()
