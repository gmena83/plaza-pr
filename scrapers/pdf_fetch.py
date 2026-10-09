"""Discover and download weekly PDF circulars (Selectos, SuperMax, Econo)."""
import logging
import re
from pathlib import Path

from .common import ROOT, get, session

log = logging.getLogger("pr-shopper.pdf")


def _resolve_pdf_url(chain: dict, sess) -> str:
    """Return a working PDF URL: try configured pdf_url, else scrape shopper_page for a link."""
    if chain.get("pdf_url"):
        try:
            r = sess.head(chain["pdf_url"], timeout=30, allow_redirects=True)
            if r.status_code == 200 and "pdf" in r.headers.get("content-type", ""):
                return chain["pdf_url"]
        except Exception as e:
            log.warning("head pdf_url failed: %s", e)
    page = get(chain["shopper_page"], sess=sess).text
    rx = chain.get("pdf_link_regex", r"[^\"']+\.pdf")
    candidates = re.findall(rx, page)
    if not candidates:
        # generic fallback
        candidates = re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)', page)
    if not candidates:
        raise RuntimeError(f"no pdf link found on {chain['shopper_page']}")
    url = candidates[0]
    if not url.startswith(("http://", "https://")):
        from urllib.parse import urljoin, urlparse
        parsed = urlparse(chain["shopper_page"])
        root = f"{parsed.scheme}://{parsed.netloc}/"
        url = urljoin(root, url.lstrip("/"))
    return url


def fetch_pdf(chain: dict, chain_slug: str, data_dir: str = "data/pdfs") -> Path:
    sess = session()
    url = _resolve_pdf_url(chain, sess)
    log.info("%s pdf url: %s", chain_slug, url)
    r = get(url, sess=sess, timeout=120)
    out_dir = ROOT / data_dir / chain_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "current.pdf"
    out.write_bytes(r.content)
    log.info("saved %s (%d bytes)", out, len(r.content))
    return out
