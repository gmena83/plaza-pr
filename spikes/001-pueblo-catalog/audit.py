"""Read-only, stratified manual-review sample of Pueblo product detail pages.

Use the output JSON for human review; regexes here are observations, not a
production scraper or a claim that every detail page has these fields.
"""
import csv
import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "catalog-pilots"
CAT = DATA / "pueblo-20261013"
SHOP = DATA / "pueblo-shopper-20261013"


def load(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def select():
    catalog = load(CAT / "catalog.csv")
    shopper = load(SHOP / "catalog.csv")
    shopper_skus = {r["sku"] for r in shopper}
    only = [r for r in catalog if r["sku"] not in shopper_skus]
    rng = random.Random(13)
    selected = [("shopper_random", x) for x in rng.sample(shopper, 5)]
    selected += [("catalog_random", x) for x in rng.sample(only, 7)]
    selected += [
        ("shopper_multibuy", next(x for x in shopper if "/" in x["price_text"])),
        ("shopper_weight", next(x for x in shopper if "LB" in x["price_text"])),
        ("catalog_multibuy", next(x for x in only if "/" in x["price_text"])),
        ("catalog_weight", next(x for x in only if "LB" in x["price_text"])),
        ("catalog_last", catalog[-1]),
        ("catalog_min", min(catalog, key=lambda x: float(x["price_number"]))),
        ("catalog_max", max(catalog, key=lambda x: float(x["price_number"]))),
        ("catalog_starred", next(x for x in only if x["product_raw"].startswith("*"))),
    ]
    return selected


def detail(soup, row):
    for tag in soup(["script", "style", "nav", "footer", "noscript"]):
        tag.decompose()
    heading = next((tag for tag in soup.find_all(["h1", "h2", "h3"])
                    if row["product_raw"].lstrip("*").lower() in
                    tag.get_text(" ", strip=True).lower()), None)
    text = soup.get_text(" ", strip=True)
    title = heading.get_text(" ", strip=True) if heading else ""
    start = text.find(title) if title else -1
    window = text[start:start + 800] if start >= 0 else text[:800]
    window = window.split("Productos Similares")[0]
    regular = re.search(r"Reg\.\s*(\$?\s*\d+(?:\.\d+)?(?:\s*LB)?)", window, re.I)
    expiry = re.search(r"Válido hasta el\s+([\w\s]+?\s+\d{4})", window, re.I)
    return {
        "title": title, "price_text_found": row["price_text"] in window,
        "regular_text": regular.group(1) if regular else None,
        "valid_until": expiry.group(1) if expiry else None,
        "availability": ("No Disponible" if "No Disponible" in window else
                         "Disponible" if "Disponible" in window else "not shown"),
        "visible_detail": window[:450],
    }


def main():
    sess = requests.Session()
    sess.headers["User-Agent"] = "PLAZA-catalog-feasibility/1.0 (+https://plaza-pr.netlify.app)"
    out = []
    for tag, row in select():
        record = {"group": tag, "sku": row["sku"], "name": row["product_raw"],
                  "size": row["size_text"], "grid_price": row["price_text"],
                  "grid_price_number": row["price_number"], "page": row["page"],
                  "url": row["product_url"]}
        try:
            response = sess.get(row["product_url"], timeout=25)
            record["http_status"] = response.status_code
            response.raise_for_status()
            record.update(detail(BeautifulSoup(response.text, "lxml"), row))
        except requests.RequestException as exc:
            record["error"] = str(exc)
        out.append(record)
        print(f"{tag} {row['sku']} HTTP {record.get('http_status')} regular={record.get('regular_text')} available={record.get('availability')}", flush=True)
        time.sleep(1.25)
    payload = {"captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "selection": "seeded random (5 shopper, 7 catalog-only) plus 8 edge cases",
               "rows": out}
    path = CAT / "detail_audit.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {path} ({len(out)} detail pages)")


if __name__ == "__main__":
    main()
