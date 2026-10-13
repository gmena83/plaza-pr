"""Local, resumable, read-only transcription of three archived Pueblo flyers.

Output is page-level raw VL extraction for human audit, NOT production offers:
archived JPEGs have no Pueblo SKU and no historical full-catalog prices.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from typing import Callable

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
WEEKS = ("2026-09-30", "2026-09-23", "2026-09-16")


def capture_page(image_path: Path, out_dir: Path, extractor: Callable[[Path], list[dict]]) -> dict:
    data = image_path.read_bytes()
    if not data.startswith(b"\xff\xd8"):
        raise ValueError(f"not a JPEG: {image_path}")
    with Image.open(image_path) as img:
        img.verify()
    sha = hashlib.sha256(data).hexdigest()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{image_path.stem}.json"
    if target.exists():
        cached = json.loads(target.read_text())
        if cached.get("image_sha256") == sha and cached.get("rows"):
            return cached
    rows = extractor(image_path)
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"no parseable products on {image_path}; manual review required")
    record = {"image": image_path.name, "image_sha256": sha,
              "extracted_at_utc": datetime.now(timezone.utc).isoformat(), "rows": rows}
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    temp.replace(target)
    return record


def extract_with_tiles(image_path: Path, extractor: Callable[[Path], list[dict]]) -> list[dict]:
    rows = extractor(image_path)
    if rows:
        return rows
    # Dense flyers can exhaust the output token limit and leave invalid JSON.
    with Image.open(image_path) as img:
        width, height = img.size
        split = height // 2
        halves = (("top", (0, 0, width, split + 30)),
                  ("bottom", (0, split - 30, width, height)))
        center = width // 2
        quarters = tuple((f"quad-{row}-{col}", (x0, y0, x1, y1))
                         for row, y0, y1 in (("top", 0, split + 30),
                                             ("bottom", split - 30, height))
                         for col, x0, x1 in (("left", 0, center + 30),
                                             ("right", center - 30, width)))
        combined = []
        for tiles in (halves, quarters):
            combined = []
            for name, box in tiles:
                tile = image_path.with_name(f"{image_path.stem}-{name}.jpg")
                img.crop(box).save(tile, format="JPEG", quality=95)
                piece = extractor(tile)
                if not piece:
                    break
                combined.extend(piece)
            else:
                break
        else:
            raise ValueError(f"local model could not parse all tiles of {image_path}")
    seen, unique = set(), []
    for row in combined:
        key = (str(row.get("product", "")).casefold(), str(row.get("price_sale")),
               str(row.get("size", "")).casefold())
        if key not in seen:
            unique.append(row)
            seen.add(key)
    return unique


def capture_week(week: str, images_dir: Path, out_dir: Path,
                 extractor: Callable[[Path], list[dict]]) -> dict:
    start = date.fromisoformat(week)
    manifest_path = out_dir / "manifest.json"
    manifest_path.unlink(missing_ok=True)
    images = [images_dir / f"page-{n:02d}.jpg" for n in range(1, 9)]
    if not all(img.is_file() for img in images):
        raise ValueError(f"{week} needs all eight JPEG pages before extraction")
    records = []
    for image in images:
        record = capture_page(image, out_dir, extractor)
        records.append(record)
        print(f"{week} {image.name}: {len(record['rows'])} raw rows", flush=True)
    manifest = {
        "complete": True, "source": "cdn.shoppersdepuertorico.com/shopper-pueblo-...-pagina-NN.jpg",
        "valid_from": week, "valid_to": (start + timedelta(days=6)).isoformat(),
        "pages": len(records), "rows": sum(len(x["rows"]) for x in records),
        "missing_size_rows": sum(not r.get("size") for x in records for r in x["rows"]),
        "page_files": [{"image": r["image"], "sha256": r["image_sha256"],
                        "rows": len(r["rows"])} for r in records],
        "limitations": "Raw VL transcription of advertised flyer specials, not a full catalog or verified SKU join. Merchant 'Reg.' is not independently observed.",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    temp = manifest_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    temp.replace(manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weeks", nargs="+", default=list(WEEKS), choices=WEEKS)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from openai import OpenAI
    from scrapers.common import load_config
    from scrapers.extract_vl import extract_page

    config = load_config()["vl"]
    config["max_tokens"] = 4096
    client = OpenAI(base_url=config["serve_url"], api_key="EMPTY", timeout=180)
    def extract(path: Path) -> list[dict]:
        return extract_with_tiles(path, lambda tile: extract_page(client, config["model"], tile, config))
    for week in args.weeks:
        result = capture_week(week, ROOT / "data/pages" / f"pueblo_{week}",
                              ROOT / "data/catalog-pilots/pueblo-archive" / week, extract)
        print(json.dumps({"week": week, "pages": result["pages"], "rows": result["rows"],
                          "missing_size_rows": result["missing_size_rows"]}), flush=True)


if __name__ == "__main__":
    main()
