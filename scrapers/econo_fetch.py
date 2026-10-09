"""Econo interactive scraper.

Econo's circular is a store-gated Firestore app (ideal.sale). Flow:
  1. open /shopper (store locator), click "Make My Store"
  2. the circular renders a product grid + a category nav
     (.navigation-panel-item-label)
  3. screenshot the home grid, then click each category and screenshot
  4. screenshots go to the VL extractor

Reference `browser_interactive` implementation.
"""
import logging
from pathlib import Path

from playwright.sync_api import sync_playwright

from .common import ROOT

log = logging.getLogger("pr-shopper.econo")

CHROME = "/home/gonzalo-mena/.hermes/tools/chromium-1208/chrome-linux64/chrome"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

CATEGORIES = [
    "Alivia Tu Bolsillo",
    "Frutas y Vegetales",
    "Deli Meat",
    "Carnes y Mariscos",
    "Lácteos y Congelados",
    "Prepárate para la Temporada",
    "Provisiones",
    "Bebidas y Entremeses",
    "Promociones Especiales",
    "Higiene y Hogar",
]
LABEL_SEL = ".navigation-panel-item-label"


def _click_category(page, name: str) -> bool:
    """Click a category nav label by exact text; returns True on success."""
    try:
        loc = page.locator(LABEL_SEL, has_text=name).first
        # The nav is an Angular app; labels are present in the DOM but often
        # fail Playwright's actionability (visibility) checks. A direct JS
        # click triggers the router reliably (verified against the live site).
        loc.evaluate("el => el.click()")
        page.wait_for_timeout(3500)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("category %r click failed: %s", name, str(e)[:100])
        return False


def fetch_shopper_images(chain: dict, chain_slug: str, scrolls: int = 3) -> list:
    url = chain["shopper_page"]
    out_dir = ROOT / "data" / "pages" / (chain_slug + "_browser")
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("page-*"):
        try:
            f.unlink()
        except Exception:
            pass

    shots: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME, headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1400, "height": 2400})
        page = ctx.new_page()
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)

        try:
            page.click("text=Make My Store", timeout=10000)
            page.wait_for_timeout(6000)
        except Exception as e:  # noqa: BLE001
            log.warning("store select failed (maybe pre-selected): %s", e)

        idx = 1

        def shoot(tag: str):
            nonlocal idx
            pth = out_dir / ("page-%02d.png" % idx)
            page.screenshot(path=str(pth), full_page=False)
            shots.append(pth)
            log.info("[%s] screenshot %s (%s)", chain_slug, pth.name, tag)
            idx += 1

        # home grid + scrolls
        shoot("home")
        for _ in range(scrolls):
            page.mouse.wheel(0, 1600)
            page.wait_for_timeout(500)
            shoot("home_scroll")

        # category pages
        for cat in CATEGORIES:
            if not _click_category(page, cat):
                continue
            page.mouse.wheel(0, -10000)  # back to top of the category
            page.wait_for_timeout(400)
            shoot(cat)
            for _ in range(2):
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(450)
                shoot(cat + "_s")

        browser.close()

    if not shots:
        raise RuntimeError("econo: no screenshots captured")
    log.info("[%s] captured %d screenshots", chain_slug, len(shots))
    return shots
