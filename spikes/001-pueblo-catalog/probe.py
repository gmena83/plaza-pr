"""Read-only, resumable snapshot of Pueblo's public online product catalog.

Example:
  .venv/bin/python spikes/001-pueblo-catalog/probe.py \
      --out data/catalog-pilots/pueblo-20261013 --max-pages 1600

Does not connect to PLAZA's database or classify catalog prices as regular prices.
Each fetched HTML page is saved compressed for a reproducible, offline re-parse.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.puebloweb.com"
ENDPOINT = BASE + "/controllers/products.html"
FIELDS = ("sku", "product_raw", "brand", "size_text", "price_text", "price_number",
          "page", "captured_at", "product_url")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def price_number(text: str) -> str:
    """Convert an advertised price to per-item dollars, retaining raw text separately.

    No inference is made that this is a regular price. Ambiguous strings are blank.
    """
    t = text.replace(",", "").strip()
    if not t:
        return ""
    multi = re.search(r"(\d+)\s*/\s*\$?\s*(\d+(?:\.\d+)?)\s*(¢)?", t)
    if multi:
        q, v = Decimal(multi[1]), Decimal(multi[2])
        if not q:
            return ""
        return str((v / (Decimal(100) if multi[3] else Decimal(1)) / q).quantize(Decimal("0.0001")))
    cents = re.search(r"(\d+(?:\.\d+)?)\s*¢", t)
    if cents:
        return str((Decimal(cents[1]) / 100).quantize(Decimal("0.0001")))
    dollars = re.search(r"\$\s*(\d+(?:\.\d+)?)", t)
    if dollars:
        return str(Decimal(dollars[1]).quantize(Decimal("0.0001")))
    bare = re.fullmatch(r"\s*(\d+\.\d{2})(?:\s+(?:LB|EA|UN))?\s*", t, re.I)
    if bare:
        return str(Decimal(bare[1]).quantize(Decimal("0.0001")))
    return ""


def parse_cards(html: bytes, page: int, captured_at: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    result = []
    for anchor in soup.select('a[href*="/productos/"]'):
        href = anchor.get("href", "")
        match = re.search(r"/productos/([0-9]+)/", href)
        if not match:
            continue
        brand_el = anchor.select_one(".font-semibold")
        name_el = anchor.select_one(".uppercase.tracking-wide.text-sm") or anchor
        brand = brand_el.get_text(" ", strip=True) if brand_el else ""
        name = name_el.get_text(" ", strip=True)
        if brand and name.startswith(brand):
            name = name[len(brand):].strip()
        product_raw = (brand + " " + name).strip() if brand else name
        parent = anchor.parent
        size_el = parent.select_one(".text-xs.text-gray-500") if parent else None
        price_el = parent.select_one(".text-lg.font-semibold") if parent else None
        raw_price = price_el.get_text(" ", strip=True) if price_el else ""
        result.append({
            "sku": match[1], "product_raw": product_raw, "brand": brand,
            "size_text": size_el.get_text(" ", strip=True) if size_el else "",
            "price_text": raw_price, "price_number": price_number(raw_price),
            "page": page, "captured_at": captured_at,
            "product_url": urljoin(BASE, href),
        })
    return result


def atomic_json(path: Path, obj: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def fetch(sess: requests.Session, page: int, out: Path, request_interval: float,
          last_request: float, product_type: str = "all") -> tuple[bytes, dict, float, bool]:
    html_path = out / "pages" / f"{page:05d}.html.gz"
    meta_path = out / "pages" / f"{page:05d}.json"
    if html_path.exists() and meta_path.exists():
        data = gzip.decompress(html_path.read_bytes())
        meta = json.loads(meta_path.read_text())
        if f"type={product_type}" not in meta["url"]:
            raise ValueError(f"cached page {page} is not type={product_type}; choose another --out")
        if hashlib.sha256(data).hexdigest() != meta["sha256"]:
            raise ValueError(f"cached page {page}: checksum mismatch")
        return data, meta, last_request, True
    params = {"type": product_type, "page": page, "sort": "name", "query": "", "category_id": ""}
    for attempt in range(4):
        elapsed = time.monotonic() - last_request
        if elapsed < request_interval:
            time.sleep(request_interval - elapsed)
        last_request = time.monotonic()
        try:
            r = sess.get(ENDPOINT, params=params, timeout=30)
            if r.status_code == 429:
                raise RuntimeError("rate limited (HTTP 429); stop and resume later")
            r.raise_for_status()
            data = r.content
            # This endpoint responds HTTP 200 with a zero-byte body after its last page.
            # The caller confirms the end with a second consecutive empty page.
            meta = {"page": page, "url": r.url, "captured_at": now(), "status": r.status_code,
                    "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            temp = html_path.with_suffix(".gz.tmp")
            with gzip.open(temp, "wb", compresslevel=6) as f:
                f.write(data)
            temp.replace(html_path)
            atomic_json(meta_path, meta)
            return data, meta, last_request, False
        except (requests.RequestException, ValueError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def write_snapshot(out: Path, rows: list[dict], manifest: dict) -> None:
    csv_path = out / "catalog.csv"
    temp = csv_path.with_suffix(".csv.tmp")
    with temp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(csv_path)
    atomic_json(out / "manifest.json", manifest)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--max-pages", type=int, default=1600)
    p.add_argument("--type", choices=("all", "shopper"), default="all")
    p.add_argument("--interval", type=float, default=1.25,
                   help="minimum seconds between HTTP requests (default: 1.25)")
    args = p.parse_args()
    if args.max_pages < 1 or args.interval < 0.5:
        p.error("--max-pages must be positive and --interval must be at least 0.5")
    out = args.out.resolve()
    (out / "pages").mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    sess.headers.update({"User-Agent": "PLAZA-catalog-feasibility/1.0 (+https://plaza-pr.netlify.app)",
                         "Accept-Language": "es-PR,es;q=0.9,en;q=0.8"})
    started = now()
    rows: list[dict] = []
    last_request = 0.0
    empty_streak = 0
    signatures: set[tuple[str, ...]] = set()
    terminal = "max_pages"
    pages_with_products = 0
    net_requests = 0
    total_bytes = 0
    page = 0
    try:
        for page in range(1, args.max_pages + 1):
            html, meta, last_request, cached = fetch(
                sess, page, out, args.interval, last_request, args.type)
            net_requests += not cached
            total_bytes += meta["bytes"]
            page_rows = parse_cards(html, page, meta["captured_at"])
            signature = tuple(r["sku"] for r in page_rows)
            if not signature:
                empty_streak += 1
                if empty_streak == 2:
                    terminal = "two_consecutive_empty_pages"
                    break
            else:
                if signature in signatures:
                    terminal = "repeated_sku_page"
                    break
                signatures.add(signature)
                pages_with_products += 1
                empty_streak = 0
                rows.extend(page_rows)
            if page % 50 == 0:
                print(f"page={page} rows={len(rows)} network_requests={net_requests}", flush=True)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        terminal = f"error:{type(exc).__name__}:{exc}"
        print(f"Stopped: {terminal}", flush=True)
    sku_counts: dict[str, int] = {}
    for row in rows:
        sku_counts[row["sku"]] = sku_counts.get(row["sku"], 0) + 1
    manifest = {
        "chain": "pueblo", "source": ENDPOINT, "mode": f"type={args.type}",
        "scope": ("online catalog display prices; not verified in-store regular prices"
                  if args.type == "all" else "advertised online shopper products"),
        "run_started_at": started, "finished_at": now(),
        "snapshot_captured_first_at": rows[0]["captured_at"] if rows else None,
        "snapshot_captured_last_at": rows[-1]["captured_at"] if rows else None,
        "request_interval_seconds": args.interval,
        "max_pages": args.max_pages, "termination": terminal,
        "complete": terminal in ("two_consecutive_empty_pages", "repeated_sku_page"),
        "pages_with_products": pages_with_products, "pages_attempted": page,
        "network_requests_this_run": net_requests, "uncompressed_bytes_of_pages": total_bytes,
        "rows": len(rows), "unique_skus": len(sku_counts),
        "duplicate_sku_rows": len(rows) - len(sku_counts),
        "missing_name": sum(not x["product_raw"] for x in rows),
        "missing_size": sum(not x["size_text"] for x in rows),
        "missing_price": sum(not x["price_number"] for x in rows),
        "raw_pages_dir": str(out / "pages"), "csv": str(out / "catalog.csv"),
    }
    write_snapshot(out, rows, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    if terminal.startswith("error:"):
        raise SystemExit(1)
    if not manifest["complete"]:
        print("Partial snapshot. Re-run with a larger --max-pages to resume.", flush=True)


if __name__ == "__main__":
    main()
