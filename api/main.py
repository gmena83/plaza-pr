"""FastAPI read API for the shopper price database.

Run: uvicorn api.main:app --host 0.0.0.0 --port 8200
Endpoints:
  GET /health
  GET /chains
  GET /search?q=leche&chain=pueblo        -> matching current offers, best first
  GET /best/{product}                     -> best price per chain for a product term
  GET /offers?chain=selectos&limit=50     -> latest offers
"""
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from normalize import db
from scrapers.common import load_config

app = FastAPI(title="PR Shopper Prices", version="0.1.0")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
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
    from normalize import cycle
    c = _conn()
    params: list = [name]
    sql = ("SELECT chain_slug, size_canonical, valid_from AS week, "
           "MIN(price_sale) AS price, MIN(unit_price) AS unit_price, "
           "MIN(price_basis) AS price_basis "
           "FROM offers WHERE product_norm = ? ")
    if size:
        sql += "AND (size_canonical = ? OR size_text = ?) "
        params += [size, size]
    sql += ("GROUP BY chain_slug, size_canonical, valid_from "
            "ORDER BY chain_slug, size_canonical, valid_from")
    rows = [dict(r) for r in c.execute(sql, params).fetchall()]
    if not rows:
        return {"product": name, "recommendation": None}

    # pick the dominant (most-observed) chain+size series as the primary subject,
    # but analyze every chain+size and let cycle.recommend pick the verdict.
    points = [{"chain_slug": r["chain_slug"], "week": r["week"], "price": r["price"],
               "unit_price": r["unit_price"], "price_basis": r["price_basis"],
               "size": r["size_canonical"]} for r in rows]
    # analyze per chain using its dominant size series
    from collections import defaultdict
    by_chain_size = defaultdict(list)
    for p in points:
        by_chain_size[(p["chain_slug"], p["size"] or "")].append(p)
    # keep the size series with most weeks per chain
    per_chain: dict = {}
    for (chain, sz), pts in by_chain_size.items():
        if chain not in per_chain or len(pts) > len(per_chain[chain]):
            per_chain[chain] = pts
    flat_points = []
    for chain, pts in per_chain.items():
        for p in sorted(pts, key=lambda x: x["week"]):
            flat_points.append({"chain_slug": chain, "week": p["week"],
                                "price": p["price"], "unit_price": p["unit_price"],
                                "price_basis": p["price_basis"]})
    result = cycle.recommend(flat_points)
    return {"product": name, "size": size,
            "recommendation": result.get("verdict"),
            "chain_patterns": result.get("chains", [])}


@app.exception_handler(Exception)
def on_err(request, exc):  # noqa: ANN001
    return JSONResponse(status_code=500, content={"error": str(exc)})
