"""Constrained PLAZA assistant. Never use projection or unverified catalog data."""

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo


def _today() -> str:
    return datetime.now(ZoneInfo("America/Puerto_Rico")).date().isoformat()


def _fold(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(ch))


def _current_offers(c, terms: tuple[str, ...]) -> list[dict]:
    where = " OR ".join("LOWER(o.product_norm) LIKE ?" for _ in terms)
    rows = c.execute(
        "SELECT o.product_raw, o.product_norm, o.chain_slug, c.name chain_name, "
        "o.size_text, o.size_canonical, o.price_sale, o.valid_from, o.valid_to, "
        "o.source_url, o.sku, o.category, o.unit_price, o.price_basis "
        "FROM offers o JOIN chains c ON c.slug=o.chain_slug "
        "WHERE date(?) BETWEEN date(o.valid_from) AND date(o.valid_to) "
        "AND o.price_sale > 0 AND (" + where + ") ORDER BY o.price_sale LIMIT 400",
        (_today(), *(f"%{term}%" for term in terms))).fetchall()
    return [dict(row) for row in rows]


def _shown(row: dict) -> dict:
    return {"chain": row["chain_name"], "product": row["product_raw"],
            "product_norm": row["product_norm"], "size": row["size_text"],
            "size_canonical": row["size_canonical"], "price": row["price_sale"],
            "unit_price": row["unit_price"], "price_basis": row["price_basis"],
            "valid_from": row["valid_from"], "valid_to": row["valid_to"],
            "source_url": row["source_url"] if str(row["source_url"]).startswith("https://") else None}


def _meat_offers(c) -> list[dict]:
    terms = ("carne", "cerdo", "pollo", "res", "pechuga", "muslo", "costilla", "lomo",
             "bistec", "churrasco", "pavo", "pernil", "beef", "pork", "chicken")
    where = " OR ".join("LOWER(o.product_norm) LIKE ?" for _ in terms)
    rows = c.execute(
        "SELECT o.product_raw, o.product_norm, o.chain_slug, c.name chain_name, "
        "o.size_text, o.size_canonical, o.price_sale, o.valid_from, o.valid_to, "
        "o.source_url, o.sku, o.category, o.unit_price, o.price_basis "
        "FROM offers o JOIN chains c ON c.slug=o.chain_slug "
        "WHERE date(?) BETWEEN date(o.valid_from) AND date(o.valid_to) "
        "AND o.price_sale > 0 AND (" + where + ") "
        "ORDER BY o.price_sale LIMIT 800",
        (_today(), *(f"%{term}%" for term in terms))).fetchall()
    good = []
    for row in rows:
        r = dict(row)
        name = _fold(r["product_raw"])
        size = _fold(r["size_text"] or "").strip().rstrip(".")
        # OCR often treats an advertised $/lb as a 23-lb package and divides
        # the price again; only explicit one-pound/per-pound labels are safe.
        if not re.fullmatch(r"(?:1(?:\.0+)?\s*)?(?:lb|lbs|libra|libras)", size):
            continue
        if not re.search(r"\b(carne|cerdo|pollo|res|pechugas?|muslos?|costillas?|lomo|"
                         r"bistec|churrasco|pavo|pernil|beef|pork|chicken)\b", name):
            continue
        if re.search(r"\b(cubitos?|caldo|sopa|condimento|sazon|salchichas?|jamon|"
                     r"embutido|chicharrones?|enlatad[oa]s?)\b", name):
            continue
        r["unit_price"] = r["price_sale"]
        r["price_basis"] = "$/lb"
        good.append(r)
    return good


def _oat_offers(c) -> list[dict]:
    return [r for r in _current_offers(c, ("avena", "oat"))
            if ("avena" in _fold(r["product_raw"]) or "oat" in _fold(r["product_raw"]))
            and re.search(r"\b(leche|milk|oatmilk)\b", _fold(r["product_raw"]))
            and not re.search(r"\b(gel|ducha|shower|jabon|soap|pudding|skin)\b",
                              _fold(r["product_raw"]))]


