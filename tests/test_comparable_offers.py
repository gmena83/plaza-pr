"""Conservative current-special comparison, exercised through the public API."""
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
import os
import sqlite3
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from api.main import app
from normalize import db


@pytest.fixture
def offers_db(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    monkeypatch.setattr("api.main._analytics_conn", lambda: nullcontext(conn))
    today = datetime.now(ZoneInfo("America/Puerto_Rico")).date()

    def add(chain, name="arroz", brand="Sello", size="3lb", basis="$/lb",
            price=2.0, start=None, end=None, url=None):
        start = today if start is None else start
        end = today if end is None else end
        run = conn.execute("INSERT INTO scrape_runs(chain_slug) VALUES (?)", (chain,)).lastrowid
        conn.execute(
            "INSERT INTO offers (run_id,chain_slug,product_raw,product_norm,brand,size_canonical,"
            "price_basis,price_sale,valid_from,valid_to,source_url) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (run, chain, name or "raw", name, brand, size, basis, price, str(start), str(end), url),
        )
        conn.commit()

    yield today, add, conn
    conn.close()


def test_comparable_offers_only_exact_cohort_and_current_valid_prices(offers_db):
    today, add, _ = offers_db
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    add("a", brand=" SELLO ", price=2.5, start=yesterday, url="https://a.test/1")
    add("b", brand="sello", price=2.0, end=tomorrow, url="https://b.test/1")
    add("a", size="5lb", price=1.0)  # no unequal pack comparison
    add("b", price=None)  # no null-priced match
    response = TestClient(app).get("/api/analytics/comparable_offers")
    assert response.status_code == 200
    assert response.json() == {
        "as_of": str(today), "scope": "advertised_specials_only",
        "active_offers": 3, "active_chains": 2, "matched_cohorts": 1,
        "rows": [{
            "product_norm": "arroz", "brand": "sello", "size_canonical": "3lb",
            "price_basis": "$/lb", "chains": [
                {"chain_slug": "a", "price_sale": 2.5, "valid_from": str(yesterday),
                 "valid_to": str(today), "source_url": "https://a.test/1", "promo": None},
                {"chain_slug": "b", "price_sale": 2.0, "valid_from": str(today),
                 "valid_to": str(tomorrow), "source_url": "https://b.test/1", "promo": None},
            ],
        }],
    }


def test_multibuy_per_item_prices_never_rank_against_single_item_offers(offers_db):
    today, add, conn = offers_db
    add("a", price=3.0)
    add("b", price=2.0)
    add("c", price=4.0)
    conn.execute("UPDATE offers SET promo=' 2 / $4.00' WHERE chain_slug='b'")
    conn.execute("UPDATE offers SET promo='raincheck' WHERE chain_slug='c'")
    conn.commit()
    data = TestClient(app).get("/api/analytics/comparable_offers").json()
    assert data["active_offers"] == 3
    assert data["matched_cohorts"] == 1
    assert data["rows"][0]["chains"] == [
        {"chain_slug": "a", "price_sale": 3, "valid_from": str(today),
         "valid_to": str(today), "source_url": None, "promo": None},
        {"chain_slug": "c", "price_sale": 4, "valid_from": str(today),
         "valid_to": str(today), "source_url": None, "promo": "raincheck"},
    ]


def test_multibuy_only_cohort_is_not_comparable(offers_db):
    _, add, conn = offers_db
    add("a")
    add("b")
    conn.execute("UPDATE offers SET promo='5/$5.00' WHERE chain_slug='b'")
    conn.commit()
    data = TestClient(app).get("/api/analytics/comparable_offers").json()
    assert data["active_offers"] == 2
    assert data["matched_cohorts"] == 0
    assert data["rows"] == []


@pytest.mark.parametrize("promo", ["2x1", "2 x 1", "2 por 1"])
def test_two_for_one_promotions_cannot_rank_as_single_item_price(offers_db, promo):
    _, add, conn = offers_db
    add("a", price=3)
    add("b", price=2)
    add("c", price=4)
    conn.execute("UPDATE offers SET promo=? WHERE chain_slug='b'", (promo,))
    conn.commit()
    data = TestClient(app).get("/api/analytics/comparable_offers").json()
    assert data["active_offers"] == 3
    assert data["matched_cohorts"] == 1
    assert [(o["chain_slug"], o["price_sale"]) for o in data["rows"][0]["chains"]] == [
        ("a", 3), ("c", 4)]


@pytest.mark.parametrize("promo", [
    "Oferta 2/$4", "Oferta: 2 / $4.00", "2x$3", "Oferta 2 x $3",
])
def test_promotional_wording_and_x_dollar_multibuys_do_not_rank_as_single_items(offers_db, promo):
    _, add, conn = offers_db
    add("a", price=3)
    add("b", price=2)
    add("c", price=4)
    conn.execute("UPDATE offers SET promo=? WHERE chain_slug='b'", (promo,))
    conn.commit()

    response = TestClient(app).get("/api/analytics/comparable_offers")
    assert response.status_code == 200
    data = response.json()
    assert data["active_offers"] == 3  # counted, but not comparable
    assert data["matched_cohorts"] == 1
    assert [(o["chain_slug"], o["price_sale"]) for o in data["rows"][0]["chains"]] == [
        ("a", 3), ("c", 4)]


def test_current_specials_use_pr_calendar_day_even_when_db_is_already_on_next_utc_day(
        offers_db, monkeypatch):
    _, add, conn = offers_db
    pr_day = date(2021, 1, 1)
    utc_day = pr_day + timedelta(days=1)
    add("a", start=pr_day, end=pr_day)
    add("b", start=pr_day, end=pr_day)
    add("c", start=utc_day, end=utc_day)
    add("d", start=pr_day - timedelta(days=1), end=pr_day - timedelta(days=1))

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz == ZoneInfo("America/Puerto_Rico")
            return datetime(2021, 1, 2, 0, 30, tzinfo=timezone.utc).astimezone(tz)

    class UtcDbConnection:
        db_calendar_reads = 0

        def execute(self, sql, params=()):
            if "date('now')" in sql:
                self.db_calendar_reads += 1

                class Cursor:
                    def fetchone(self):
                        return {"as_of": str(utc_day)}

                return Cursor()
            return conn.execute(sql, params)

    utc_db = UtcDbConnection()
    monkeypatch.setattr("api.main._analytics_conn", lambda: nullcontext(utc_db))
    monkeypatch.setattr("api.main.datetime", FrozenDateTime, raising=False)

    response = TestClient(app).get("/api/analytics/comparable_offers")
    assert response.status_code == 200
    data = response.json()
    assert data["as_of"] == str(pr_day)
    assert data["active_offers"] == 2
    assert data["active_chains"] == 2
    assert data["matched_cohorts"] == 1
    assert [o["chain_slug"] for o in data["rows"][0]["chains"]] == ["a", "b"]
    assert utc_db.db_calendar_reads == 0


def test_selects_cheapest_current_offer_per_chain_with_deterministic_ties(offers_db):
    today, add, _ = offers_db
    add("z", price=5, url="https://z.test/expensive")
    add("z", price=2, url="https://z.test/b")
    add("z", price=2, url="https://z.test/a")
    add("a", price=3, url="https://a.test/")
    response = TestClient(app).get("/api/analytics/comparable_offers")
    assert response.status_code == 200
    assert response.json()["matched_cohorts"] == 1
    assert response.json()["active_offers"] == 4
    assert response.json()["rows"][0]["chains"] == [
        {"chain_slug": "a", "price_sale": 3, "valid_from": str(today),
         "valid_to": str(today), "source_url": "https://a.test/", "promo": None},
        {"chain_slug": "z", "price_sale": 2, "valid_from": str(today),
         "valid_to": str(today), "source_url": "https://z.test/a", "promo": None},
    ]


def test_missing_identity_bad_price_or_expired_offer_never_creates_a_match(offers_db):
    today, add, _ = offers_db
    add("a")
    add("a", price=3.0)  # same chain cannot self-match
    add("b", brand="Other")
    add("b", size="5lb")
    add("b", basis="$/un")
    add("b", name="arroz integral")
    for fields in ({"name": None}, {"brand": None}, {"brand": "   "},
                   {"size": None}, {"basis": ""}):
        add("b", **fields)
    for price in (None, 0, -2, float("inf")):
        add("b", price=price)
    add("b", end=today - timedelta(days=1))
    add("b", start=today + timedelta(days=1))
    data = TestClient(app).get("/api/analytics/comparable_offers").json()
    assert data["active_offers"] == 11
    assert data["active_chains"] == 2
    assert data["matched_cohorts"] == 0
    assert data["rows"] == []
    assert not any("proj" in str(key) or "total" in str(key) for key in data)


def test_malformed_printed_validity_does_not_count_as_current(offers_db):
    today, add, _ = offers_db
    add("a")
    add("b", start=f"{today - timedelta(days=1)}oops",
        end=f"{today + timedelta(days=1)}oops")
    data = TestClient(app).get("/api/analytics/comparable_offers").json()
    assert data["active_offers"] == 1
    assert data["active_chains"] == 1
    assert data["matched_cohorts"] == 0
    assert data["rows"] == []


def test_sample_is_stable_bounded_and_reports_total_matched_cohorts(offers_db):
    _, add, _ = offers_db
    for index in range(105):
        for chain in ("b", "a"):
            add(chain, name=f"item-{index:03d}")
    data = TestClient(app).get("/api/analytics/comparable_offers").json()
    assert data["matched_cohorts"] == 105
    assert data["active_offers"] == 210
    assert len(data["rows"]) == 100
    assert data["rows"][0]["product_norm"] == "item-000"
    assert data["rows"][-1]["product_norm"] == "item-099"
    assert all([o["chain_slug"] for o in row["chains"]] == ["a", "b"] for row in data["rows"])


def test_postgres_current_specials_and_double_precision_nulls(monkeypatch):
    """Opt-in, disposable localhost Postgres only; never connect to production."""
    dsn = os.environ.get("ANALYTICS_TEST_PG_DSN")
    if not dsn:
        pytest.skip("set ANALYTICS_TEST_PG_DSN for disposable local Postgres")
    parsed = urlparse(dsn)
    assert parsed.hostname == "127.0.0.1" and parsed.path == "/analytics_test"
    conn = db.connect(dsn)
    schema = f"analytics_{uuid4().hex}"
    try:
        conn.execute(f"CREATE SCHEMA {schema}")  # generated identifier, localhost-only
        conn.execute(f"SET search_path TO {schema}")
        db.init_db(conn)
        monkeypatch.setattr("api.main._analytics_conn", lambda: nullcontext(conn))
        today = datetime.now(ZoneInfo("America/Puerto_Rico")).date()
        run = conn.execute("INSERT INTO scrape_runs(chain_slug) VALUES (?)", ("a",)).lastrowid
        for chain, brand, size, price, start, end in (
            ("a", " Sello ", "3lb", 2.5, today, today),
            ("b", "sello", "3lb", 2.0, today, today),
            ("b", "sello", "5lb", 1.0, today, today),
            ("b", "sello", "3lb", None, today, today),
            ("b", "sello", "3lb", float("nan"), today, today),
            ("b", "sello", "3lb", 0, today, today),
            ("b", "sello", "3lb", 0.5, today, today),
            ("b", "sello", "3lb", 3.0, today - timedelta(days=1), today - timedelta(days=1)),
        ):
            conn.execute(
                "INSERT INTO offers(run_id,chain_slug,product_raw,product_norm,brand,size_canonical,"
                "price_basis,price_sale,valid_from,valid_to,source_url,promo) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (run, chain, "Arroz", "arroz", brand, size, "$/lb", price,
                 start, end, "https://example.test/flyer",
                 "2/$1.00" if price == 0.5 else None),
            )
        conn.commit()
        response = TestClient(app).get("/api/analytics/comparable_offers")
        assert response.status_code == 200
        data = response.json()
        assert data["as_of"] == str(today)
        assert data["active_offers"] == 4
        assert data["active_chains"] == 2
        assert data["matched_cohorts"] == 1
        assert [(o["chain_slug"], o["price_sale"]) for o in data["rows"][0]["chains"]] == [
            ("a", 2.5), ("b", 2.0)]
        assert data["rows"][0]["chains"][0]["valid_from"] == str(today)
    finally:
        conn.rollback()
        conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        conn.commit()
        conn.close()
