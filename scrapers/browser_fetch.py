"""Playwright-based scraper for JS-heavy chains.

Renders a shopper page in headless Chromium, scrolls to trigger lazy loading,
collects shopper page images (img src, srcset, CSS background-image, and image
URLs present anywhere in the rendered DOM), downloads them, and returns local
paths for the VL extractor.

Use for chains whose circular is behind a JS app: Econo (ideal.sale),
Walmart PR, Freshmart, and Facebook-published shoppers (Agranel).
"""
import logging
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from .common import ROOT, get, session

log = logging.getLogger("pr-shopper.browser")

CHROME = "/home/gonzalo-mena/.hermes/tools/chromium-1208/chrome-linux64/chrome"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

IMG_RX = re.compile(r"https?://[^\s\"'()<>]+\.(?:jpg|jpeg|png|webp)", re.I)
RELEVANT_RX = re.compile(
    r"shopper|page|flyer|circular|oferta|especial|media|cloudfront|scontent|"
    r"ideal|leaflet|tile|upload|fbcdn|image", re.I)
SKIP_RX = re.compile(
    r"logo|icon|sprite|avatar|emoji|favicon|placeholder|profile|"
    r"banner[-_]?ad|tracking|pixel|badge", re.I)

_BG_JS = (
    "() => { const s=[]; document.querySelectorAll('*').forEach(e=>{"
    " const b=getComputedStyle(e).backgroundImage;"
    " const m=b.match(/url\\([\"']?([^\"')]+)/); if(m) s.push(m[1]); });"
    " return s; }"
)


def _collect_image_urls(page) -> list:
    urls = set()
    for attr in ("currentSrc", "src"):
        try:
            vals = page.eval_on_selector_all(
                "img", "els=>els.map(e=>e." + attr + ").filter(Boolean)")
            urls.update(vals)
        except Exception:
            pass
    try:
        srcsets = page.eval_on_selector_all(
            "img[srcset]", "els=>els.map(e=>e.srcset).filter(Boolean)")
        for ss in srcsets:
            for part in ss.split(","):
                urls.add(part.strip().split(" ")[0])
    except Exception:
        pass
    try:
        urls.update(page.evaluate(_BG_JS))
    except Exception:
        pass
    for m in IMG_RX.findall(page.content()):
        urls.add(m)
    out = []
    for u in urls:
        if not u.startswith("http"):
            continue
        if SKIP_RX.search(u):
            continue
        if RELEVANT_RX.search(u):
            out.append(u)
    seen, res = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            res.append(u)
    return res


def fetch_shopper_images(chain: dict, chain_slug: str,
                         wait_s: int | None = None,
                         scrolls: int = 8) -> list:
    url = chain["shopper_page"]
    wait_s = wait_s if wait_s is not None else int(chain.get("render_wait_s", 8))
    out_dir = ROOT / "data" / "pages" / (chain_slug + "_browser")
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME, headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1400, "height": 2200})
        page = ctx.new_page()
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(wait_s * 1000)
        for _ in range(scrolls):
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(400)
        urls = _collect_image_urls(page)
        browser.close()

    log.info("[%s] browser found %d candidate images", chain_slug, len(urls))
    if not urls:
        raise RuntimeError("no shopper images discovered on " + url)

    sess = session()
    for f in out_dir.glob("page-*"):
        try:
            f.unlink()
        except Exception:
            pass
    paths = []
    for i, u in enumerate(urls, start=1):
        try:
            r = get(u, sess=sess, timeout=60)
        except Exception as e:  # noqa: BLE001
            log.warning("download failed %s: %s", u[:80], e)
            continue
        ul = u.lower()
        ext = ".jpg"
        if ".png" in ul:
            ext = ".png"
        elif ".webp" in ul:
            ext = ".webp"
        pth = out_dir / ("page-%02d%s" % (i, ext))
        pth.write_bytes(r.content)
        paths.append(pth)
    log.info("[%s] downloaded %d images", chain_slug, len(paths))
    return paths
