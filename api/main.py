"""FastAPI read API for the shopper price database.

Run: uvicorn api.main:app --host 0.0.0.0 --port 8200
Endpoints:
  GET /health
  GET /chains
  GET /search?q=leche&chain=pueblo        -> matching current offers, best first
  GET /best/{product}                     -> best price per chain for a product term
  GET /offers?chain=selectos&limit=50     -> latest offers
  GET/POST/DELETE /api/list*              -> user shopping lists (Supabase Auth bearer)
"""
import json
import logging
import math
import os
import re
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import requests as http_requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from normalize import basket, db
from scrapers.common import load_config

app = FastAPI(title="PR Shopper Prices", version="0.1.0")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # list endpoints need POST/PATCH/DELETE; GET-only made every preflight 400
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    max_age=86400,
)
_cfg = load_config()

from fastapi.responses import HTMLResponse

_DASHBOARD = Path(__file__).resolve().parent / "static" / "dashboard.html"


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return _DASHBOARD.read_text()


def _conn():
    c = db.connect(db.dsn_from_env(_cfg))
    db.init_db(c)
    return c


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/chains")
def chains():
    c = _conn()
    rows = c.execute(
        "SELECT slug, name FROM chains ORDER BY name").fetchall()
    counts = c.execute(
        "SELECT chain_slug, COUNT(*) n FROM offers "
        "WHERE date('now') BETWEEN date(valid_from) AND date(valid_to) "
        "GROUP BY chain_slug").fetchall()
    cmap = {r["chain_slug"]: r["n"] for r in counts}
    return [{"slug": r["slug"], "name": r["name"],
             "active_offers": cmap.get(r["slug"], 0)} for r in rows]


@app.get("/search")
def search(q: str = Query(..., min_length=2),
           chain: str | None = None,
           limit: int = 50):
    c = _conn()
    term = f"%{q.strip().lower()}%"
    sql = (
        "SELECT chain_slug, product_raw, product_norm, sku, brand, size_text, size_canonical, "
        "price_sale, price_regular, promo, valid_from, valid_to, unit_price, price_basis FROM offers "
        "WHERE product_norm LIKE ? "
        "AND date('now') BETWEEN date(valid_from) AND date(valid_to) ")
    params: list = [term]
    if chain:
        sql += "AND chain_slug = ? "
        params.append(chain)
    sql += "ORDER BY price_sale ASC LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in c.execute(sql, params).fetchall()]
    return {"query": q, "count": len(rows), "results": rows}


@app.get("/best/{product}")
def best(product: str):
    c = _conn()
    term = f"%{product.strip().lower()}%"
    rows = c.execute(
        "SELECT MIN(product_norm) AS product_norm, MIN(price_sale) AS best_price, chain_slug "
        "FROM offers WHERE product_norm LIKE ? "
        "AND date('now') BETWEEN date(valid_from) AND date(valid_to) "
        "GROUP BY chain_slug ORDER BY best_price ASC",
        (term,)).fetchall()
    return {"product": product,
            "by_chain": [dict(r) for r in rows]}


@app.get("/offers")
def offers(chain: str | None = None, limit: int = 50, offset: int = 0):
    c = _conn()
    sql = ("SELECT chain_slug, product_raw, size_text, price_sale, promo, page "
           "FROM offers WHERE date('now') BETWEEN date(valid_from) AND date(valid_to) ")
    params: list = []
    if chain:
        sql += "AND chain_slug = ? "
        params.append(chain)
    sql += "ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    return [dict(r) for r in c.execute(sql, params).fetchall()]


