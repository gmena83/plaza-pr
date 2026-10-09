"""Fetch historical shopper page images from the shoppersdepuertorico CDN.

The CDN re-hosts each chain's official weekly circular, dated:
  images: /shopper-{cdn_chain}-{YYYY-MM-DD}-pagina-{NN}.jpg   (NN = 01..pages)
A Referer header is required (HEAD -> 403, GET works).
"""
import logging
from pathlib import Path

import requests

from .common import ROOT, session

log = logging.getLogger("pr-shopper.cdn")

CDN = "https://cdn.shoppersdepuertorico.com"
REFERER = "https://www.shoppersdepuertorico.com/"


def _get(url: str) -> requests.Response:
    s = session()
    s.headers.update({"Referer": REFERER})
    r = s.get(url, timeout=60, stream=True)
    r.raise_for_status()
    return r


def page_exists(cdn_chain: str, week: str, page: int) -> bool:
    url = f"{CDN}/shopper-{cdn_chain}-{week}-pagina-{page:02d}.jpg"
    try:
        r = _get(url)
        r.close()
        return True
    except Exception:
        return False


def week_exists(cdn_chain: str, week: str) -> bool:
    return page_exists(cdn_chain, week, 1)


def count_pages(cdn_chain: str, week: str, max_pages: int = 40) -> int:
    n = 0
    for i in range(1, max_pages + 1):
        if page_exists(cdn_chain, week, i):
            n = i
        else:
            break
    return n


def fetch_week(cdn_chain: str, week: str, out_dir: Path) -> list[Path]:
    """Download all page images for one chain-week. Returns local paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("page-*"):
        try:
            f.unlink()
        except Exception:
            pass
    paths = []
    for i in range(1, 41):
        url = f"{CDN}/shopper-{cdn_chain}-{week}-pagina-{i:02d}.jpg"
        try:
            r = _get(url)
        except Exception:
            break  # no more pages
        p = out_dir / f"page-{i:02d}.jpg"
        p.write_bytes(r.content)
        paths.append(p)
        r.close()
    log.info("[cdn:%s %s] downloaded %d pages", cdn_chain, week, len(paths))
    if not paths:
        raise RuntimeError(f"no pages for {cdn_chain} {week}")
    return paths
