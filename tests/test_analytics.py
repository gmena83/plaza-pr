"""Deprecated analytics must not publish unequal-basket or future-price claims."""
import sqlite3
import pytest
from fastapi.testclient import TestClient
from api.main import app
from normalize import db


@pytest.mark.parametrize("fail_query", [False, True])
def test_comparable_offers_read_never_initializes_schema_and_closes_connection(
        monkeypatch, tmp_path, fail_query):
    db_path = tmp_path / "analytics.db"
    setup = db.connect(db_path)
    db.init_db(setup)
    setup.close()

    class TrackedConnection:
        def __init__(self):
            self.connection = sqlite3.connect(db_path)
            self.connection.row_factory = sqlite3.Row
            self.closed = False

        def execute(self, sql, *args):
            if fail_query:
                raise RuntimeError("query failed")
            return self.connection.execute(sql, *args)

        def close(self):
            self.closed = True
            self.connection.close()

    connections = []

    def connect(_dsn):
        connection = TrackedConnection()
        connections.append(connection)
        return connection

    def no_ddl(_conn):
        raise AssertionError("read endpoint must not execute schema DDL")

    monkeypatch.setattr(db, "connect", connect)
    monkeypatch.setattr(db, "dsn_from_env", lambda cfg: str(db_path))
    monkeypatch.setattr(db, "init_db", no_ddl)
    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/analytics/comparable_offers")
    assert response.status_code == (500 if fail_query else 200)
    assert len(connections) == 1
    assert connections[0].closed


@pytest.mark.parametrize("route", [
    "/api/analytics/overview",
    "/api/analytics/category_comparison",
    "/api/analytics/basket_projections",
])
def test_old_analytics_routes_reject_misleading_comparisons(route, monkeypatch):
    def no_database():
        raise AssertionError("retired route must not query the database")
    monkeypatch.setattr("api.main._conn", no_database)
    response = TestClient(app, raise_server_exceptions=False).get(route)
    assert response.status_code == 410
    assert response.json() == {"detail": "Analytics endpoint retired; use /api/analytics/comparable_offers"}


def test_unexpected_api_failure_has_generic_public_body_and_is_logged(monkeypatch, caplog):
    def broken_connection():
        raise RuntimeError("private DSN/password must not appear")
    monkeypatch.setattr("api.main._analytics_conn", broken_connection)
    response = TestClient(app, raise_server_exceptions=False).get("/api/analytics/comparable_offers")
    assert response.status_code == 500
    assert response.json() == {"error": "Internal server error"}
    assert "private DSN/password must not appear" not in response.text
    assert "private DSN/password must not appear" in caplog.text
