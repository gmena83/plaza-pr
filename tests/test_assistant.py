"""PLAZA's grounded assistant: auth/profile gates and real-offer boundaries."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from api import main as api


@pytest.fixture
def assistant_client(monkeypatch):
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE chains (slug TEXT PRIMARY KEY, name TEXT);
        INSERT INTO chains VALUES ('pueblo','Pueblo'), ('amigo','Amigo');
        CREATE TABLE lists (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL);
        CREATE TABLE list_items (id INTEGER PRIMARY KEY, list_id INTEGER, product_norm TEXT,
            size_canonical TEXT, any_size INTEGER, display_name TEXT, target_price REAL);
        CREATE TABLE profiles (user_id TEXT PRIMARY KEY, preferred_chains TEXT, shopping_cadence TEXT);
        CREATE TABLE offers (chain_slug TEXT, product_raw TEXT, product_norm TEXT, sku TEXT,
            size_text TEXT, size_canonical TEXT, price_sale REAL, price_regular REAL,
            promo TEXT, valid_from TEXT, valid_to TEXT, unit_price REAL, price_basis TEXT,
            category TEXT, source_url TEXT);
        INSERT INTO offers VALUES
          ('pueblo','Planet Oat leche de avena','planet oat leche de avena','1','32 OZ','32 OZ',2.69,NULL,NULL,'2026-01-01','2099-12-31',1.345,'$/lb','Lácteos','https://www.puebloweb.com/shopper'),
          ('amigo','Oatly leche de avena','oatly leche de avena','2','32 OZ','32 OZ',3.50,NULL,NULL,'2026-01-01','2099-12-31',1.75,'$/lb','Lácteos','https://apps.amigo.com/shopper'),
          ('pueblo','Quaker avena','quaker avena','3','10 OZ','10 OZ',1.00,NULL,NULL,'2026-01-01','2099-12-31',1.60,'$/lb','Provisiones','https://www.puebloweb.com/shopper'),
          ('pueblo','Gel ducha leche avena','gel ducha leche avena','4','42 OZ','42 OZ',0.50,NULL,NULL,'2026-01-01','2099-12-31',0.20,'$/lb','Higiene','https://www.puebloweb.com/shopper');
    """)
    c.commit()
    monkeypatch.setattr(api, "_conn", lambda: c)
    monkeypatch.setattr(api, "_auth_user", lambda req:
                        {"id": req.headers["authorization"].split()[-1], "email": "demo@example.test"}
                        if req.headers.get("authorization") else None)
    with TestClient(api.app) as t:
        yield t, c
    c.close()


def complete_profile(c, user="alice"):
    c.execute("INSERT INTO lists(id,user_id) VALUES(?,?)", (1 if user == "alice" else 2, user))
    c.execute("INSERT INTO list_items(id,list_id,product_norm,size_canonical,any_size,display_name) "
              "VALUES(?,?,?,?,?,?)", (1 if user == "alice" else 2, 1 if user == "alice" else 2,
                                      "arroz", "1 LB", 0, "Arroz"))
    c.execute("INSERT INTO profiles VALUES(?,?,?)", (user, json.dumps(["pueblo"]), "weekly"))
    c.commit()


def ask(t, message, user="alice"):
    return t.post("/api/assistant", headers={"Authorization": f"Bearer {user}"},
                  json={"message": message})


def test_assistant_requires_authentication_and_complete_profile(assistant_client):
    t, c = assistant_client
    assert t.post("/api/assistant", json={"message": "¿Dónde compro leche de avena?"}).status_code == 401
    assert ask(t, "¿Dónde compro leche de avena?").status_code == 403
    complete_profile(c)
    assert ask(t, "¿Dónde compro leche de avena?").status_code == 200
    assert ask(t, "¿Dónde compro leche de avena?", "bob").status_code == 403


def test_specials_count_is_current_and_deduplicated(assistant_client):
    t, c = assistant_client
    complete_profile(c)
    c.execute("INSERT INTO offers SELECT chain_slug,product_raw,product_norm,'dup',size_text,"
              "size_canonical,price_sale,price_regular,promo,valid_from,valid_to,unit_price,"
              "price_basis,category,source_url FROM offers WHERE sku='1'")
    c.execute("INSERT INTO offers SELECT chain_slug,product_raw,product_norm,'old',size_text,"
              "size_canonical,price_sale,price_regular,promo,'2020-01-01','2020-01-07',"
              "unit_price,price_basis,category,source_url FROM offers WHERE sku='2'")
    c.commit()
    d = ask(t, "¿Qué supermercado tiene más especiales hoy?").json()
    assert d["kind"] == "specials"
    assert d["counts"][0] == {"chain": "Pueblo", "count": 3}
    assert d["counts"][1] == {"chain": "Amigo", "count": 1}
    assert "registra" in d["answer"].lower()
    assert "no es un recuento completo" in d["answer"].lower()


