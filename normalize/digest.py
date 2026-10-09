"""Mi Lista email digest: per-user recommendations, sent Mondays and Thursdays.

build_digest() turns one user's list into a render-ready dict (store plan,
per-item advice, changes vs the previous circular, expiring offers).
render_digest() fills the Jinja templates in templates/. Sending, logging
and scheduling live in notify_lists.py.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from . import basket, reco

PR_TZ = ZoneInfo("America/Puerto_Rico")
SLOT_WEEKDAYS = (0, 3)            # Monday, Thursday
TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
MONO = "'SFMono-Regular',Menlo,Consolas,'Liberation Mono','Courier New',monospace"

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DIAS_CORTO = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
NB = "\u00a0"   # keeps "mié 21", "3 de 6", "ahorras ~$1.84" from splitting on phones
# circular fine print that adds noise, not information
_PROMO_NOISE = ("raincheck", "sustitut", "limite", "límite", "hasta agotar", "mientras dure",
                "aplican", "restriccion", "restricción")

# same palette as the dashboard (api/static/dashboard.html COLORS)
CHAIN_COLORS = {"pueblo": "#3aa6ff", "amigo": "#ff5a3c", "selectos": "#2fd6a3",
                "supermax": "#ffd400", "econo": "#c792ff", "walmart": "#8fd14f",
                "ralphs": "#ff9d3c", "migente": "#4fd6ff", "mrspecial": "#ff6fb1",
                "agranel": "#9dff4f", "freshmart": "#4fffc9", "plazaloiza": "#d64fff"}
_SHORT = {"walmart": "Walmart", "ralphs": "Ralph's", "mrspecial": "Mr. Special",
          "supermax": "SuperMax", "freshmart": "Freshmart"}


def today_pr() -> dt.date:
    return dt.datetime.now(PR_TZ).date()


def slot_for(day: dt.date) -> dt.date:
    """Most recent Monday or Thursday on/before `day`: the idempotency period.
    A catch-up run on Tuesday still belongs to Monday's slot."""
    for back in range(7):
        d = day - dt.timedelta(days=back)
        if d.weekday() in SLOT_WEEKDAYS:
            return d
    raise AssertionError("unreachable")


def chain_names(conn) -> dict:
    return {r["slug"]: r["name"] for r in conn.execute("SELECT slug, name FROM chains").fetchall()}


def short_chain(slug: str, names: dict | None = None) -> str:
    if slug in _SHORT:
        return _SHORT[slug]
    n = (names or {}).get(slug, slug)
    for pre in ("Supermercados ", "Supermercado "):
        if n.startswith(pre):
            n = n[len(pre):]
    return n


def pretty_name(s: str | None) -> str:
    s = (s or "").strip()
    if s.isupper() and len(s) > 3:
        s = s.capitalize()
    return s[:64]


def pretty_size(s: str | None) -> str:
    s = (s or "").strip()
    s = re.sub(r"(\d)\.0(?=\D|$)", r"\1", s)        # 8.0x10oz -> 8x10oz
    return re.sub(r"(?<=\d)x(?=\d)", " × ", s)      # 8x10oz -> 8 × 10oz


def fmt_unit(v: float | None, basis: str | None) -> str | None:
    if not v:
        return None
    num = f"${v:.3f}" if v < 0.10 else f"${v:.2f}"   # 3 decimals only where cents would vanish
    return num + (basis or "").replace("$", "")


def clean_promo(p: str | None) -> str | None:
    p = (p or "").strip()
    if not p or len(p) > 24 or any(w in p.lower() for w in _PROMO_NOISE):
        return None
    return p


def pct_off(price: float, regular: float | None) -> int | None:
    """Discount vs the chain's own regular price; ignores implausible regulars."""
    if not regular or not price or not (price + 0.01 < regular < price * 5):
        return None
    return round((regular - price) / regular * 100)


def _as_date(v) -> dt.date | None:
    if v is None:
        return None
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])


def date_label(d: dt.date) -> str:
    return f"{DIAS[d.weekday()]} {d.day} {MESES[d.month - 1]}"


