"""Synthetic concept belongs in both PLAZA dashboard copies, not a separate app."""
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DASHBOARDS = [ROOT / "api/static/dashboard.html", ROOT / "deploy/netlify/app/index.html"]
CHROME = Path.home() / ".hermes/tools/chromium-1208/chrome-linux64/chrome"


def open_page(browser, path, width=1280):
    page = browser.new_page(viewport={"width": width, "height": 812}, has_touch=width < 500)
    # The concept must still function when the live API is unreachable.
    page.route("https://plaza-pr-api.fly.dev/**", lambda route: route.abort())
    page.goto(path.as_uri(), wait_until="domcontentloaded")
    return page


@pytest.mark.parametrize("path", DASHBOARDS)
def test_projection_is_part_of_main_page_beside_real_history_and_labeled(path):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME), args=["--no-sandbox"])
        try:
            page = open_page(browser, path)
            assert page.locator("#hist").count() == 1
            assert page.locator("#projection-demo").is_visible()
            assert page.locator("#projection-demo").evaluate(
                "e => e.closest('.card').querySelector('#hist') !== null")
            assert "DATOS FICTICIOS" in page.locator("#projection-demo .demo-label").inner_text()
            assert "DATOS FICTICIOS" in page.locator("#projection-demo .demo-result").inner_text()
            assert "No es una predicción validada" in page.locator("#demo-note").inner_text()
            assert "no está conectada" in page.locator("#demo-note").inner_text()
            assert page.locator("#demo-bars .demo-bar-row").count() == 4
            assert page.locator("#demo-best-week").inner_text() == "Semana 3"
            assert page.locator("#demo-feedback").count() == 1
            assert page.locator("#demo-feedback").get_attribute("href").startswith("mailto:contact@menatech.dev")
        finally:
            browser.close()


@pytest.mark.parametrize("path", DASHBOARDS)
def test_demo_responds_to_basket_edits_without_auth_or_live_api(path):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME), args=["--no-sandbox"])
        try:
            page = open_page(browser, path)
            original = page.locator("#demo-bars .demo-amount").all_inner_texts()
            page.locator("#demo-arroz").uncheck()
            assert page.locator("#demo-bars .demo-amount").all_inner_texts() != original
            for box in page.locator(".demo-check").all():
                box.uncheck()
            assert "Selecciona" in page.locator("#demo-best-week").inner_text()
            assert page.locator("#demo-bars .demo-bar-row").count() == 0
            page.locator("#demo-reset").click()
            assert page.locator("#demo-bars .demo-amount").all_inner_texts() == original
        finally:
            browser.close()


@pytest.mark.parametrize("width", [320, 375, 390])
def test_embedded_projection_fits_phone_and_targets_are_touchable(width):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME), args=["--no-sandbox"])
        try:
            page = open_page(browser, DASHBOARDS[0], width)
            dims = page.evaluate("""() => ({width:innerWidth, scroll:document.documentElement.scrollWidth,
              targets:[...document.querySelectorAll('.demo-item, #demo-reset')]
                .map(el=>el.getBoundingClientRect().height)})""")
            assert dims["scroll"] <= dims["width"]
            assert all(height >= 44 for height in dims["targets"])
            assert page.locator("#projection-demo .demo-label").is_visible()
            assert float(page.locator("#demo-note").evaluate(
                "el=>getComputedStyle(el).fontSize.replace('px','')")) >= 12
        finally:
            browser.close()


def test_blank_live_history_does_not_push_demo_below_a_tall_empty_chart():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME), args=["--no-sandbox"])
        try:
            page = open_page(browser, DASHBOARDS[0], 375)
            assert not page.locator("#hist").is_visible()
            assert page.locator("#projection-demo").is_visible()
            page.evaluate("""async () => {
              j = async () => ({points:[{week_start:'2026-10-07',chain_slug:'pueblo',price_sale:2.49}]});
              await drawHistory('arroz');
            }""")
            assert page.locator("#hist").is_visible()
        finally:
            browser.close()
