"""Walk-forward baseline evaluation must not turn demo data into evidence."""
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate  # noqa: E402


def weekly(prices, sizes=None, dates=None):
    dates = dates or ["2026-10-07", "2026-10-14", "2026-10-21", "2026-10-28", "2026-11-04", "2026-11-11"]
    sizes = sizes or ["8 OZ"] * len(prices)
    return [(date, [{"sku": "a", "size_text": size, "price_number": str(price)}],
             [{"sku": "a"}]) for date, size, price in zip(dates, sizes, prices)]


def test_no_results_until_four_prior_editions_exist():
    assert evaluate.walk_forward(weekly([2, 2, 3, 3])[:4])["cutoffs"] == []


def test_next_week_baselines_use_only_prices_seen_before_cutoff():
    rows = weekly([2, 2, 3, 3, 4])
    result = evaluate.walk_forward(rows)
    cutoff = result["cutoffs"][0]
    assert cutoff["target_edition"] == "2026-11-04"
    assert cutoff["eligible"] == 1
    assert cutoff["last_price_mae"] == "1.0000"
    assert cutoff["median_price_mae"] == "1.5000"
    assert evaluate.walk_forward(rows + weekly([999], dates=["2026-11-11"]))["cutoffs"][0] == cutoff


def test_pack_change_and_missing_week_are_not_comparable():
    resized = evaluate.walk_forward(weekly([2, 2, 3, 3, 4], sizes=["8 OZ"] * 4 + ["12 OZ"]))
    assert resized["cutoffs"][0]["eligible"] == 0
    gap_dates = ["2026-10-07", "2026-10-14", "2026-10-21", "2026-10-28", "2026-11-11"]
    gap = evaluate.walk_forward(weekly([2, 2, 3, 3, 4], dates=gap_dates))
    assert gap["cutoffs"][0]["eligible"] == 0
    assert gap["cutoffs"][0]["gap_days"] == 14


def test_after_a_gap_four_new_consecutive_training_editions_are_required():
    dates = ["2026-10-07", "2026-10-14", "2026-10-21", "2026-10-28", "2026-11-11", "2026-11-18"]
    result = evaluate.walk_forward(weekly([2] * 6, dates=dates))
    assert result["cutoffs"][0]["eligible"] == 0
    assert result["cutoffs"][1]["eligible"] == 0


def save_pair(cat, shop, price):
    for folder, mode in ((cat, "all"), (shop, "shopper")):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "manifest.json").write_text(json.dumps({"complete": True, "mode": f"type={mode}", "rows": 1}))
        with (folder / "catalog.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("sku", "size_text", "price_number"))
            writer.writeheader()
            writer.writerow({"sku": "a", "size_text": "8 OZ", "price_number": price})


def test_loader_excludes_uncompared_and_partial_edition(tmp_path):
    old_cat, old_shop = tmp_path / "old-cat", tmp_path / "old-shop"
    save_pair(old_cat, old_shop, "2.00")
    new_cat = tmp_path / "pueblo-20261014"
    new_shop = tmp_path / "pueblo-shopper-20261014"
    save_pair(new_cat, new_shop, "3.00")
    assert len(evaluate.load_editions(tmp_path, "2026-10-07", old_cat, old_shop)) == 1
    (new_cat / "week_compare.json").write_text('{"summary": {}}')
    rows = evaluate.load_editions(tmp_path, "2026-10-07", old_cat, old_shop)
    assert [date for date, *_ in rows] == ["2026-10-07", "2026-10-14"]
    (new_shop / "manifest.json").write_text('{"complete": false, "mode": "type=shopper", "rows": 1}')
    import pytest
    with pytest.raises(ValueError, match="incomplete"):
        evaluate.load_editions(tmp_path, "2026-10-07", old_cat, old_shop)


def test_study_report_with_one_real_pair_refuses_prediction(tmp_path):
    old_cat, old_shop = tmp_path / "old-cat", tmp_path / "old-shop"
    save_pair(old_cat, old_shop, "2.00")
    output = tmp_path / "study_evaluation.json"
    report = evaluate.run_study(tmp_path, "2026-10-07", old_cat, old_shop, output)
    assert report["status"] == "insufficient_observations"
    assert report["edition_count"] == 1
    assert report["evaluation_cutoffs"] == 0
    assert report["prediction_release_approved"] is False
    assert json.loads(output.read_text()) == report


def test_review_gate_requires_consecutive_editions_not_just_four_scattered_cutoffs(monkeypatch, tmp_path):
    dates = [(date(2026, 10, 7) + timedelta(days=7 * i + (7 if i >= 6 else 0))).isoformat()
             for i in range(12)]
    monkeypatch.setattr(evaluate, "load_editions", lambda *args: weekly([2] * 12, dates=dates))
    report = evaluate.run_study(tmp_path, "2026-10-07", tmp_path, tmp_path,
                                tmp_path / "study_evaluation.json")
    assert report["evaluation_cutoffs"] == 4
    assert report["status"] == "insufficient_observations"
