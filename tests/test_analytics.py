"""Test market analytics, basket projections and category comparison endpoints."""
import sqlite3
from fastapi.testclient import TestClient
from api.main import app
from normalize import db

client = TestClient(app)


def test_analytics_overview_endpoint(monkeypatch, tmp_path):
    db_path = tmp_path / "test_shopper.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO scrape_runs(chain_slug, status, offers_found, valid_from, valid_to) "
        "VALUES ('pueblo', 'ok', 2, date('now', '-1 day'), date('now', '+5 days'))"
    )
    run_id = cur.lastrowid
    cur.execute(
        "INSERT INTO offers(run_id, chain_slug, product_raw, product_norm, price_sale, price_regular, unit_price, category, valid_from, valid_to) "
        "VALUES (?, 'pueblo', 'Leche 128oz', 'leche', 3.99, 4.99, 0.03, 'Lácteos', date('now', '-1 day'), date('now', '+5 days'))",
        (run_id,)
    )
    conn.commit()

    conn.close()
    monkeypatch.setattr("api.main._conn", lambda: db.connect(str(db_path)))

    r = client.get("/api/analytics/overview")
    assert r.status_code == 200
    data = r.json()
    assert "summary" in data
    assert "per_chain" in data
    assert "categories" in data
    assert "top_dispersion" in data


def test_analytics_category_comparison_endpoint(monkeypatch, tmp_path):
    db_path = tmp_path / "test_shopper.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO scrape_runs(chain_slug, status, offers_found, valid_from, valid_to) "
        "VALUES ('amigo', 'ok', 1, date('now', '-1 day'), date('now', '+5 days'))"
    )
    run_id = cur.lastrowid
    cur.execute(
        "INSERT INTO offers(run_id, chain_slug, product_raw, product_norm, price_sale, category, valid_from, valid_to) "
        "VALUES (?, 'amigo', 'Arroz 3lb', 'arroz', 1.99, 'Granos', date('now', '-1 day'), date('now', '+5 days'))",
        (run_id,)
    )
    conn.commit()

    conn.close()
    monkeypatch.setattr("api.main._conn", lambda: db.connect(str(db_path)))

    r = client.get("/api/analytics/category_comparison")
    assert r.status_code == 200
    data = r.json()
    assert "categories" in data


def test_analytics_basket_projections_endpoint(monkeypatch, tmp_path):
    db_path = tmp_path / "test_shopper.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO scrape_runs(chain_slug, status, offers_found, valid_from, valid_to) "
        "VALUES ('selectos', 'ok', 1, date('now', '-1 day'), date('now', '+5 days'))"
    )
    run_id = cur.lastrowid
    cur.execute(
        "INSERT INTO offers(run_id, chain_slug, product_raw, product_norm, price_sale, valid_from, valid_to) "
        "VALUES (?, 'selectos', 'Café 10oz', 'cafe', 5.99, date('now', '-1 day'), date('now', '+5 days'))",
        (run_id,)
    )
    conn.commit()

    conn.close()
    monkeypatch.setattr("api.main._conn", lambda: db.connect(str(db_path)))

    r = client.get("/api/analytics/basket_projections")
    assert r.status_code == 200
    data = r.json()
    assert "chain_totals" in data
    assert "staples_evaluated" in data
