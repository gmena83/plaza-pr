"""Basket intelligence: cheapest chain for a shopping list this week.

For each list item, find the best current offer per chain (unit price when
comparable, else sticker). A chain's basket total is the sum over items it
carries. Chains carrying fewer items get penalized in ranking (a cheap
partial basket isn't useful if you still need a second store).
"""
import os

from . import db

_cfg = {"db_path": os.environ.get("DATABASE_URL", "")}


def _conn():
    c = db.connect(db.dsn_from_env(_cfg) if _cfg["db_path"] else os.environ["DATABASE_URL"])
    db.init_db(c)
    return c


def list_items(conn, list_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, product_norm, size_canonical, any_size, display_name, target_price "
        "FROM list_items WHERE list_id = ? ORDER BY id", (list_id,)).fetchall()
    return [dict(r) for r in rows]


def best_offers_for_item(conn, item: dict) -> list[dict]:
    """Best current offer per chain for one item (unit price preferred)."""
    params: list = [item["product_norm"]]
    sql = ("SELECT chain_slug, product_raw, price_sale, price_regular, promo, "
           "unit_price, price_basis, size_canonical, size_text, valid_from, valid_to "
           "FROM offers WHERE product_norm = ? "
           "AND date('now') BETWEEN date(valid_from) AND date(valid_to)")
    if not item["any_size"] and item["size_canonical"]:
        sql += " AND (size_canonical = ? OR size_text = ?)"
        params += [item["size_canonical"], item["size_canonical"]]
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    best: dict = {}
    for r in rows:
        key = r["chain_slug"]
        rank = r["unit_price"] if r["unit_price"] is not None else r["price_sale"]
        if key not in best or rank < best[key]["_rank"]:
            r["_rank"] = rank
            best[key] = r
    return list(best.values())


def optimize(conn, items: list[dict]) -> dict:
    """Compute per-chain basket totals + a verdict."""
    per_item = {it["id"]: best_offers_for_item(conn, it) for it in items}
    chains: dict = {}
    for it in items:
        for offer in per_item[it["id"]]:
            chains.setdefault(offer["chain_slug"], {"total": 0.0, "found": 0, "items": {}})
            c = chains[offer["chain_slug"]]
            c["total"] += offer["price_sale"]
            c["found"] += 1
            c["items"][it["id"]] = offer

    n_items = len(items)
    ranked = sorted(
        ({"chain": k, "total": round(v["total"], 2), "found": v["found"],
          "coverage": round(100 * v["found"] / n_items) if n_items else 0}
         for k, v in chains.items()),
        key=lambda x: (-x["found"], x["total"]))

    full = [r for r in ranked if r["found"] == n_items and n_items > 0]
    verdict = None
    if full:
        winner = full[0]
        runner_up = full[1] if len(full) > 1 else None
        saving = round(runner_up["total"] - winner["total"], 2) if runner_up else 0
        verdict = {
            "chain": winner["chain"],
            "total": winner["total"],
            "saving_vs_next": saving,
            "message": (
                f"Esta semana compra tu lista en {winner['chain']}: "
                f"total ${winner['total']:.2f}"
                + (f", ${saving:.2f} menos que la siguiente opción." if saving > 0 else ".")),
        }

    per_item_out = []
    for it in items:
        offers = sorted(per_item[it["id"]],
                        key=lambda o: o["_rank"])
        best = offers[0] if offers else None
        per_item_out.append({
            "item_id": it["id"], "product_norm": it["product_norm"],
            "display_name": it["display_name"], "size": it["size_canonical"] or "",
            "any_size": bool(it["any_size"]),
            "target_price": it["target_price"],
            "best": ({k: v for k, v in best.items() if k != "_rank"} if best else None),
            "on_sale": bool(best and it["target_price"] and best["price_sale"] <= it["target_price"]),
            "n_chains": len(offers),
        })
    return {"items": per_item_out, "chains": ranked, "verdict": verdict}


def store_plan(items: list[dict], per_item: dict) -> dict | None:
    """Best 1- or 2-store plan for a list.

    per_item: {item_id: [best offer per chain, each with '_rank']}. Picks the
    single chain covering the most items (cheapest on ties); if some pair of
    chains covers strictly more, recommends the pair, assigning each item to
    the cheaper of the two. Returns None when no item has a current offer.
    """
    from itertools import combinations

    by_chain: dict = {}
    for it in items:
        for o in per_item.get(it["id"], []):
            by_chain.setdefault(o["chain_slug"], {})[it["id"]] = o
    if not by_chain:
        return None

    def evaluate(chains: tuple) -> dict:
        assign, total, regular_saving = {}, 0.0, 0.0
        for it in items:
            cands = [by_chain[c][it["id"]] for c in chains if it["id"] in by_chain[c]]
            if not cands:
                continue
            o = min(cands, key=lambda x: x["_rank"])
            assign[it["id"]] = o
            total += o["price_sale"] or 0
            reg = o.get("price_regular")
            if reg and o["price_sale"] and o["price_sale"] < reg < o["price_sale"] * 5:
                regular_saving += reg - o["price_sale"]
        return {"stores": list(chains), "covered": len(assign), "total": round(total, 2),
                "regular_saving": round(regular_saving, 2), "assign": assign}

    available = {iid for offers in by_chain.values() for iid in offers}
    best_price = {iid: min(o["price_sale"] or 0 for o in per_item[iid]) for iid in available}

    def key(p: dict) -> tuple:
        # equal coverage -> compare what the WHOLE list costs: plan items at the
        # plan's stores + the rest at their best price elsewhere. Comparing plan
        # totals alone would reward pairs that happen to cover cheaper items.
        rest = sum(best_price[i] for i in available - set(p["assign"]))
        return (-p["covered"], round(p["total"] + rest, 2))

    best_single = min((evaluate((c,)) for c in by_chain), key=key)
    plan = best_single
    if best_single["covered"] < len(items) and len(by_chain) > 1:
        best_pair = min((evaluate(pair) for pair in combinations(sorted(by_chain), 2)), key=key)
        if best_pair["covered"] > best_single["covered"]:
            # list the store carrying more of the plan first
            counts = {c: sum(1 for o in best_pair["assign"].values() if o["chain_slug"] == c)
                      for c in best_pair["stores"]}
            best_pair["stores"].sort(key=lambda c: -counts[c])
            plan = best_pair

    plan["n_items"] = len(items)
    plan["elsewhere"] = sorted(available - set(plan["assign"]))   # on offer at a 3rd store
    plan["unavailable"] = [it["id"] for it in items if it["id"] not in available]
    return plan


def user_default_list_id(conn, user_id: str) -> int | None:
    r = conn.execute("SELECT id FROM lists WHERE user_id = ? ORDER BY id LIMIT 1",
                     (user_id,)).fetchone()
    return r["id"] if r else None