@app.get("/api/stats")
def stats():
    """Dashboard summary metrics."""
    c = _conn()
    per_chain = c.execute(
        "SELECT chain_slug, COUNT(*) n, MIN(valid_from) vf, MAX(valid_to) vt "
        "FROM offers WHERE date('now') BETWEEN date(valid_from) AND date(valid_to) "
        "GROUP BY chain_slug ORDER BY n DESC").fetchall()
    total = c.execute(
        "SELECT COUNT(*) x FROM offers "
        "WHERE date('now') BETWEEN date(valid_from) AND date(valid_to)").fetchone()["x"]
    products = c.execute("SELECT COUNT(*) x FROM products").fetchone()["x"]
    weeks = c.execute(
        "SELECT COUNT(DISTINCT valid_from) x FROM offers").fetchone()["x"]
    last_runs = c.execute(
        "SELECT chain_slug, status, offers_found, valid_from, valid_to, started_at "
        "FROM scrape_runs WHERE id IN (SELECT MAX(id) FROM scrape_runs GROUP BY chain_slug) "
        "ORDER BY chain_slug").fetchall()
    # data-quality metrics
    unit_cov = c.execute(
        "SELECT COUNT(*) x FROM offers WHERE unit_price IS NOT NULL "
        "AND date('now') BETWEEN date(valid_from) AND date(valid_to)").fetchone()["x"]
    hist_points = c.execute("SELECT COUNT(*) x FROM v_price_history").fetchone()["x"]
    all_offers = c.execute("SELECT COUNT(*) x FROM offers").fetchone()["x"]
    chains_hist = c.execute(
        "SELECT COUNT(DISTINCT chain_slug) x FROM offers").fetchone()["x"]
    return {
        "total_active_offers": total,
        "all_time_offers": all_offers,
        "distinct_products": products,
        "weeks_of_history": weeks,
        "chains_tracked": chains_hist,
        "unit_price_coverage": unit_cov,
        "unit_price_pct": round(100 * unit_cov / total) if total else 0,
        "history_points": hist_points,
        "per_chain": [dict(r) for r in per_chain],
        "last_runs": [dict(r) for r in last_runs],
    }


@app.get("/api/history/{product}")
def history(product: str):
    """Price history for a product term across all chains and weeks."""
    c = _conn()
    term = f"%{product.strip().lower()}%"
    rows = c.execute(
        "SELECT product_norm, chain_slug, week_start, week_end, price_sale, "
        "price_regular, observations FROM v_price_history "
        "WHERE product_norm LIKE ? ORDER BY product_norm, chain_slug, week_start",
        (term,)).fetchall()
    return {"product": product, "points": [dict(r) for r in rows]}


@app.get("/api/movers")
def movers(direction: str = "down", limit: int = 20):
    """Biggest week-over-week price movers. direction=down|up."""
    c = _conn()
    order = "ASC" if direction == "down" else "DESC"
    rows = c.execute(
        f"""SELECT t.product_norm, p.display_name, t.chain_slug, t.week_start,
                   t.prev_price, t.price_sale, t.pct_change
            FROM v_price_trend t
            LEFT JOIN products p ON p.product_norm = t.product_norm
            WHERE t.pct_change IS NOT NULL
            ORDER BY t.pct_change {order} LIMIT ?""",
        (limit,)).fetchall()
    return {"direction": direction, "movers": [dict(r) for r in rows]}


@app.get("/api/best_unit/{product}")
def best_unit(product: str):
    """Best *unit* price per chain for a product, grouped by base_unit so we
    only compare like-for-like ($/lb vs $/lb, not a 1lb vs a 5lb pack)."""
    c = _conn()
    term = f"%{product.strip().lower()}%"
    rows = c.execute(
        """SELECT product_norm, chain_slug, base_unit,
                  MIN(unit_price) AS best_unit_price, MIN(price_basis) AS price_basis,
                  (SELECT product_raw FROM offers o2
                    WHERE o2.product_norm=o.product_norm AND o2.chain_slug=o.chain_slug
                      AND o2.unit_price IS NOT NULL
                      AND date('now') BETWEEN date(o2.valid_from) AND date(o2.valid_to)
                    ORDER BY o2.unit_price ASC LIMIT 1) AS example
           FROM offers o
           WHERE product_norm LIKE ? AND unit_price IS NOT NULL
             AND date('now') BETWEEN date(valid_from) AND date(valid_to)
           GROUP BY product_norm, chain_slug, base_unit
           ORDER BY base_unit, best_unit_price ASC""",
        (term,)).fetchall()
    # group by base_unit for clean comparison
    by_unit: dict = {}
    for r in rows:
        d = dict(r)
        by_unit.setdefault(d["base_unit"] or "?", []).append(d)
    return {"product": product, "by_base_unit": by_unit}


