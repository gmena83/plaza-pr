"""Compare two complete Pueblo catalog/shopper pairs by SKU and same pack.

The comparison measures displayed-price transitions, not proven regular prices.
"""
from __future__ import annotations

import argparse
import csv
import json
from decimal import Decimal
from pathlib import Path

BASELINE_KIND = "out_of_shopper_displayed_price_not_verified_regular"


def keyed(rows: list[dict]) -> dict[str, dict]:
    result = {}
    for r in rows:
        sku = r["sku"]
        if sku in result:
            raise ValueError(f"duplicate SKU in snapshot: {sku}")
        result[sku] = r
    return result


def same_pack(a: dict, b: dict) -> bool:
    return " ".join(a["size_text"].lower().split()) == " ".join(b["size_text"].lower().split())


def comparison(old: dict, new: dict) -> dict:
    before, after = Decimal(old["price_number"]), Decimal(new["price_number"])
    return {
        "sku": old["sku"], "name_before": old["product_raw"], "name_after": new["product_raw"],
        "size": new["size_text"], "price_before": str(before), "price_after": str(after),
        "price_change": str((after - before).quantize(Decimal("0.0001"))),
        "price_change_pct": (str(((after - before) / before * 100).quantize(Decimal("0.01")))
                             if before else None),
        "product_url": new.get("product_url") or old.get("product_url"),
    }


def compare_snapshots(old_catalog: list[dict], old_shopper: list[dict],
                      new_catalog: list[dict], new_shopper: list[dict]) -> dict:
    old_c, old_s, new_c, new_s = map(keyed, (old_catalog, old_shopper, new_catalog, new_shopper))
    ended_skus, new_skus = old_s.keys() - new_s.keys(), new_s.keys() - old_s.keys()
    ended, newly, continuing = [], [], []
    missing_new, missing_old, resized = [], [], []
    for sku in sorted(ended_skus):
        if sku not in new_c:
            missing_new.append(sku)
        elif not same_pack(old_s[sku], new_c[sku]):
            resized.append(sku)
        else:
            ended.append({**comparison(old_s[sku], new_c[sku]), "baseline_kind": BASELINE_KIND})
    for sku in sorted(new_skus):
        if sku not in old_c:
            missing_old.append(sku)
        elif not same_pack(old_c[sku], new_s[sku]):
            resized.append(sku)
        else:
            newly.append({**comparison(old_c[sku], new_s[sku]),
                          "baseline_kind": "prior_catalog_displayed_price_not_verified_regular"})
    for sku in sorted(old_s.keys() & new_s.keys()):
        if not same_pack(old_s[sku], new_s[sku]):
            resized.append(sku)
        else:
            continuing.append(comparison(old_s[sku], new_s[sku]))
    return {
        "summary": {
            "old_catalog": len(old_c), "new_catalog": len(new_c),
            "old_shopper": len(old_s), "new_shopper": len(new_s),
            "ended_shopper": len(ended_skus), "newly_advertised": len(new_skus),
            "still_shopper": len(old_s.keys() & new_s.keys()),
            "ended_with_same_pack_price": len(ended),
            "new_with_same_pack_prior_price": len(newly),
            "missing_in_new_catalog": len(missing_new),
            "missing_from_old_catalog": len(missing_old),
            "size_changed_skipped": len(resized),
            "ended_higher": sum(Decimal(x["price_change"]) > 0 for x in ended),
            "ended_same": sum(Decimal(x["price_change"]) == 0 for x in ended),
            "ended_lower": sum(Decimal(x["price_change"]) < 0 for x in ended),
            "new_lower": sum(Decimal(x["price_change"]) < 0 for x in newly),
        },
        "ended": ended, "newly_advertised": newly, "continuing": continuing,
        "missing_in_new_catalog_skus": missing_new,
        "missing_from_old_catalog_skus": missing_old, "size_changed_skus": resized,
        "caveat": "Displayed online prices only. Shopper absence and a price increase do not prove a regular price: other promotions, item expiry and availability require detail-page review.",
    }


def load_snapshot(directory: Path, mode: str) -> list[dict]:
    manifest = json.loads((directory / "manifest.json").read_text())
    if not manifest["complete"] or manifest["mode"] != f"type={mode}":
        raise ValueError(f"incomplete or incorrect-mode snapshot: {directory}")
    with (directory / "catalog.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != manifest["rows"]:
        raise ValueError(f"row count mismatch: {directory}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("old-catalog", "old-shopper", "new-catalog", "new-shopper"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = compare_snapshots(
        load_snapshot(args.old_catalog, "all"), load_snapshot(args.old_shopper, "shopper"),
        load_snapshot(args.new_catalog, "all"), load_snapshot(args.new_shopper, "shopper"))
    result["snapshots"] = {name: str(getattr(args, name).resolve())
                           for name in ("old_catalog", "old_shopper", "new_catalog", "new_shopper")}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temp = args.out.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    temp.replace(args.out)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {args.out.resolve()}")


if __name__ == "__main__":
    main()