def test_meat_answer_uses_current_per_pound_meat_not_repollo_or_bouillon(assistant_client):
    t, c = assistant_client
    complete_profile(c)
    c.executemany("INSERT INTO offers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("pueblo", "Repollo Verde", "repollo verde", "20", "1 LB", "1 LB", 0.35, None, None,
         "2026-01-01", "2099-12-31", 0.35, "$/lb", "Vegetales", None),
        ("pueblo", "Cubitos de carne", "cubitos de carne", "21", "1 LB", "1 LB", 0.50, None, None,
         "2026-01-01", "2099-12-31", 0.50, "$/lb", "Provisiones", None),
        ("pueblo", "Carne de cerdo para freír", "carne de cerdo para freir", "22", "1 LB", "1 LB", 1.88, None, None,
         "2026-01-01", "2099-12-31", 1.88, "$/lb", "Carnes", "https://www.puebloweb.com/shopper"),
        ("amigo", "Pechugas de pollo", "pechugas de pollo", "23", "LB", "1 LB", 2.49, None, None,
         "2026-01-01", "2099-12-31", 2.49, "$/lb", None, None),
        ("pueblo", "Pernil cerdo congelado", "pernil cerdo congelado", "25", "23-27 Libras", "23-27 LB", 1.49, None, None,
         "2026-01-01", "2099-12-31", 0.0552, "$/lb", "Carnes", None),
    ])
    c.commit()
    d = ask(t, "¿Dónde puedo comprar carne más barata?").json()
    assert d["kind"] == "meat"
    assert d["offers"][0]["price"] == 1.88
    assert "cerdo" in d["offers"][0]["product"].lower()
    assert all("repollo" not in o["product"].lower() and "cubitos" not in o["product"].lower()
               for o in d["offers"])
    assert "por libra" in d["answer"].lower()


def test_list_add_is_a_proposal_not_a_write(assistant_client):
    t, c = assistant_client
    complete_profile(c)
    before = c.execute("SELECT COUNT(*) FROM list_items").fetchone()[0]
    d = ask(t, "Agrega leche de avena a mi lista").json()
    assert d["kind"] == "list_proposal"
    assert len(d["actions"]) >= 1
    a = d["actions"][0]
    assert a["method"] == "POST" and a["path"] == "/api/list/items"
    assert a["params"]["product_norm"] in {"planet oat leche de avena", "oatly leche de avena"}
    assert a["requires_confirmation"] is True
    assert c.execute("SELECT COUNT(*) FROM list_items").fetchone()[0] == before


def test_list_remove_and_edit_are_scoped_to_account_and_not_applied(assistant_client):
    t, c = assistant_client
    complete_profile(c)
    complete_profile(c, "bob")
    d = ask(t, "Quita arroz de mi lista").json()
    assert d["kind"] == "list_proposal"
    assert [a["path"] for a in d["actions"]] == ["/api/list/items/1"]
    assert d["actions"][0]["method"] == "DELETE"
    changed = ask(t, "Cambia el precio meta de arroz a $3.50").json()
    assert changed["actions"][0]["method"] == "PATCH"
    assert changed["actions"][0]["params"] == {"target_price": 3.5}
    assert c.execute("SELECT COUNT(*) FROM list_items").fetchone()[0] == 2
    assert c.execute("SELECT target_price FROM list_items WHERE id=1").fetchone()[0] is None
    t.delete("/api/list/items/2", headers={"Authorization": "Bearer alice"})
    assert c.execute("SELECT id FROM list_items WHERE id=2").fetchone() is not None


def test_generic_cheapest_offer_answer_is_size_scoped_and_abstains_without_data(assistant_client):
    t, c = assistant_client
    complete_profile(c)
    c.executemany("INSERT INTO offers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("pueblo", "Arroz marca A", "arroz marca a", "30", "1 LB", "1 LB", 1.50, None, None,
         "2026-01-01", "2099-12-31", 1.50, "$/lb", "Provisiones", None),
        ("amigo", "Arroz marca B", "arroz marca b", "31", "1 LB", "1 LB", 1.70, None, None,
         "2026-01-01", "2099-12-31", 1.70, "$/lb", "Provisiones", None),
        ("amigo", "Arroz marca C", "arroz marca c", "32", "2 LB", "2 LB", 1.40, None, None,
         "2026-01-01", "2099-12-31", 0.70, "$/lb", "Provisiones", None),
    ])
    c.commit()
    d = ask(t, "¿Dónde compro arroz más barato?").json()
    assert d["kind"] == "price"
    assert len({x["size_canonical"] for x in d["offers"]}) == 1
    assert "no todo el inventario" in d["answer"].lower()
    missing = ask(t, "¿Dónde compro quinoa más barata?").json()
    assert missing["kind"] == "no_data" and missing["offers"] == []


def test_schema_defaults_email_notifications_off_for_new_accounts():
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "normalize/schema_users_pg.sql").read_text()
    assert "enabled          BOOLEAN NOT NULL DEFAULT false" in sql
    assert "ALTER TABLE email_prefs ALTER COLUMN enabled SET DEFAULT false" in sql


def test_new_account_email_digest_is_opt_in(assistant_client):
    t, c = assistant_client
    complete_profile(c)
    c.execute("CREATE TABLE email_prefs (user_id TEXT, enabled INTEGER)")
    c.commit()
    d = t.get("/api/list", headers={"Authorization": "Bearer alice"}).json()
    assert d["digest_enabled"] is False


def test_oat_milk_answer_excludes_oatmeal_and_body_wash_and_discloses_scope(assistant_client):
    t, c = assistant_client
    complete_profile(c)
    r = ask(t, "Where is the cheapest oat milk?")
    assert r.status_code == 200
    d = r.json()
    assert d["kind"] == "price"
    assert d["offers"][0]["chain"] == "Pueblo"
    assert d["offers"][0]["price"] == 2.69
    assert all("avena" in x["product"].lower() and "leche" in x["product"].lower()
               for x in d["offers"])
    assert "ofertas" in d["answer"].lower()
    assert "inventario" in d["answer"].lower()