def _proposal(c, user_id: str, text: str) -> dict | None:
    add = re.match(r"^(?:agrega|anade|anadi|pon|add)\s+(.+?)\s+(?:a|en|to)\s+(?:mi|my)\s+(?:lista|list)[.!?]*$", text)
    if add:
        term = add.group(1).strip()
        rows = (_oat_offers(c) if term in ("leche de avena", "leche avena", "oat milk")
                else _current_offers(c, (term,)) if re.fullmatch(r"[a-z0-9 ]{2,60}", term) else [])
        seen, actions = set(), []
        for r in rows:
            key = (r["product_norm"], r["size_canonical"] or r["size_text"] or "")
            if key in seen:
                continue
            seen.add(key)
            actions.append({"label": f"Añadir {r['product_raw']} · {key[1] or 'sin tamaño'}",
                            "method": "POST", "path": "/api/list/items",
                            "params": {"product_norm": key[0], "display_name": r["product_raw"],
                                       "size": key[1]}, "requires_confirmation": True})
            if len(actions) >= 4:
                break
        if not actions:
            return {"kind": "no_data", "answer": "No encontré ese producto entre las ofertas vigentes. "
                    "Puedes buscarlo o añadirlo manualmente desde Mi Lista.", "offers": [], "actions": []}
        return {"kind": "list_proposal", "answer": "Elige el producto exacto. "
                "No cambiaré Mi Lista hasta que confirmes.", "offers": [], "actions": actions}

    remove = re.match(r"^(?:quita|elimina|borra|remove|delete)\s+(.+?)\s+"
                      r"(?:de|from)\s+(?:mi|my)\s+(?:lista|list)[.!?]*$", text)
    edit_price = re.match(r"^(?:cambia|edita|pon|set|change)\s+(?:el\s+)?precio\s+"
                          r"(?:meta|objetivo|limite|tope|target)\s+de\s+(.+?)\s+"
                          r"(?:a|en|to)\s*\$?(\d+(?:[.,]\d{1,2})?)[.!?]*$", text)
    any_size = re.match(r"^(?:compara\s+)?(cualquier|solo este)\s+tamano\s+(?:para|de)\s+(.+)$", text)
    if not (remove or edit_price or any_size):
        return None
    term = (remove.group(1) if remove else edit_price.group(1) if edit_price else any_size.group(2)).strip()
    items = c.execute(
        "SELECT i.id, i.product_norm, i.display_name, i.size_canonical FROM list_items i "
        "JOIN lists l ON l.id=i.list_id WHERE l.user_id=? ORDER BY i.id", (user_id,)).fetchall()
    matches = [dict(r) for r in items if term in _fold(r["display_name"] or r["product_norm"])]
    if not matches:
        return {"kind": "no_data", "answer": "No encontré ese producto en tu Mi Lista.",
                "offers": [], "actions": []}
    value = None
    if edit_price:
        value = float(edit_price.group(2).replace(",", "."))
        if not 0 < value <= 10000:
            return {"kind": "help", "answer": "Indica un precio meta mayor que $0 y menor que $10,000.",
                    "offers": [], "actions": []}
    actions = []
    for r in matches[:5]:
        label = r["display_name"] or r["product_norm"]
        if remove:
            method, params, caption = "DELETE", {}, f"Quitar {label}"
        elif edit_price:
            method, params, caption = "PATCH", {"target_price": value}, f"Precio meta de {label}: ${value:.2f}"
        else:
            flag = any_size.group(1) == "cualquier"
            method, params, caption = "PATCH", {"any_size": flag}, f"{label}: {'cualquier tamaño' if flag else 'este tamaño'}"
        actions.append({"label": caption, "method": method,
                        "path": f"/api/list/items/{r['id']}", "params": params,
                        "requires_confirmation": True})
    return {"kind": "list_proposal", "answer": "Confirma el producto exacto antes de cambiar Mi Lista.",
            "offers": [], "actions": actions}