@app.get("/api/filters")
def filters(q: str = ""):
    """Distinct chains + sizes for the current search term, to drive filter dropdowns."""
    c = _conn()
    term = f"%{q.strip().lower()}%"
    chains = [r["chain_slug"] for r in c.execute(
        "SELECT DISTINCT chain_slug FROM offers WHERE product_norm LIKE ? "
        "AND date('now') BETWEEN date(valid_from) AND date(valid_to) ORDER BY chain_slug",
        (term,)).fetchall()]
    sizes = [r["size_canonical"] for r in c.execute(
        "SELECT DISTINCT size_canonical FROM offers WHERE product_norm LIKE ? "
        "AND size_canonical IS NOT NULL "
        "AND date('now') BETWEEN date(valid_from) AND date(valid_to) ORDER BY size_canonical",
        (term,)).fetchall()]
    return {"chains": chains, "sizes": sizes}


@app.get("/api/product")
def product_detail(name: str, size: str | None = None):
    """One product across all chains + weeks: detail for the popup.
    name = exact product_norm (from a clicked result)."""
    c = _conn()
    params: list = [name]
    sql = ("SELECT chain_slug, product_raw, sku, size_text, size_canonical, price_sale, "
           "price_regular, unit_price, price_basis, promo, valid_from, valid_to "
           "FROM offers WHERE product_norm = ? ")
    if size:
        sql += "AND (size_canonical = ? OR size_text = ?) "
        params += [size, size]
    sql += "ORDER BY valid_from DESC, price_sale ASC"
    rows = [dict(r) for r in c.execute(sql, params).fetchall()]
    # current-week best per chain
    return {"product": name, "size": size, "offers": rows}


@app.get("/api/product_history")
def product_history(name: str, size: str | None = None, chain: str | None = None):
    """Weekly price points for one product, optionally filtered to one chain."""
    c = _conn()
    params: list = [name]
    sql = ("SELECT chain_slug, valid_from AS week, MIN(price_sale) AS price, "
           "MIN(unit_price) AS unit_price, MIN(price_basis) AS price_basis "
           "FROM offers WHERE product_norm = ? ")
    if size:
        sql += "AND (size_canonical = ? OR size_text = ?) "
        params += [size, size]
    if chain:
        sql += "AND chain_slug = ? "
        params.append(chain)
    sql += "GROUP BY chain_slug, valid_from ORDER BY valid_from ASC"
    rows = [dict(r) for r in c.execute(sql, params).fetchall()]
    return {"product": name, "size": size, "chain": chain, "points": rows}


@app.get("/api/recommendation")
def recommendation(name: str, size: str | None = None):
    """Cycle-pattern buy recommendation for one product.

    Groups history by (chain, size_canonical) so cycles are detected on the
    SAME pack size across weeks (pack-size changes otherwise look like fake
    price swings). Uses normalize.cycle for alternating-cycle / trend /
    volatility analysis and an overall buy_now / wait / buy_cheapest verdict.
    """
    from normalize import reco
    result = reco.product_recommendation(_conn(), name, size)
    if result.get("_no_rows"):
        return {"product": name, "recommendation": None}
    return {"product": name, "size": size,
            "recommendation": result.get("verdict"),
            "chain_patterns": result.get("chains", [])}


