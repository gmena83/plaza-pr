"""Per-source validity-date detection.

Each chain prints its shopper's validity range differently:
  pueblo   page text: "Válido del 7 al 13 de Octubre 2026"
  amigo    page text: "Válido del 8 al 14 de Octubre 2026"
  supermax page text: "Válido del 07-Oct-2026 al 13-Oct-2026"
  selectos no text layer -> read from PDF page 1 via the VL model
Falls back to today..+6d when nothing parses.
"""
import base64
import json
import logging
import re
from datetime import date, timedelta

from .common import get, session

log = logging.getLogger("pr-shopper.validity")

MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
          "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
          "noviembre": 11, "diciembre": 12}
MON_ABBR = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
            "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _iso(y, m, d) -> str:
    return date(int(y), int(m), int(d)).isoformat()


def _fallback() -> tuple[str, str]:
    t = date.today()
    return t.isoformat(), (t + timedelta(days=6)).isoformat()


def _spanish_range(text: str):
    """'Válido del 7 al 13 de Octubre 2026' (month may appear once, at the end)."""
    t = re.sub(r"\s+", " ", text)
    m = re.search(
        r"[Vv][aá]lido?\s+del\s+(\d{1,2})\s+(?:de\s+(\w+)\s+)?al\s+(\d{1,2})\s+de\s+(\w+)(?:\s+(\d{4}))?",
        t)
    if not m:
        return None
    d1, mon1, d2, mon2, year = m.groups()
    mon2n = MONTHS.get(mon2.lower())
    mon1n = MONTHS.get(mon1.lower()) if mon1 else mon2n
    year = year or date.today().year
    if not (mon1n and mon2n):
        return None
    return _iso(year, mon1n, d1), _iso(year, mon2n, d2)


def _abbr_range(text: str):
    """'07-Oct-2026 al 13-Oct-2026'"""
    m = re.search(
        r"(\d{1,2})-([A-Za-z]{3})-(\d{4})\s+al\s+(\d{1,2})-([A-Za-z]{3})-(\d{4})", text)
    if not m:
        return None
    d1, mo1, y1, d2, mo2, y2 = m.groups()
    return _iso(y1, MON_ABBR[mo1[:3].lower()], d1), _iso(y2, MON_ABBR[mo2[:3].lower()], d2)


def from_page(chain: dict):
    """Parse validity from the chain's shopper landing page (pueblo/amigo/supermax)."""
    try:
        html = get(chain["shopper_page"], sess=session()).text
    except Exception as e:  # noqa: BLE001
        log.warning("validity page fetch failed: %s", e)
        return None
    return _spanish_range(html) or _abbr_range(html)


def _vl_dates(img_path, cfg: dict):
    """Ask the VL model for the validity dates shown on a single image."""
    from openai import OpenAI
    from .extract_vl import _maybe_downscale
    vl = cfg["vl"]
    client = OpenAI(base_url=vl["serve_url"], api_key="EMPTY")
    img = _maybe_downscale(img_path)
    b64 = base64.b64encode(img.read_bytes()).decode()
    year = date.today().year
    resp = client.chat.completions.create(
        model=vl["model"], temperature=0.0, max_tokens=200,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": (
                "What are the validity dates of this shopper circular? Look for "
                "'Válido del X al Y'. Respond ONLY as JSON: "
                '{"valid_from":"YYYY-MM-DD","valid_to":"YYYY-MM-DD"}. '
                f"Use {year} for the year if only day/month are shown.")},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}])
    txt = resp.choices[0].message.content or ""
    m = re.search(r"\{[^}]*\}", txt, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        vf, vt = d.get("valid_from"), d.get("valid_to")
        if vf and vt:
            return vf, vt
    except json.JSONDecodeError:
        return None
    return None


def from_pdf_vl(pdf_path, chain_slug: str, cfg: dict):
    """Render page 1 of a PDF and read validity dates via the VL model."""
    from .extract_vl import pdf_to_images
    from .common import ROOT
    img_dir = ROOT / "data" / "pages" / f"{chain_slug}_validity"
    imgs = pdf_to_images(pdf_path, int(cfg["vl"].get("dpi", 200)), img_dir)
    if not imgs:
        return None
    return _vl_dates(imgs[0], cfg)


def from_image_vl(image_path, chain_slug: str, cfg: dict):
    """Read validity dates from a single shopper page image via the VL model."""
    return _vl_dates(image_path, cfg)


def detect(chain: dict, chain_slug: str, cfg: dict, pdf_path=None,
           image_path=None) -> tuple[str, str]:
    """Best-effort validity for a chain; falls back to today..+6d."""
    try:
        ctype = chain["type"]
        if ctype == "structured":
            got = from_page(chain)
        elif ctype == "pdf":
            got = from_page(chain)  # supermax prints it on the especiales page
            if not got and pdf_path is not None:
                got = from_pdf_vl(pdf_path, chain_slug, cfg)
        else:  # images / browser / browser_interactive -> VL read of a page image
            got = from_page(chain)
            if not got and image_path is not None:
                got = from_image_vl(image_path, chain_slug, cfg)
        if got:
            log.info("[%s] validity detected: %s -> %s", chain_slug, got[0], got[1])
            return got
    except Exception as e:  # noqa: BLE001
        log.warning("[%s] validity detect failed: %s", chain_slug, e)
    fb = _fallback()
    log.info("[%s] validity fallback: %s -> %s", chain_slug, fb[0], fb[1])
    return fb
