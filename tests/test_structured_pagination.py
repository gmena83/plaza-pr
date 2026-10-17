"""Structured shopper pagination must not silently accept incomplete pages."""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import sqlite3

import pytest

from scrapers import structured
from normalize import db
import run_weekly


def _card(sku):
    return (f'<div><a href="/productos/{sku}/detalle">'
            f'<span class="font-semibold">Sello</span>'
            f'<span class="uppercase tracking-wide text-sm">Arroz {sku}</span>'
            '</a><span class="text-xs text-gray-500">3 lb</span>'
            '<span class="text-lg font-semibold">$2.99</span></div>')


def _scrape(monkeypatch, pages, max_pages=6):
    requested = []

    def fake_get(url, sess):
        page = int(parse_qs(urlparse(url).query)["page"][0])
        requested.append(page)
        return SimpleNamespace(text=pages.get(page, ""))

    monkeypatch.setattr(structured, "get", fake_get)
    monkeypatch.setattr(structured, "session", lambda: object())
    chain = {"name": "Test", "base_url": "https://example.test",
             "products_endpoint": "/catalog?page={page}", "max_pages": max_pages}
    return chain, requested


def test_empty_first_page_is_failure_not_successful_empty_catalog(monkeypatch):
    chain, requested = _scrape(monkeypatch, {})
    with pytest.raises(ValueError, match="no products"):
        structured.scrape(chain)
    assert requested[:2] == [1, 2]


def test_empty_structured_scrape_records_failed_run(monkeypatch):
    chain, _ = _scrape(monkeypatch, {})
    chain["type"] = "structured"
    monkeypatch.setattr(run_weekly.validity, "detect", lambda *args: (
        "2026-10-17", "2026-10-23"))
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    try:
        result = run_weekly.run_chain(conn, {"chains": {"test": chain}}, "test")
        assert result["status"] == "error"
        assert "no products" in result["error"]
        run = conn.execute("SELECT status, offers_found FROM scrape_runs").fetchone()
        assert (run["status"], run["offers_found"]) == ("error", 0)
    finally:
        conn.close()


def test_single_empty_page_does_not_hide_later_products(monkeypatch):
    chain, requested = _scrape(monkeypatch, {1: _card(101), 3: _card(303)})
    offers = structured.scrape(chain)
    assert [offer["sku"] for offer in offers] == ["101", "303"]
    assert requested == [1, 2, 3, 4, 5]


def test_two_terminal_empty_pages_confirm_complete_collection(monkeypatch):
    chain, requested = _scrape(monkeypatch, {1: _card(101)})
    assert [offer["sku"] for offer in structured.scrape(chain)] == ["101"]
    assert requested == [1, 2, 3]


def test_exhausted_page_limit_with_products_is_not_a_complete_scrape(monkeypatch):
    chain, requested = _scrape(monkeypatch, {1: _card(101), 2: _card(202)}, max_pages=2)
    with pytest.raises(ValueError, match="page limit"):
        structured.scrape(chain)
    assert requested == [1, 2]