# ─── Market Analytics & Comparisons ──────────────────────────────────────────

@contextmanager
def _analytics_conn():
    """Keep the comparison read scoped; schema setup belongs to ingestion."""
    c = db.connect(db.dsn_from_env(_cfg))
    try:
        yield c
    finally:
        c.close()


@app.get("/api/analytics/comparable_offers")
def comparable_offers():
    """Date-valid advertised specials only; exact item/pack/basis cohorts.

    Counters describe all active positive-price offers (including multi-buy),
    not just comparable ones. Exclude quantity-dependent promotions from
    matched cohorts; expose other promo restrictions without claiming stock.
    The bounded rows are a sample; matched_cohorts counts the complete set.
    """
    with _analytics_conn() as c:
        return _comparable_offers(c)


def _comparable_offers(c):
    as_of = datetime.now(ZoneInfo("America/Puerto_Rico")).date().isoformat()
    offers = c.execute(
        "SELECT id, chain_slug, product_norm, brand, size_canonical, price_basis, "
        "price_sale, valid_from, valid_to, source_url, promo FROM offers "
        "WHERE valid_from <= ? AND valid_to >= ? AND price_sale > 0",
        (as_of, as_of),
    ).fetchall()
    def printed_date(value):
        try:
            return date.fromisoformat(str(value)).isoformat() == str(value)
        except ValueError:
            return False

    active = [r for r in offers if math.isfinite(float(r["price_sale"]))
              and printed_date(r["valid_from"]) and printed_date(r["valid_to"])]
    groups = defaultdict(dict)
    for r in active:
        # Multi-buy per-unit prices require a quantity commitment; do not rank
        # them against a single-item price even if all identity fields match.
        if re.search(r"(?<!\w)\d+\s*(?:/\s*\$?\s*\d+|[x×]\s*\$?\s*\d+|por\s+\$?\s*\d+)",
                     r["promo"] or "", flags=re.IGNORECASE):
            continue
        chain = (r["chain_slug"] or "").strip()
        name = r["product_norm"]
        brand = " ".join((r["brand"] or "").split()).casefold()
        size = r["size_canonical"]
        basis = r["price_basis"]
        if not (chain and name and name.strip() and brand and size and size.strip()
                and basis and basis.strip()):
            continue
        key = (name, brand, size, basis)
        offer = {
            "chain_slug": chain, "price_sale": float(r["price_sale"]),
            "valid_from": str(r["valid_from"]), "valid_to": str(r["valid_to"]),
            "source_url": r["source_url"], "promo": r["promo"],
        }
        # Price first; dates, URL and ID make equal-price choices reproducible.
        rank = (offer["price_sale"], offer["valid_from"], offer["valid_to"],
                offer["source_url"] or "", r["id"])
        previous = groups[key].get(chain)
        if previous is None or rank < previous[0]:
            groups[key][chain] = (rank, offer)
    matched = sorted(key for key, chains in groups.items() if len(chains) >= 2)
    rows = [
        {
            "product_norm": key[0], "brand": key[1],
            "size_canonical": key[2], "price_basis": key[3],
            "chains": [groups[key][chain][1] for chain in sorted(groups[key])],
        }
        for key in matched[:100]
    ]
    return {
        "as_of": as_of, "scope": "advertised_specials_only",
        "active_offers": len(active),
        "active_chains": len({r["chain_slug"] for r in active if r["chain_slug"]}),
        "matched_cohorts": len(matched), "rows": rows,
    }

@app.get("/api/analytics/overview")
def analytics_overview():
    raise HTTPException(status_code=410, detail="Analytics endpoint retired; use /api/analytics/comparable_offers")


@app.get("/api/analytics/category_comparison")
def analytics_category_comparison():
    raise HTTPException(status_code=410, detail="Analytics endpoint retired; use /api/analytics/comparable_offers")


