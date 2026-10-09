"""Scraper for chains that publish the shopper as a set of page images
embedded in a (Wix/WordPress) page, rather than a single PDF.
Fetches the highest-resolution variant of each page image and hands the
local files to the VL extractor.
"""
import logging
import re
from pathlib import Path

from .common import ROOT, get, session

log = logging.getLogger("pr-shopper.images")

# Wix serves many variants; the full-res original is the URL before the /v1/ transform.
WIX_RX = re.compile(
    r'(https://static\.wixstatic\.com/media/[0-9a-f_]+~mv2\.(?:jpg|jpeg|png))',
    re.I)


def _fullres(url: str) -> str:
    """Strip the /v1/... transform to get the original-resolution image."""
    return url.split("/v1/")[0]


def fetch_images(chain: dict, chain_slug: str, data_dir: str = "data/pages") -> list[Path]:
    sess = session()
    html = get(chain["shopper_page"], sess=sess).text
    urls = WIX_RX.findall(html)
    # de-dup, keep order, full-res
    seen, ordered = set(), []
    for u in urls:
        fu = _fullres(u)
        if fu not in seen:
            seen.add(fu)
            ordered.append(fu)
    if not ordered:
        raise RuntimeError(f"no shopper images found on {chain['shopper_page']}")
    log.info("[%s] found %d distinct shopper page images", chain_slug, len(ordered))

    out_dir = ROOT / data_dir / f"{chain_slug}_img"
    out_dir.mkdir(parents=True, exist_ok=True)
    # clear old
    for f in out_dir.glob("page-*.jpg"):
        f.unlink()
    paths = []
    for i, u in enumerate(ordered, start=1):
        ext = ".jpg"
        p = out_dir / f"page-{i:02d}{ext}"
        r = get(u, sess=sess, timeout=60)
        p.write_bytes(r.content)
        paths.append(p)
    return paths
