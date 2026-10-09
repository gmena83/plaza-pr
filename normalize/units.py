"""Size parsing + unit-price computation.

Turns messy chain-specific size strings into a canonical (quantity, unit,
canonical_size) and a comparable unit_price (price per base unit).

Canonical base units:
  weight:  'g'   (oz, lb, lbs, libras -> g)
  volume:  'ml'  (l, lt, litro, oz(fl), ml -> ml)
  count:   'un'  (un, unidad, ct, pk, paquete, rollos, latas -> un)

For weight+volume we use a per-unit price (price / qty_in_base_unit). For
multi-pack "12 Latas de 10 oz" we compute total content (120 oz) when possible.
Range sizes "6-8 oz" use the midpoint. Non-parseable / count-only items keep
unit_price = price_sale (comparing per-item is the best we can do).
"""
import re

# conversion to base units
OZ_TO_G = 28.3495
LB_TO_G = 453.592
L_TO_ML = 1000.0

_NUM = r"(\d+(?:[.,]\d+)?)"

# ordered: most specific first
WEIGHT_UNITS = {
    "lb": LB_TO_G, "lbs": LB_TO_G, "libra": LB_TO_G, "libras": LB_TO_G,
    "lb.": LB_TO_G, "lbs.": LB_TO_G,
    "oz": OZ_TO_G, "oz.": OZ_TO_G, "onza": OZ_TO_G, "onzas": OZ_TO_G,
    "kg": 1000.0, "g": 1.0,
}
VOLUME_UNITS = {
    "l": L_TO_ML, "lt": L_TO_ML, "lts": L_TO_ML, "litro": L_TO_ML,
    "litros": L_TO_ML, "ltr": L_TO_ML,
    "ml": 1.0, "cc": 1.0,
    "qt": 946.353, "gal": 3785.41,
}
COUNT_WORDS = {"un", "unid", "unidad", "unidades", "ct", "pk", "pqte", "pqt",
               "paquete", "rollos", "rollo", "latas", "lata", "env", "sobres",
               "pz", "pza", "piezas", "capsulas", "tabletas", "ea", "caja"}


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def _norm_text(t: str) -> str:
    t = (t or "").lower()
    t = t.replace("pqte.", "pqte").replace("pte.", "pqte").replace("pzte", "pqte")
    return t


def parse_size(size_text: str):
    """Return dict(quantity, unit, base_qty, base_unit, canonical) or None.

    base_qty is total content in base_unit (g / ml / un) for the whole package.
    """
    if not size_text:
        return None
    t = _norm_text(size_text)

    # price-per-unit strings leaking into size (econo): "95¢ lb", "$1.75 lb.",
    # "2/$5.00" -> the basis is a single unit (lb / each). price parsing owns
    # the number; here we just capture the unit so unit_price = price / 1 unit.
    if re.search(r"(lb|lbs)\b", t) and re.search(r"[¢$]|/\s*\$", t):
        return {"quantity": 1.0, "unit": "lb", "base_qty": LB_TO_G,
                "base_unit": "g", "canonical": "1lb"}
    if re.search(r"(p\.?q\.?t\.?e|pqte|paquete|c/u|each)\b", t) and re.search(r"[¢$]|/", t):
        return {"quantity": 1.0, "unit": "un", "base_qty": 1.0,
                "base_unit": "un", "canonical": "1un"}

    # strip price/promo noise that sometimes leaks into size (econo)
    t = re.sub(r"\$?\d+(?:[.,]\d+)?\s*[/¢]\s*", " ", t)
    t = re.sub(r"\d+\s*/\s*\$?\d+", " ", t)  # 2/$5

    # multi-pack: "12 latas de 10 oz", "12pk/10oz", "6 rollos"
    m = re.search(_NUM + r"\s*(?:pk|pqte|latas?|rollos?|un(?:idad)?|ct|bot|botellas?)"
                  r"\s*(?:de|x|/)?\s*" + _NUM + r"\s*(oz|ml|l|lt|lb|g)\b", t)
    if m:
        count, qty, unit = _f(m.group(1)), _f(m.group(2)), m.group(3)
        conv = WEIGHT_UNITS.get(unit) or VOLUME_UNITS.get(unit)
        base_unit = "g" if unit in WEIGHT_UNITS else "ml"
        if conv:
            total = count * qty * conv
            return {"quantity": count * qty, "unit": unit, "base_qty": total,
                    "base_unit": base_unit,
                    "canonical": f"{count}x{qty:g}{unit}"}

    # range: "6-8 oz", "7 a 8 oz"
    m = re.search(_NUM + r"\s*(?:-|a)\s*" + _NUM + r"\s*(oz|lb|lbs|l|ml|g)\b", t)
    if m:
        lo, hi, unit = _f(m.group(1)), _f(m.group(2)), m.group(3)
        qty = (lo + hi) / 2
        conv = WEIGHT_UNITS.get(unit) or VOLUME_UNITS.get(unit)
        base_unit = "g" if unit in WEIGHT_UNITS else ("ml" if unit in VOLUME_UNITS else None)
        if conv and base_unit:
            return {"quantity": qty, "unit": unit, "base_qty": qty * conv,
                    "base_unit": base_unit, "canonical": f"{qty:g}{unit}"}

    # simple: "15.5 oz", "1 lb", "3 libras", "1.75 litro"
    m = re.search(_NUM + r"\s*(oz\.?|lbs?\.?|libras?|kg|g|ml|l|lt|lts|litros?|qt|gal)\b", t)
    if m:
        qty, unit = _f(m.group(1)), m.group(2).rstrip(".")
        if unit in WEIGHT_UNITS:
            return {"quantity": qty, "unit": unit, "base_qty": qty * WEIGHT_UNITS[unit],
                    "base_unit": "g", "canonical": f"{qty:g}{unit}"}
        if unit in VOLUME_UNITS:
            return {"quantity": qty, "unit": unit, "base_qty": qty * VOLUME_UNITS[unit],
                    "base_unit": "ml", "canonical": f"{qty:g}{unit}"}

    # count-only: "12 unidad", "6 rollos", "caja"
    m = re.search(_NUM + r"\s*(un(?:idad(?:es)?)?|ct|rollos?|latas?|piezas?|capsulas|tabletas)\b", t)
    if m:
        qty = _f(m.group(1))
        return {"quantity": qty, "unit": "un", "base_qty": qty,
                "base_unit": "un", "canonical": f"{qty:g}un"}
    # bare unit word (econo 'CAJA', 'P.Q.T.E.') -> single unit
    if re.search(r"\b(caja|pqte|paquete|env|un)\b", t):
        return {"quantity": 1.0, "unit": "un", "base_qty": 1.0,
                "base_unit": "un", "canonical": "1un"}
    return None


def unit_price(price_sale: float, parsed: dict | None) -> tuple[float | None, str | None]:
    """Return (unit_price, price_basis label like '$/lb' or '$/100ml')."""
    if not price_sale or not parsed:
        return None, None
    bq, bu = parsed.get("base_qty"), parsed.get("base_unit")
    if not bq or not bu:
        return None, None
    if bu == "g":
        # report per lb (454g) for readability
        return round(price_sale / bq * LB_TO_G, 4), "$/lb"
    if bu == "ml":
        return round(price_sale / bq * 100.0, 4), "$/100ml"
    if bu == "un":
        return round(price_sale / bq, 4), "$/un"
    return None, None
