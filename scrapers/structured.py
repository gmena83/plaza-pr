"""Scraper for the shared Pueblo/Amigo product platform.

The shopper product grid is server-rendered paginated HTML at:
  {base}/controllers/products.html?type=shopper&page=N&sort=name&query=&category_id=
Each card: SKU in /productos/<sku>/..., brand div.font-semibold, name text,
size in div.text-xs.text-gray-500, price in div.text-lg.font-semibold.
We paginate until a page returns no product anchors.
"""
import logging
import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

from .common import get, parse_price, parse_size_unit, session

log = logging.getLogger("pr-shopper.structured")


def _norm(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "")).strip().lower()
    t = re.sub(r"[^a-z0-9\u00f1\u00e1\u00e9\u00ed\u00f3\u00fa ]", "", t)
    return t


def scrape(chain: dict) -> list[dict]:
    slug_name = chain["name"]
    base = chain["base_url"].rstrip("/")
    endpoint = base + chain["products_endpoint"]
    max_pages = int(chain.get("max_pages", 60))
    sess = session()

    offers: list[dict] = []
    seen_skus: set[str] = set()
    empty_streak = 0

    for page in range(1, max_pages + 1):
        url = endpoint.format(page=page)
        r = get(url, sess=sess)
        soup = BeautifulSoup(r.text, "lxml")
        anchors = soup.select('a[href*="/productos/"]')
        if not anchors:
            empty_streak += 1
            log.info("%s page %d: no products (streak %d)", slug_name, page, empty_streak)
            if empty_streak >= 1:
                break
            continue

        new_this_page = 0
        for a in anchors:
            href = a.get("href", "")
            m = re.search(r"/productos/(\d+)/", href)
            sku = m.group(1) if m else href
            if sku in seen_skus:
                continue

            # brand + name
            brand_el = a.select_one(".font-semibold")
            brand = brand_el.get_text(strip=True) if brand_el else None
            name_container = a.select_one(".uppercase.tracking-wide.text-sm") or a
            name_txt = name_container.get_text(" ", strip=True)
            if brand and name_txt.startswith(brand):
                name_txt = name_txt[len(brand):].strip()
            product_raw = (f"{brand} {name_txt}".strip() if brand else name_txt) or name_txt

            # the price/size live in siblings after the </a>
            parent = a.parent
            block_txt = parent.get_text(" ", strip=True) if parent else ""
            size_el = parent.select_one(".text-xs.text-gray-500") if parent else None
            price_el = parent.select_one(".text-lg.font-semibold") if parent else None
            size_text = size_el.get_text(strip=True) if size_el else None
            price_text = price_el.get_text(strip=True) if price_el else None

            price_sale = parse_price(price_text or "")
            # detect "2/$5" style promo inside price text
            promo = None
            if price_text and re.search(r"\d+\s*/\s*\$", price_text):
                promo = price_text.strip()

            _, unit_basis = parse_size_unit(" ".join([size_text or "", price_text or ""]))

            if not product_raw or price_sale is None:
                continue

            seen_skus.add(sku)
            new_this_page += 1
            offers.append({
                "chain_slug": None,  # filled by orchestrator
                "sku": sku,
                "product_raw": product_raw,
                "product_norm": _norm(product_raw),
                "brand": brand,
                "size_text": size_text,
                "price_sale": price_sale,
                "price_regular": None,
                "unit_basis": unit_basis,
                "promo": promo,
                "page": page,
                "source_url": base + href if href.startswith("/") else href,
            })

        log.info("%s page %d: %d new products (total %d)",
                 slug_name, page, new_this_page, len(offers))
        if new_this_page == 0:
            # we've wrapped around to already-seen products -> done
            break

    return offers


if __name__ == "__main__":
    from .common import load_config
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    for slug in ("pueblo", "amigo"):
        chain = cfg["chains"][slug]
        res = scrape(chain)
        print(f"\n=== {slug}: {len(res)} offers ===")
        for o in res[:5]:
            print(f"  {o['product_raw']!r:50} ${o['price_sale']}  [{o['size_text']}]")