@app.get("/api/analytics/basket_projections")
def analytics_basket_projections():
    raise HTTPException(status_code=410, detail="Analytics endpoint retired; use /api/analytics/comparable_offers")


# ─── B2B demo (synthetic data while in beta) ─────────────────────────────────

@app.get("/api/b2b/overview")
def b2b_overview():
    """Aggregate user-activity metrics for brands/chains. Synthetic events
    until real usage accumulates (same queries, real table)."""
    c = _conn()
    weekly = c.execute(
        "SELECT to_char(date_trunc('week', ts), 'YYYY-MM-DD') AS week, kind, COUNT(*) n "
        "FROM events GROUP BY 1, 2 ORDER BY 1").fetchall()
    top_products = c.execute(
        "SELECT product_norm, COUNT(*) n, COUNT(DISTINCT user_cohort) users "
        "FROM events WHERE kind='search' AND product_norm IS NOT NULL "
        "GROUP BY 1 ORDER BY n DESC LIMIT 15").fetchall()
    brand_week = c.execute(
        "SELECT to_char(date_trunc('week', ts), 'YYYY-MM-DD') AS week, brand, COUNT(*) n "
        "FROM events WHERE brand IS NOT NULL AND kind IN ('search','list_add') "
        "GROUP BY 1, 2 ORDER BY 1, n DESC").fetchall()
    chain_engagement = c.execute(
        "SELECT chain_slug, COUNT(*) clicks, COUNT(DISTINCT user_cohort) users "
        "FROM events WHERE kind='offer_click' AND chain_slug IS NOT NULL "
        "GROUP BY 1 ORDER BY clicks DESC").fetchall()
    funnel = c.execute(
        "SELECT kind, COUNT(DISTINCT user_cohort) users FROM events GROUP BY kind").fetchall()
    return {
        "synthetic": True,
        "note": "datos sintéticos de demostración — se reemplazan con uso real",
        "weekly_activity": [dict(r) for r in weekly],
        "top_searches": [dict(r) for r in top_products],
        "brand_weekly": [dict(r) for r in brand_week],
        "chain_engagement": [dict(r) for r in chain_engagement],
        "funnel": [dict(r) for r in funnel],
    }


@app.get("/api/b2b/brand/{brand}")
def b2b_brand(brand: str):
    """One brand: weekly attention, campaign lift, price position vs category."""
    c = _conn()
    attention = c.execute(
        "SELECT to_char(date_trunc('week', ts), 'YYYY-MM-DD') AS week, COUNT(*) n, "
        "COUNT(DISTINCT user_cohort) users "
        "FROM events WHERE brand = ? GROUP BY 1 ORDER BY 1", (brand,)).fetchall()
    conversion = c.execute(
        "SELECT kind, COUNT(*) n FROM events WHERE brand = ? GROUP BY kind",
        (brand,)).fetchall()
    # real price position: brand's current offers vs category median
    prices = c.execute(
        "SELECT o.product_norm, o.chain_slug, o.price_sale, o.unit_price, o.price_basis "
        "FROM offers o WHERE o.brand = ? "
        "AND date('now') BETWEEN date(o.valid_from) AND date(o.valid_to) "
        "ORDER BY o.product_norm, o.unit_price LIMIT 200",
        (brand,)).fetchall()
    return {"brand": brand,
            "synthetic_events": True,
            "attention_weekly": [dict(r) for r in attention],
            "conversion": [dict(r) for r in conversion],
            "current_prices": [dict(r) for r in prices]}


# ─── user lists (Supabase Auth) ──────────────────────────────────────────────

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://blluhfmfslxpmacnqkox.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")


_AUTH_CACHE: dict[str, tuple[float, dict]] = {}
_AUTH_TTL = 60.0  # seconds; avoids a Supabase round-trip on every list click


