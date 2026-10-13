"""Recurring forward-only study must not mistake same-week or partial data for evidence."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import research  # noqa: E402


def mark_complete(folder: Path, mode: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps({"complete": True, "mode": f"type={mode}"}))


def test_previous_pair_requires_a_finished_comparison(tmp_path):
    base_cat, base_shop = tmp_path / "original-cat", tmp_path / "original-shop"
    mark_complete(base_cat, "all")
    mark_complete(base_shop, "shopper")
    first_cat = tmp_path / "pueblo-20261014"
    first_shop = tmp_path / "pueblo-shopper-20261014"
    mark_complete(first_cat, "all")
    mark_complete(first_shop, "shopper")
    # A complete-looking pair without a comparison is not admissible as a prior observation.
    assert research.previous_pair(tmp_path, "2026-10-21", "2026-10-07", base_cat, base_shop) == ("2026-10-07", base_cat, base_shop)
    (first_cat / "week_compare.json").write_text('{"summary": {}}')
    assert research.previous_pair(tmp_path, "2026-10-21", "2026-10-07", base_cat, base_shop) == ("2026-10-14", first_cat, first_shop)


def test_study_skips_unchanged_edition_without_capture(monkeypatch, tmp_path):
    monkeypatch.setattr(research, "current_edition", lambda: "2026-10-07")
    monkeypatch.setattr(research, "run_probe", lambda *args: pytest.fail("unexpected capture"))
    assert research.run_once(tmp_path, "2026-10-07", tmp_path / "old-cat", tmp_path / "old-shop") is None


def test_study_rejects_future_edition_without_capture(monkeypatch, tmp_path):
    monkeypatch.setattr(research, "current_edition", lambda: "2099-10-14")
    monkeypatch.setattr(research, "run_probe", lambda *args: pytest.fail("unexpected capture"))
    with pytest.raises(ValueError, match="future"):
        research.run_once(tmp_path, "2026-10-07", tmp_path / "old-cat", tmp_path / "old-shop")


def test_study_captures_new_pair_and_compares_without_production_db(monkeypatch, tmp_path):
    old_cat, old_shop = tmp_path / "original-cat", tmp_path / "original-shop"
    mark_complete(old_cat, "all")
    mark_complete(old_shop, "shopper")
    monkeypatch.setattr(research, "current_edition", lambda: "2026-10-08")
    captured = []

    def fake_probe(folder, mode, maximum):
        captured.append(mode)
        mark_complete(folder, mode)

    monkeypatch.setattr(research, "run_probe", fake_probe)

    def fake_compare(argv, **kwargs):
        assert "--old-catalog" in argv and str(old_cat) in argv
        assert "--old-shopper" in argv and str(old_shop) in argv
        assert "--new-catalog" in argv and str(tmp_path / "pueblo-20261008") in argv
        assert "--new-shopper" in argv and str(tmp_path / "pueblo-shopper-20261008") in argv
        (tmp_path / "pueblo-20261008" / "week_compare.json").write_text('{"summary": {}}')
        return None

    monkeypatch.setattr(research.subprocess, "run", fake_compare)
    out = research.run_once(tmp_path, "2026-10-07", old_cat, old_shop)
    assert out == tmp_path / "pueblo-20261008" / "week_compare.json"
    assert captured == ["shopper", "all"]
    assert research.run_once(tmp_path, "2026-10-07", old_cat, old_shop) == out
    assert captured == ["shopper", "all"]
