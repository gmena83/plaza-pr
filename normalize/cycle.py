"""Cycle-pattern price analysis for buy-timing recommendations.

Goes beyond the simple historical-low check: detects recurring sale cycles,
trend direction, volatility, and where the current price sits in the product's
typical range, to produce a richer recommendation.

All series are per (chain, product), using best unit_price (fallback sticker)
per week, ordered by week. Needs >=3 points to say anything about a cycle.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field


@dataclass
class ChainPattern:
    chain: str
    n_weeks: int
    current: float
    low: float
    high: float
    mean: float
    basis: str
    on_sale_now: bool          # current <= low * 1.08
    alternating: bool          # detects high/low/high/low cycle
    cycle_weeks: int | None    # 2 if alternating weekly, else None
    trend: str                 # 'down' | 'up' | 'flat'
    position_pct: float        # 0=at low, 100=at high
    predicted_next: str        # 'drop_likely' | 'rise_likely' | 'stable'
    note: str


def _alternates(prices: list[float], tol: float = 0.12) -> bool:
    """True if the series alternates above/below its mean (zigzag), a strong
    sign of an every-other-week promotion cycle."""
    if len(prices) < 4:
        return False
    m = statistics.mean(prices)
    signs = []
    for p in prices:
        if p > m * (1 + tol):
            signs.append(1)
        elif p < m * (1 - tol):
            signs.append(-1)
        else:
            signs.append(0)
    signs = [s for s in signs if s != 0]
    if len(signs) < 3:
        return False
    flips = sum(1 for i in range(1, len(signs)) if signs[i] != signs[i - 1])
    return flips >= len(signs) - 1 - 1  # almost every step flips sign


def _trend(prices: list[float]) -> str:
    if len(prices) < 2:
        return "flat"
    # compare last value to the mean of the earlier values
    prior = prices[:-1]
    if not prior:
        return "flat"
    m = statistics.mean(prior)
    last = prices[-1]
    if last < m * 0.93:
        return "down"
    if last > m * 1.07:
        return "up"
    return "flat"


def analyze_chain(chain: str, points: list[dict]) -> ChainPattern | None:
    """points: [{'week':..., 'price':..., 'unit_price':...}] ordered by week."""
    if len(points) < 2:
        return None
    # Cycle detection uses STICKER price: pack sizes can change week to week
    # (corona 6x12oz vs 12x7oz), which makes unit_price swing even when the
    # actual sale price is flat. A promo cycle always shows in the sticker.
    series = [(p["week"], p["price"]) for p in points]
    series = [(w, v) for w, v in series if v is not None and v > 0]
    if len(series) < 2:
        return None
    basis = points[0].get("price_basis") or ("$/unidad" if points[0].get("unit_price") else "precio")
    weeks = [w for w, _ in series]
    prices = [v for _, v in series]
    low, high, mean = min(prices), max(prices), statistics.mean(prices)
    current = prices[-1]
    n = len(prices)

    # meaningful swing? flat products (corona 9.98 every week) are neither a
    # cycle nor "on sale". Require >=15% swing and >=2 distinct-ish levels.
    swing = (high - low) / mean if mean else 0.0
    has_swing = swing >= 0.15

    on_sale = has_swing and current <= low * 1.08
    alternating = has_swing and _alternates(prices)
    cycle_weeks = 2 if alternating else None
    trend = _trend(prices) if has_swing else "flat"
    position = 0.0 if high == low else (current - low) / (high - low) * 100

    # predict next move
    if alternating:
        # if currently low (sale week), next week likely rises; if high, likely drops
        predicted = "rise_likely" if on_sale else "drop_likely"
    elif trend == "down":
        predicted = "drop_likely"
    elif trend == "up":
        predicted = "rise_likely"
    else:
        predicted = "stable"

    # human note
    if alternating:
        note = (f"Ciclo semanal de ofertas: alterna precio alto/bajo cada semana. "
                + ("Está en semana de OFERTA." if on_sale else "Está en semana de precio alto; suele bajar la próxima semana."))
    elif trend == "down":
        note = "Tendencia a la baja en las últimas semanas."
    elif trend == "up":
        note = "Tendencia al alza; el precio viene subiendo."
    else:
        note = "Precio estable; no muestra ciclo claro."
    if on_sale and not alternating:
        note += " Ahora mismo está en su precio más bajo."

    return ChainPattern(
        chain=chain, n_weeks=n, current=current, low=low, high=high, mean=mean,
        basis=basis, on_sale_now=on_sale, alternating=alternating,
        cycle_weeks=cycle_weeks, trend=trend, position_pct=round(position, 1),
        predicted_next=predicted, note=note)


def recommend(product_points: list[dict]) -> dict:
    """product_points: rows across all chains+weeks for one product.
    Returns per-chain patterns + an overall verdict."""
    from collections import defaultdict
    by_chain = defaultdict(list)
    for p in product_points:
        by_chain[p["chain_slug"]].append(p)
    patterns = []
    for chain, pts in by_chain.items():
        pts = sorted(pts, key=lambda x: x["week"])
        pat = analyze_chain(chain, pts)
        if pat:
            patterns.append(pat)
    if not patterns:
        return {"verdict": None, "chains": []}

    # overall verdict: cheapest chain that's on sale now, else cheapest chain with drop_likely
    def cur(p):
        return p.current
    on_sale = [p for p in patterns if p.on_sale_now]
    drop_soon = [p for p in patterns if p.predicted_next == "drop_likely" and not p.on_sale_now]

    if on_sale:
        best = min(on_sale, key=cur)
        saving = round((best.mean - best.current) / best.mean * 100) if best.mean else 0
        verdict = {
            "action": "buy_now",
            "chain": best.chain,
            "value": round(best.current, 2),
            "basis": best.basis,
            "saving_pct": saving,
            "message": (f"COMPRAR AHORA en {best.chain}: está en oferta a "
                        f"{round(best.current,2)} {best.basis} ({saving}% bajo su promedio) "
                        + ("— semana baja de su ciclo semanal." if best.alternating else "— su precio más bajo reciente.")),
        }
    elif drop_soon:
        best = min(drop_soon, key=cur)
        # when: if alternating weekly, the drop is next week
        when = "la próxima semana" if best.alternating else "pronto"
        verdict = {
            "action": "wait",
            "chain": best.chain,
            "value": round(best.low, 2),
            "basis": best.basis,
            "when": when,
            "message": (f"ESPERAR: {best.chain} suele bajar a ~{round(best.low,2)} {best.basis} "
                        f"{when}. Ahora está en {round(best.current,2)} (parte alta del ciclo)."
                        if best.alternating else
                        f"ESPERAR: {best.chain} muestra tendencia a la baja; históricamente llega a ~{round(best.low,2)} {best.basis}."),
        }
    else:
        cheapest = min(patterns, key=cur)
        # if the cheapest option is on a rising trend, urge buying before it climbs more
        if cheapest.trend == "up" and cheapest.position_pct > 40:
            verdict = {
                "action": "buy_soon",
                "chain": cheapest.chain,
                "value": round(cheapest.current, 2),
                "basis": cheapest.basis,
                "message": (f"COMPRAR PRONTO en {cheapest.chain}: el precio viene SUBIENDO "
                            f"({round(cheapest.low,2)} → {round(cheapest.current,2)} {cheapest.basis}). "
                            f"Mejor ahora antes de que siga subiendo."),
            }
            return {"verdict": verdict,
                    "chains": [vars(p) for p in sorted(patterns, key=cur)]}
        verdict = {
            "action": "buy_cheapest",
            "chain": cheapest.chain,
            "value": round(cheapest.current, 2),
            "basis": cheapest.basis,
            "message": (f"Sin ciclo de ofertas claro. El más barato ahora es "
                        f"{cheapest.chain} a {round(cheapest.current,2)} {cheapest.basis}."),
        }
    return {"verdict": verdict,
            "chains": [vars(p) for p in sorted(patterns, key=cur)]}
