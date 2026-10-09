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
    sql = ("SELECT chain_slug, product_raw, price_sale, unit_price, price_basis, "
           "size_canonical, size_text, valid_from, valid_to "
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
            "display_name": it["display_name"], "size": it["size_canonical"],
            "target_price": it["target_price"],
            "best": ({k: v for k, v in best.items() if k != "_rank"} if best else None),
            "on_sale": bool(best and it["target_price"] and best["price_sale"] <= it["target_price"]),
            "n_chains": len(offers),
        })
    return {"items": per_item_out, "chains": ranked, "verdict": verdict}


def user_default_list_id(conn, user_id: str) -> int | None:
    r = conn.execute("SELECT id FROM lists WHERE user_id = ? ORDER BY id LIMIT 1",
                     (user_id,)).fetchone()
    return r["id"] if r else None
