"""Backfill status should report rows that survive pack-aware deduplication."""
import sqlite3

import backfill
from normalize import db


def test_backfill_count_matches_stored_rows_after_dedup(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    offers = [
        {"product_raw": "Arroz", "product_norm": "arroz", "brand": "Marca X",
         "size_text": size, "price_sale": 2.0, "promo": None}
        for size in ("1 lb", "1 LB")
    ]
    monkeypatch.setattr(backfill.cdn_fetch, "fetch_week", lambda *a: ["fixture.png"])
    monkeypatch.setattr(backfill, "extract_images", lambda *a: offers)

    result = backfill.backfill_chain_week(conn, {}, "econo", "econo", "2026-10-15", 7)

    assert result["status"] == "ok"
    assert conn.execute("SELECT COUNT(*) AS n FROM offers").fetchone()["n"] == 1
    assert conn.execute("SELECT offers_found FROM scrape_runs").fetchone()["offers_found"] == 1
    assert result["offers"] == 1
    conn.close()