def _auth_user(request: Request) -> dict | None:
    """Validate the Supabase access token via the Auth API. Returns {id, email}."""
    import time
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token:
        return None
    hit = _AUTH_CACHE.get(token)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    try:
        r = http_requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
            timeout=8)
        if r.status_code == 200:
            user = r.json()
            if len(_AUTH_CACHE) > 2000:
                _AUTH_CACHE.clear()
            _AUTH_CACHE[token] = (time.monotonic() + _AUTH_TTL, user)
            return user
    except http_requests.RequestException:
        pass
    return None


def _require_user(request: Request) -> dict:
    user = _auth_user(request)
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="login requerido")
    return user


def _ensure_list(c, user_id: str) -> int:
    lid = basket.user_default_list_id(c, user_id)
    if lid is None:
        c.execute("INSERT INTO lists(user_id, name) VALUES(?, 'Mi lista')", (user_id,))
        c.commit()
        lid = basket.user_default_list_id(c, user_id)
    return lid


def _own_list(c, request: Request) -> tuple[dict, int]:
    user = _require_user(request)
    return user, _ensure_list(c, user["id"])


@app.get("/api/profile")
def get_profile(request: Request):
    user = _require_user(request)
    c = _conn()
    row = c.execute("SELECT preferred_chains, shopping_cadence FROM profiles WHERE user_id = ?",
                    (user["id"],)).fetchone()
    chains = row["preferred_chains"] if row else []
    if isinstance(chains, str):
        chains = json.loads(chains)
    cadence = row["shopping_cadence"] if row else None
    n = c.execute("SELECT COUNT(*) n FROM list_items i JOIN lists l ON l.id = i.list_id "
                  "WHERE l.user_id = ?", (user["id"],)).fetchone()["n"]
    return {"preferred_chains": chains, "shopping_cadence": cadence,
            "list_item_count": n, "complete": bool(n and chains and cadence)}


class ProfilePrefs(BaseModel):
    preferred_chains: list[str]
    shopping_cadence: Literal["weekly", "biweekly", "monthly"]


@app.patch("/api/profile")
def update_profile(request: Request, prefs: ProfilePrefs):
    user = _require_user(request)
    c = _conn()
    chains = prefs.preferred_chains
    available = {r["slug"] for r in c.execute("SELECT slug FROM chains").fetchall()}
    if len(set(chains)) != len(chains) or not set(chains).issubset(available):
        raise HTTPException(status_code=400, detail="supermercado no válido o repetido")
    c.execute("INSERT INTO profiles(user_id, preferred_chains, shopping_cadence) "
              "VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
              "preferred_chains=excluded.preferred_chains, "
              "shopping_cadence=excluded.shopping_cadence, updated_at=CURRENT_TIMESTAMP",
              (user["id"], json.dumps(prefs.preferred_chains), prefs.shopping_cadence))
    c.commit()
    return get_profile(request)


class AssistantQuestion(BaseModel):
    message: str


@app.post("/api/assistant")
def ask_assistant(request: Request, question: AssistantQuestion):
    user = _require_user(request)
    if not get_profile(request)["complete"]:
        raise HTTPException(status_code=403, detail="Completa Mi Lista, tus supermercados preferidos y tu frecuencia de compra.")
    if not 3 <= len(question.message.strip()) <= 220:
        raise HTTPException(status_code=422, detail="Pregunta de 3 a 220 caracteres requerida")
    from api.assistant import answer
    return answer(_conn(), user["id"], question.message)


@app.get("/api/list")
def get_list(request: Request):
    c = _conn()
    user, lid = _own_list(c, request)
    items = basket.list_items(c, lid)
    result = basket.optimize(c, items) if items else {"items": [], "chains": [], "verdict": None}
    result["email"] = user.get("email")
    result["list_id"] = lid
    pref = c.execute("SELECT enabled FROM email_prefs WHERE user_id = ?", (user["id"],)).fetchone()
    result["digest_enabled"] = bool(pref["enabled"]) if pref else False   # explicit opt-in
    return result


