import sqlite3
import pytest
from normalize import db, pg_compat


@pytest.fixture
def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    db.ensure_chain(conn, "testchain", "Test Chain")
    return conn


def test_upsert_offers_and_products_batch(memory_db):
    run_id = db.start_run(memory_db, "testchain", "test", "2025-01-01", "2025-01-07")
    offers = [
        {
            "product_raw": "Leche 1 gal",
            "product_norm": "leche galon",
            "brand": "Tres Monjitas",
            "size_text": "1 galon",
            "price_sale": 4.99,
            "category": "Lacteos",
        },
        {
            "product_raw": "Leche 1/2 gal",
            "product_norm": "leche medio galon",
            "brand": "Tres Monjitas",
            "size_text": "1/2 galon",
            "price_sale": 2.99,
            "category": "Lacteos",
        },
        {
            "product_raw": "Arroz 3 lb",
            "product_norm": "arroz 3lb",
            "brand": "Sello Rojo",
            "size_text": "3 lb",
            "price_sale": 1.99,
            "category": "Granos",
        },
    ]

    count = db.upsert_offers(memory_db, run_id, "testchain", offers, "2025-01-01", "2025-01-07")
    assert count == 3

    # Verify offers stored
    res_offers = memory_db.execute("SELECT COUNT(*) c FROM offers").fetchone()["c"]
    assert res_offers == 3

    # Verify products dimension table populated
    res_prods = memory_db.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
    assert res_prods == 3


def test_dedup_offers_batch(memory_db):
    run_id = db.start_run(memory_db, "testchain", "test", "2025-01-01", "2025-01-07")
    offers = [
        {
            "product_raw": "Arroz 3 lb",
            "product_norm": "arroz 3lb",
            "brand": "Sello Rojo",
            "size_text": "3 lb",
            "price_sale": 1.99,
            "category": "Granos",
        },
        {
            "product_raw": "Arroz 3 lb Duplicate",
            "product_norm": "arroz 3lb",
            "brand": None,  # less rich
            "size_text": "3 lb (Pack)",
            "price_sale": 1.99,
            "category": "Granos",
        },
    ]

    db.upsert_offers(memory_db, run_id, "testchain", offers, "2025-01-01", "2025-01-07")
    initial_count = memory_db.execute("SELECT COUNT(*) c FROM offers").fetchone()["c"]
    assert initial_count == 2

    removed = db.dedup_offers(memory_db, "testchain", "2025-01-01")
    assert removed == 1

    final_count = memory_db.execute("SELECT COUNT(*) c FROM offers").fetchone()["c"]
    assert final_count == 1