def _price_reply(rows: list[dict], subject: str) -> dict:
    if not rows:
        return {"kind": "no_data", "answer": f"No encontré ofertas actuales comparables de {subject}. "
                "PLAZA no cubre todo el inventario; no puedo afirmar qué tienda es más barata.",
                "offers": [], "actions": []}
    size = rows[0]["size_canonical"] or rows[0]["size_text"] or "sin tamaño"
    same_size = [r for r in rows if (r["size_canonical"] or r["size_text"] or "sin tamaño") == size]
    offers = [_shown(r) for r in same_size[:4]]
    first = offers[0]
    return {"kind": "price", "answer":
            f"Entre las ofertas de {subject} de {size} registradas por PLAZA, {first['chain']} muestra "
            f"${first['price']:.2f} para {first['product']}. Vigente hasta {first['valid_to']}. "
            "Solo compara ofertas publicadas del mismo tamaño, no todo el inventario "
            "ni la disponibilidad en tienda.", "offers": offers, "actions": []}


def answer(c, user_id: str, message: str) -> dict:
    text = _fold(message).strip()
    proposed = _proposal(c, user_id, text)
    if proposed is not None:
        return proposed
    if ("especial" in text or "oferta" in text or "special" in text) and (
            "supermercado" in text or "tienda" in text or "store" in text):
        rows = c.execute(
            "SELECT c.name chain, COUNT(DISTINCT o.product_norm || '|' || "
            "COALESCE(o.size_canonical, '')) n FROM offers o "
            "JOIN chains c ON c.slug=o.chain_slug "
            "WHERE date(?) BETWEEN date(o.valid_from) AND date(o.valid_to) AND o.price_sale > 0 "
            "GROUP BY c.name ORDER BY n DESC, c.name", (_today(),)).fetchall()
        counts = [{"chain": r["chain"], "count": r["n"]} for r in rows]
        if not counts:
            return {"kind": "no_data", "answer": "No tengo ofertas vigentes registradas hoy.",
                    "counts": [], "offers": [], "actions": []}
        top = counts[0]
        return {"kind": "specials", "answer":
                f"De los shoppers que PLAZA registra hoy ({_today()}), {top['chain']} tiene "
                f"{top['count']} productos/tamaños distintos en oferta. "
                "No es un recuento completo de todos los especiales de cada supermercado.",
                "counts": counts, "offers": [], "actions": []}
    if ("carne" in text or "meat" in text) and ("barat" in text or "cheap" in text):
        rows = _meat_offers(c)
        if not rows:
            return {"kind": "no_data", "answer": "No tengo precios por libra comparables de carne "
                    "entre las ofertas vigentes. No puedo señalar una tienda más barata.",
                    "offers": [], "actions": []}
        offers = [_shown(row) for row in rows[:4]]
        first = offers[0]
        return {"kind": "meat", "answer":
                f"Entre las carnes frescas anunciadas por libra que PLAZA registra hoy, "
                f"{first['chain']} muestra {first['product']} a ${first['unit_price']:.2f} por libra "
                f"(hasta {first['valid_to']}). Son cortes y tipos distintos; no representa el precio "
                "de toda la carne ni confirma disponibilidad en tienda.",
                "offers": offers, "actions": []}
    if "oat milk" in text or "leche de avena" in text or "leche avena" in text:
        return _price_reply(_oat_offers(c), "leche de avena")
    sought = re.search(r"\b(?:compro|comprar|buy)\s+(.+?)(?:\s+mas\s+barat\w*|\s+cheapest|\s+cheap|[?!.]|$)", text)
    if sought:
        term = sought.group(1).strip()
        if re.fullmatch(r"[a-z0-9 ]{2,60}", term):
            return _price_reply(_current_offers(c, (term,)), term)
    return {"kind": "help", "answer": "Puedo buscar ofertas y ayudarte con Mi Lista.",
            "offers": [], "actions": []}
