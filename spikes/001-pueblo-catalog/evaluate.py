"""Offline walk-forward baselines for observed online display prices, not shopping advice."""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from compare import load_snapshot
from followup import BASE, BASELINE_CATALOG, BASELINE_EDITION, BASELINE_SHOPPER, complete


def load_editions(base: Path, baseline_edition: str, baseline_catalog: Path,
                  baseline_shopper: Path) -> list[tuple[str, list[dict], list[dict]]]:
    """Include only full catalog/shopper pairs with a completed comparison."""
    result = [(baseline_edition, load_snapshot(baseline_catalog, "all"),
               load_snapshot(baseline_shopper, "shopper"))]
    for catalog in sorted(base.glob("pueblo-[0-9]*")):
        match = re.fullmatch(r"pueblo-(\d{8})", catalog.name)
        if not match or not (catalog / "week_compare.json").exists():
            continue
        key = match[1]
        edition = date.fromisoformat(f"{key[:4]}-{key[4:6]}-{key[6:]}").isoformat()
        shopper = base / f"pueblo-shopper-{key}"
        if not complete(catalog, "all") or not complete(shopper, "shopper"):
            raise ValueError(f"incomplete compared snapshot: {catalog}")
        if edition > baseline_edition:
            result.append((edition, load_snapshot(catalog, "all"), load_snapshot(shopper, "shopper")))
    return result


def walk_forward(editions: list[tuple[str, list[dict], list[dict]]]) -> dict:
    """Freeze prior same-SKU/pack prices at each cutoff; score only the following week."""
    history: dict[str, tuple[str, list[Decimal]]] = {}
    cutoffs = []
    preceding: date | None = None
    consecutive_prior = 0
    for index, (edition, catalog, shopper) in enumerate(editions):
        current = date.fromisoformat(edition)
        if preceding is not None and current <= preceding:
            raise ValueError("editions must be strictly chronological")
        gap = (current - preceding).days if preceding is not None else None
        consecutive_prior = consecutive_prior + 1 if gap == 7 else 0
        target_skus = {row["sku"] for row in shopper}
        if index >= 4:
            last_errors, median_errors = [], []
            advertised = 0
            if consecutive_prior >= 4:
                for row in catalog:
                    sku = row["sku"]
                    pack = " ".join(row["size_text"].lower().split())
                    if sku not in history or not row["price_number"]:
                        continue
                    old_pack, past = history[sku]
                    if pack != old_pack:
                        continue
                    actual = Decimal(row["price_number"])
                    ordered = sorted(past)
                    midpoint = len(ordered) // 2
                    prior_median = (ordered[midpoint] if len(ordered) % 2
                                    else (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2))
                    last_errors.append(abs(actual - past[-1]))
                    median_errors.append(abs(actual - prior_median))
                    advertised += sku in target_skus
            def mae(errors: list[Decimal]) -> str | None:
                return str((sum(errors) / len(errors)).quantize(Decimal("0.0001"))) if errors else None
            cutoffs.append({"target_edition": edition, "gap_days": gap,
                            "eligible": len(last_errors), "advertised_target": advertised,
                            "last_price_mae": mae(last_errors),
                            "median_price_mae": mae(median_errors)})
        if gap not in (None, 7):
            history.clear()
        updated = {}
        for row in catalog:
            if not row["price_number"]:
                continue
            sku = row["sku"]
            pack = " ".join(row["size_text"].lower().split())
            previous = history.get(sku)
            past = previous[1] if previous and previous[0] == pack else []
            updated[sku] = (pack, past + [Decimal(row["price_number"])])
        history = updated
        preceding = current
    return {"cutoffs": cutoffs}


def run_study(base: Path, baseline_edition: str, baseline_catalog: Path,
              baseline_shopper: Path, output: Path) -> dict:
    editions = load_editions(base, baseline_edition, baseline_catalog, baseline_shopper)
    scores = walk_forward(editions)
    assessable = [c for c in scores["cutoffs"] if c["eligible"] > 0]
    consecutive_cutoffs = best_run = 0
    for cutoff in scores["cutoffs"]:
        if cutoff["gap_days"] != 7 or cutoff["eligible"] == 0:
            consecutive_cutoffs = 0
        else:
            consecutive_cutoffs += 1
            best_run = max(best_run, consecutive_cutoffs)
    status = ("baseline_review_possible" if len(editions) >= 8 and best_run >= 4
              else "insufficient_observations")
    report = {"status": status, "edition_count": len(editions),
              "editions": [e[0] for e in editions],
              "evaluation_cutoffs": len(assessable),
              "max_consecutive_review_cutoffs": best_run, "cutoffs": scores["cutoffs"],
              "candidate_model_evaluated": False, "basket_decision_validated": False,
              "prediction_release_approved": False,
              "scope": "Online displayed prices, Pueblo only. SKU/pack match does not verify stock or non-promo price. Baselines are not forecasts offered to users."}
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temp.replace(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=BASE)
    options = parser.parse_args()
    report = run_study(options.base, BASELINE_EDITION, BASELINE_CATALOG,
                       BASELINE_SHOPPER, options.base / "study_evaluation.json")
    print(json.dumps({"status": report["status"], "edition_count": report["edition_count"],
                      "evaluation_cutoffs": report["evaluation_cutoffs"],
                      "prediction_release_approved": False}, indent=2))
    print(f"Study report: {options.base / 'study_evaluation.json'}")


if __name__ == "__main__":
    main()