# ─── email preferences + unsubscribe ─────────────────────────────────────────

@app.patch("/api/list/prefs")
def update_prefs(request: Request, digest: bool):
    c = _conn()
    user = _require_user(request)
    c.execute(
        "INSERT INTO email_prefs(user_id, enabled, unsubscribed_at, reason) VALUES(?, ?, "
        "CASE WHEN ? THEN NULL ELSE now() END, CASE WHEN ? THEN NULL ELSE 'toggle' END) "
        "ON CONFLICT (user_id) DO UPDATE SET enabled = excluded.enabled, "
        "unsubscribed_at = excluded.unsubscribed_at, reason = excluded.reason, updated_at = now()",
        (user["id"], digest, digest, digest))
    c.commit()
    return {"ok": True, "digest_enabled": digest}


def _unsub_page(title: str, body: str, form: str = "") -> HTMLResponse:
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>PLAZA · {title}</title>
<style>body{{margin:0;background:#0b0e11;color:#e8eef2;font-family:"SFMono-Regular",ui-monospace,Menlo,Consolas,monospace}}
.w{{max-width:520px;margin:12vh auto;padding:0 20px}}.c{{background:#11161b;border:1px solid #232d36;padding:26px}}
.l{{font-size:26px;font-weight:800;letter-spacing:-1px}}.l b{{color:#ffd400}}
h1{{font-size:15px;margin:22px 0 10px}}p{{color:#8fa1ad;font-size:13px;line-height:1.6;margin:0 0 12px}}
a{{color:#ffd400}}button{{background:#ffd400;color:#000;border:0;font-family:inherit;font-weight:800;
font-size:12px;letter-spacing:.06em;padding:11px 18px;cursor:pointer}}
button.ghost{{background:none;color:#8fa1ad;border:1px solid #232d36}}</style></head>
<body><div class="w"><div class="c"><div class="l">PLA<b>ZA</b></div><h1>{title}</h1>{body}{form}</div></div></body></html>"""
    return HTMLResponse(html)


def _token_ok(c, token: str) -> dict | None:
    if not token.isalnum() or len(token) > 80:
        return None
    return c.execute("SELECT enabled FROM email_prefs WHERE unsub_token = ?", (token,)).fetchone()


def _set_unsub(c, token: str, enabled: bool, reason: str) -> bool:
    if not token.isalnum() or len(token) > 80:
        return False
    row = c.execute(
        "UPDATE email_prefs SET enabled = ?, updated_at = now(), "
        "unsubscribed_at = CASE WHEN ? THEN NULL ELSE now() END, "
        "reason = CASE WHEN ? THEN NULL ELSE ? END WHERE unsub_token = ? RETURNING user_id",
        (enabled, enabled, enabled, reason, token)).fetchone()
    c.commit()
    return row is not None


_BAD_LINK = ("Enlace no válido",
             "<p>Este enlace no es válido. Puedes apagar los emails desde Mi Lista en "
             "<a href='https://plaza-pr.netlify.app/app/'>PLAZA</a>.</p>")


@app.get("/u/{token}", response_class=HTMLResponse)
def unsubscribe_page(token: str):
    """Footer link. GET only shows a one-button confirm page: mail security
    scanners pre-open links, so a GET that unsubscribed would opt people out
    without them clicking. Gmail/Yahoo's own button uses POST /u/{token}."""
    pref = _token_ok(_conn(), token)
    if not pref:
        return _unsub_page(*_BAD_LINK)
    if not pref["enabled"]:
        return _unsub_page(
            "Ya no recibes el resumen",
            "<p>Tu lista sigue guardada en PLAZA.</p>",
            f"<form method='post' action='/u/{token}/resubscribe'>"
            "<button class='ghost'>VOLVER A RECIBIRLO</button></form>")
    return _unsub_page(
        "¿Dejar de recibir el resumen de Mi Lista?",
        "<p>Te lo enviamos lunes y jueves con las ofertas de tu lista. "
        "Tu lista seguirá guardada en PLAZA.</p>",
        f"<form method='post' action='/u/{token}/confirm'><button>SÍ, DEJAR DE RECIBIRLO</button></form>")


@app.post("/u/{token}/confirm", response_class=HTMLResponse)
def unsubscribe_confirm(token: str):
    if not _set_unsub(_conn(), token, False, "link"):
        return _unsub_page(*_BAD_LINK)
    return _unsub_page(
        "Listo, no recibirás más resúmenes",
        "<p>Tu lista sigue guardada en PLAZA; solo dejamos de enviarte el resumen de lunes y jueves.</p>",
        f"<form method='post' action='/u/{token}/resubscribe'>"
        "<button class='ghost'>ME EQUIVOQUÉ, VOLVER A RECIBIRLO</button></form>")


@app.post("/u/{token}")
def unsubscribe_one_click(token: str):
    """RFC 8058 one-click unsubscribe (Gmail/Yahoo 'Unsubscribe' button)."""
    _set_unsub(_conn(), token, False, "one_click")
    return {"ok": True}


@app.post("/u/{token}/resubscribe", response_class=HTMLResponse)
def resubscribe(token: str):
    if not _set_unsub(_conn(), token, True, ""):
        return _unsub_page(*_BAD_LINK)
    return _unsub_page("Suscripción reactivada",
                       "<p>Volverás a recibir el resumen de Mi Lista los lunes y jueves. "
                       "<a href='https://plaza-pr.netlify.app/app/'>Abrir PLAZA</a></p>")


@app.post("/api/list/items")
def add_item(request: Request, product_norm: str, display_name: str = "",
             size: str | None = None, any_size: bool = False,
             target_price: float | None = None):
    c = _conn()
    _, lid = _own_list(c, request)
    # '' (not NULL) for "no size" so the UNIQUE constraint dedupes re-adds
    row = c.execute(
        "INSERT INTO list_items(list_id, product_norm, size_canonical, any_size, display_name, target_price) "
        "VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(list_id, product_norm, size_canonical) DO UPDATE SET "
        "any_size=excluded.any_size, "
        "display_name=COALESCE(excluded.display_name, list_items.display_name) "
        "RETURNING id",
        (lid, product_norm, size or "", any_size or not size, display_name or None,
         target_price)).fetchone()
    c.commit()
    n = c.execute("SELECT COUNT(*) n FROM list_items WHERE list_id = ?", (lid,)).fetchone()
    return {"ok": True, "item_id": row["id"] if row else None, "count": n["n"]}


@app.patch("/api/list/items/{item_id}")
def update_item(request: Request, item_id: int, any_size: bool | None = None,
                target_price: float | None = None, clear_target: bool = False):
    c = _conn()
    _, lid = _own_list(c, request)
    sets, params = [], []
    if any_size is not None:
        sets.append("any_size = ?")
        params.append(any_size)
    if target_price is not None:
        sets.append("target_price = ?")
        params.append(target_price)
    elif clear_target:
        sets.append("target_price = NULL")
    if not sets:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="nada que actualizar")
    c.execute(f"UPDATE list_items SET {', '.join(sets)} WHERE id = ? AND list_id = ?",
              (*params, item_id, lid))
    c.commit()
    return {"ok": True}


@app.delete("/api/list/items/{item_id}")
def remove_item(request: Request, item_id: int):
    c = _conn()
    _, lid = _own_list(c, request)
    c.execute("DELETE FROM list_items WHERE id = ? AND list_id = ?", (item_id, lid))
    c.commit()
    return {"ok": True}


@app.exception_handler(Exception)
def on_err(request, exc):  # noqa: ANN001
    logging.getLogger("pr-shopper.api").exception("Unhandled API error", exc_info=exc)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})