def _prior_price(conn, offer: dict, item: dict) -> float | None:
    """Same chain's sale price on its previous circular, for the 'bajó $X' line."""
    params: list = [offer["chain_slug"], item["product_norm"], offer["valid_from"]]
    sql = ("SELECT valid_from, MIN(price_sale) AS p FROM offers "
           "WHERE chain_slug = ? AND product_norm = ? AND valid_from < ? ")
    if not item["any_size"] and item["size_canonical"]:
        sql += "AND (size_canonical = ? OR size_text = ?) "
        params += [item["size_canonical"], item["size_canonical"]]
    sql += "GROUP BY valid_from ORDER BY valid_from DESC LIMIT 1"
    r = conn.execute(sql, params).fetchone()
    return r["p"] if r and r["p"] else None


def _badge(item: dict, offer: dict, verdict: dict | None, delta: float | None,
           names: dict) -> dict | None:
    """One advice line per item, most useful first."""
    target = item.get("target_price")
    if target and offer["price_sale"] <= target:
        return {"kind": "deal", "text": f"Llegó a tu precio · ${target:.2f}"}
    if verdict:
        where = short_chain(verdict["chain"], names)
        same = verdict["chain"] == offer["chain_slug"]
        if verdict["action"] == "buy_now" and verdict.get("saving_pct", 0) >= 5:
            return {"kind": "deal", "text": f"Oferta real · {verdict['saving_pct']}% bajo su promedio"
                    + ("" if same else f" en {where}")}
        if verdict["action"] == "wait":
            return {"kind": "wait", "text": f"Espera · en {where} suele bajar {verdict.get('when', 'pronto')}"}
        if verdict["action"] == "buy_soon":
            return {"kind": "soon", "text": "Subiendo · mejor comprar ya"}
    if delta is not None and delta <= -0.05:
        return {"kind": "down", "text": f"Bajó ${-delta:.2f} vs su shopper anterior"}
    off = pct_off(offer["price_sale"], offer.get("price_regular"))
    if off and off >= 20:
        return {"kind": "deal", "text": f"{off}% menos que su precio regular"}
    return None


def _row(conn, item: dict, offer: dict, today: dt.date, names: dict) -> dict:
    size_filter = None if item["any_size"] else (item["size_canonical"] or None)
    verdict = reco.product_recommendation(conn, item["product_norm"], size_filter).get("verdict")
    prior = _prior_price(conn, offer, item)
    delta = round(offer["price_sale"] - prior, 2) if prior is not None else None

    meta = []
    unit = fmt_unit(offer.get("unit_price"), offer.get("price_basis"))
    if unit:
        meta.append({"text": unit, "style": ""})
    reg = offer.get("price_regular")
    regular = round(reg, 2) if reg and pct_off(offer["price_sale"], reg) else None
    promo = clean_promo(offer.get("promo"))
    if promo:
        meta.append({"text": promo, "style": ""})
    vt = _as_date(offer.get("valid_to"))
    ends_soon = False
    if vt:
        days_left = (vt - today).days
        ends_soon = days_left <= 2
        lbl = f"{DIAS_CORTO[vt.weekday()]}{NB}{vt.day}"
        meta.append({"text": ("termina" if ends_soon else "hasta") + NB + lbl,
                     "style": "warn" if ends_soon else ""})

    return {"item_id": item["id"],
            "name": pretty_name(item["display_name"] or offer.get("product_raw") or item["product_norm"]),
            "size": "cualquier tamaño" if item["any_size"] else pretty_size(item["size_canonical"]),
            "chain": offer["chain_slug"], "chain_short": short_chain(offer["chain_slug"], names),
            "color": CHAIN_COLORS.get(offer["chain_slug"], "#8fa1ad"),
            "price": round(offer["price_sale"], 2), "regular": regular,
            "meta": meta, "ends_soon": ends_soon,
            "delta": delta, "badge": _badge(item, offer, verdict, delta, names)}


