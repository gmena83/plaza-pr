"""Phone-width smoke checks for the existing PLAZA dashboard."""
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path.home() / ".hermes/tools/chromium-1208/chrome-linux64/chrome"
DASHBOARD = (ROOT / "api/static/dashboard.html").as_uri()


@pytest.mark.parametrize("width", [320, 375, 390])
def test_search_button_and_page_fit_phone_viewport(width):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(CHROME),
                                             args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": width, "height": 812}, device_scale_factor=1)
        try:
            page.goto(DASHBOARD, wait_until="domcontentloaded")
            fit = page.evaluate("""() => ({screen:innerWidth, doc:document.documentElement.scrollWidth,
              search:document.querySelector('.searchbar button').getBoundingClientRect().right})""")
            assert fit["doc"] <= fit["screen"]
            assert fit["search"] <= fit["screen"]
        finally:
            browser.close()


def test_phone_list_actions_have_finger_sized_targets():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(CHROME), args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 375, "height": 812}, has_touch=True)
        try:
            page.goto(DASHBOARD, wait_until="domcontentloaded")
            sizes = page.evaluate("""() => ['addbtn','xbtn','sizetog'].map(cls => {
              const btn=document.createElement('button'); btn.className=cls;
              document.body.appendChild(btn); const r=btn.getBoundingClientRect();
              return {cls,width:r.width,height:r.height}; })""")
            assert all(x["width"] >= 44 and x["height"] >= 44 for x in sizes)
        finally:
            browser.close()


def test_phone_search_result_is_a_card_not_a_seven_column_scroll():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(CHROME), args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 375, "height": 812}, has_touch=True)
        try:
            page.goto(DASHBOARD, wait_until="domcontentloaded")
            fit = page.evaluate("""() => {
              SEARCH.results=[{_i:0, product_raw:'Arroz grano mediano',product_norm:'arroz grano mediano',
                chain_slug:'pueblo',price_sale:2.49,unit_price:0.83,price_basis:'lb',
                size_text:'3 lb',size_canonical:'3 lb',sku:'123'}];
              document.querySelector('#rescard').classList.remove('hidden'); renderResults();
              const card=document.querySelector('#rescard');
              const row=document.querySelector('#restable tr.rowlink');
              return {rowWidth:row.getBoundingClientRect().width,cardWidth:card.clientWidth,
                      text:row.innerText,add:row.querySelector('.addbtn').getBoundingClientRect().width};
            }""")
            assert fit["rowWidth"] <= fit["cardWidth"]
            assert fit["add"] >= 44
            assert "Arroz grano mediano" in fit["text"]
        finally:
            browser.close()


def test_phone_secondary_movers_fit_with_long_realistic_names():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(CHROME), args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 375, "height": 812}, has_touch=True)
        try:
            page.goto(DASHBOARD, wait_until="domcontentloaded")
            page.evaluate("""() => {
              const names=['House of Raeford Muslos de Pollo','Detergente Líquido Ace Simply',
                'Pinchos de Pollo ECONO','Filete de Carrucho','Pechugas de Pollo AriztiA*',
                'Lechuga Romana','Gandules Verdes ECONO','New York Steak Choice',
                'Gandules ECONO','Selectos Pimientos Morrones','Especias Badia',
                'Coca Cola, Sprite o Fanta Refresco'];
              document.querySelector('#movers tbody').innerHTML = names.map(n =>
                `<tr><td>${n}</td><td>selectos</td><td class="price">$0.57</td><td class="down">-92.9%</td></tr>`).join('');
            }""")
            fit = page.evaluate("""() => ({screen:innerWidth,
              doc:document.documentElement.scrollWidth,
              table:document.querySelector('#movers').getBoundingClientRect().right,
              card:document.querySelector('#movers').closest('.card').getBoundingClientRect().right})""")
            assert fit["doc"] <= fit["screen"]
            assert fit["table"] <= fit["card"]
        finally:
            browser.close()
