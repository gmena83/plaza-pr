"""Shared HTTP + config helpers."""
import re
import time
import logging
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

log = logging.getLogger("pr-shopper")


def load_config(path: str | None = None) -> dict:
    p = Path(path) if path else ROOT / "config" / "chains.yaml"
    with open(p) as f:
        return yaml.safe_load(f)


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "es-PR,es;q=0.9,en;q=0.8"})
    return s


def get(url: str, sess: requests.Session | None = None, retries: int = 3,
        timeout: int = 60, **kw) -> requests.Response:
    s = sess or session()
    last = None
    for attempt in range(retries):
        try:
            r = s.get(url, timeout=timeout, **kw)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001
            last = e
            wait = 2 ** attempt
            log.warning("GET %s failed (%s); retry %d in %ds", url, e, attempt + 1, wait)
            time.sleep(wait)
    raise last


def parse_price(text: str) -> float | None:
    """'2/$5.00' -> 2.50 ; '$1.99' -> 1.99 ; '1.99' -> 1.99"""
    if not text:
        return None
    t = text.strip().replace("$", "").replace(",", "")
    m = re.search(r"(\d+)\s*/\s*(\d+(?:\.\d+)?)", t)          # 2/5.00
    if m:
        qty, total = float(m.group(1)), float(m.group(2))
        return round(total / qty, 4) if qty else None
    m = re.search(r"(\d+\.\d{2})", t)
    if m:
        return float(m.group(1))
    m = re.search(r"\b(\d+)\b", t)
    return float(m.group(1)) if m else None


def parse_size_unit(text: str) -> tuple[str | None, str | None]:
    """Return (size_text, unit_basis) from strings like '12 oz', '1 lb', 'caja 24 un'."""
    if not text:
        return None, None
    t = text.lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(oz|lb|lbs|un|unid|ct|pk|l|lt|litro|ml|kg|g)\b", t)
    if not m:
        return None, None
    val, unit = m.group(1), m.group(2)
    basis = {"lbs": "lb", "unid": "un", "ct": "un", "pk": "un",
             "lt": "l", "litro": "l", "g": "g", "kg": "kg", "ml": "ml"}.get(unit, unit)
    return f"{val} {unit}", basis