def build_digest(conn, list_id: int, *, today: dt.date | None = None,
                 slot: dt.date | None = None, names: dict | None = None) -> dict:
    today = today or today_pr()
    slot = slot or slot_for(today)
    names = names if names is not None else chain_names(conn)
    items = basket.list_items(conn, list_id)
    per_item = {it["id"]: basket.best_offers_for_item(conn, it) for it in items}
    plan = basket.store_plan(items, per_item)
    n = len(items)
    base = {"n_items": n, "slot": slot.isoformat(), "date_label": date_label(slot),
            "is_thursday": slot.weekday() == 3}
    if not items or plan is None:
        return {**base, "send": False, "reason": "no_deals", "n_deals": 0}

    by_id = {it["id"]: it for it in items}
    stores = []
    for slug in plan["stores"]:
        rows = [_row(conn, by_id[iid], o, today, names)
                for iid, o in plan["assign"].items() if o["chain_slug"] == slug]
        stores.append({"slug": slug, "short": short_chain(slug, names),
                       "color": CHAIN_COLORS.get(slug, "#8fa1ad"), "rows": rows,
                       "subtotal": round(sum(r["price"] for r in rows), 2)})
    elsewhere = []
    for iid in plan["elsewhere"]:
        best = min(per_item[iid], key=lambda o: o["_rank"])
        elsewhere.append(_row(conn, by_id[iid], best, today, names))
    unavailable = [pretty_name(by_id[iid]["display_name"] or by_id[iid]["product_norm"])
                   for iid in plan["unavailable"]]

    n_deals = n - len(plan["unavailable"])
    labels = [s["short"] for s in stores]
    stores_label = " + ".join(labels)
    covered = plan["covered"]
    if len(stores) == 1 and covered == n:
        headline = f"Esta semana compra toda tu lista en {stores_label}"
    elif len(stores) == 1:
        headline = f"{stores_label} tiene {covered}{NB}de{NB}{n} productos de tu lista en oferta"
    else:
        headline = f"{stores_label} cubren {covered}{NB}de{NB}{n} productos de tu lista"
    total_line = f"Total estimado{NB}${plan['total']:.2f}"
    if covered < n:
        total_line += f" por esos {covered}"
    if plan["regular_saving"] >= 0.5:
        total_line += f" · ahorras{NB}~${plan['regular_saving']:.2f} vs precio regular"

    if base["is_thursday"]:
        subject = f"Mi Lista: {n_deals} de {n} en oferta · {stores_label}"
        eyebrow = "Shoppers nuevos de esta semana"
    else:
        subject = f"Mi Lista: {n_deals} ofertas siguen activas · {stores_label}"
        eyebrow = "Lo que queda de la semana"
    n_ending = sum(r["ends_soon"] for s in stores for r in s["rows"]) + sum(r["ends_soon"] for r in elsewhere)

    summary = {str(r["item_id"]): [r["chain"], r["price"]]
               for r in [r for s in stores for r in s["rows"]] + elsewhere}
    return {**base, "send": True, "reason": "ok", "n_deals": n_deals,
            "subject": subject, "eyebrow": eyebrow, "headline": headline,
            "total": plan["total"], "regular_saving": plan["regular_saving"],
            "total_line": total_line, "stores": stores, "elsewhere": elsewhere,
            "unavailable": unavailable, "n_ending": n_ending,
            "preheader": f"{headline}. {total_line}.".replace(NB, " "), "summary": summary}


def render_digest(d: dict, *, unsubscribe_url: str, site_url: str,
                  feedback_url: str = "", postal_address: str = "",
                  can_reply: bool = False) -> tuple[str, str]:
    """-> (html, text)."""
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    env = Environment(loader=FileSystemLoader(TEMPLATES), undefined=StrictUndefined,
                      autoescape=lambda name: bool(name) and name.endswith(".html.j2"),
                      trim_blocks=True, lstrip_blocks=True)
    ctx = {**d, "mono": MONO, "unsubscribe_url": unsubscribe_url, "site_url": site_url,
           "feedback_url": feedback_url, "postal_address": postal_address,
           "can_reply": can_reply}
    return (env.get_template("digest.html.j2").render(**ctx),
            env.get_template("digest.txt.j2").render(**ctx))
