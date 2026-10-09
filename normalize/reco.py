"""Per-product buy-timing recommendation, shared by the API and the email digest.

Wraps normalize.cycle: pulls the product's weekly history from `offers`,
keeps each chain's dominant pack-size series (pack-size changes otherwise
look like fake price swings), and asks cycle.recommend for a verdict.
"""
from __future__ import annotations

from collections import defaultdict

from . import cycle


def product_recommendation(conn, name: str, size: str | None = None) -> dict:
    """Returns {"verdict": {...} | None, "chains": [ChainPattern dicts]}."""
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
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    if not rows:
        return {"verdict": None, "chains": [], "_no_rows": True}

    by_chain_size: dict = defaultdict(list)
    for r in rows:
        by_chain_size[(r["chain_slug"], r["size_canonical"] or "")].append(r)
    per_chain: dict = {}
    for (chain, _sz), pts in by_chain_size.items():
        if chain not in per_chain or len(pts) > len(per_chain[chain]):
            per_chain[chain] = pts
    flat = [{"chain_slug": chain, "week": p["week"], "price": p["price"],
             "unit_price": p["unit_price"], "price_basis": p["price_basis"]}
            for chain, pts in per_chain.items()
            for p in sorted(pts, key=lambda x: str(x["week"]))]
    return cycle.recommend(flat)
