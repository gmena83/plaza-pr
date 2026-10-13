"""Local profile API contract, with isolated in-memory data and fake Auth identity."""
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import main as api


@pytest.fixture
def client(monkeypatch):
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE chains (slug TEXT PRIMARY KEY);
        INSERT INTO chains VALUES ('pueblo'), ('amigo');
        CREATE TABLE lists (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL);
        CREATE TABLE list_items (id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL);
        CREATE TABLE profiles (
            user_id TEXT PRIMARY KEY, preferred_chains TEXT NOT NULL DEFAULT '[]',
            shopping_cadence TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    """)
    monkeypatch.setattr(api, "_conn", lambda: c)
    monkeypatch.setattr(api, "_auth_user", lambda req:
                        {"id": req.headers["authorization"].split()[-1]}
                        if req.headers.get("authorization") else None)
    with TestClient(api.app) as t:
        yield t, c
    c.close()


def test_profile_requires_auth_and_starts_incomplete(client):
    t, _ = client
    assert t.get("/api/profile").status_code == 401
    r = t.get("/api/profile", headers={"Authorization": "Bearer alice"})
    assert r.status_code == 200
    assert r.json() == {"preferred_chains": [], "shopping_cadence": None,
                        "list_item_count": 0, "complete": False}


def test_profile_owner_can_set_preferences_but_requires_a_saved_item(client):
    t, c = client
    alice = {"Authorization": "Bearer alice"}
    bob = {"Authorization": "Bearer bob"}
    r = t.patch("/api/profile", headers=alice,
                json={"preferred_chains": ["amigo", "pueblo"], "shopping_cadence": "weekly"})
    assert r.status_code == 200
    assert r.json()["complete"] is False
    assert t.get("/api/profile", headers=bob).json()["preferred_chains"] == []
    c.execute("INSERT INTO lists(id,user_id) VALUES(1,'alice')")
    c.execute("INSERT INTO list_items(id,list_id) VALUES(1,1)")
    c.commit()
    assert t.get("/api/profile", headers=alice).json() == {
        "preferred_chains": ["amigo", "pueblo"], "shopping_cadence": "weekly",
        "list_item_count": 1, "complete": True}
    assert t.get("/api/profile", headers=bob).json()["complete"] is False


@pytest.mark.parametrize("chains,cadence", [
    (["unknown"], "weekly"), (["pueblo", "pueblo"], "monthly"),
    (["pueblo"], "daily"), (["PUEBLO"], "weekly")])
def test_profile_rejects_invalid_store_or_cadence_without_writing(client, chains, cadence):
    t, c = client
    r = t.patch("/api/profile", headers={"Authorization": "Bearer alice"},
                json={"preferred_chains": chains, "shopping_cadence": cadence})
    assert r.status_code in (400, 422)
    assert c.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 0


def test_profile_update_requires_auth(client):
    t, c = client
    r = t.patch("/api/profile", json={"preferred_chains": ["pueblo"],
                                      "shopping_cadence": "weekly"})
    assert r.status_code == 401
    assert c.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 0


def test_profile_pg_migration_is_api_only_and_keeps_user_id_unique():
    sql = (Path(__file__).parents[1] / "normalize/schema_users_pg.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS profiles" in sql
    assert "user_id UUID PRIMARY KEY" in sql
    assert "ALTER TABLE profiles ENABLE ROW LEVEL SECURITY" in sql
    assert "REVOKE ALL ON profiles FROM anon, authenticated" in sql
