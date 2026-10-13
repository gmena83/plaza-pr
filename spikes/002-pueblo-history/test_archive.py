"""Pueblo historical circular extraction keeps auditable page-level evidence."""
import importlib.util
from pathlib import Path
from PIL import Image
import pytest

SPEC = importlib.util.spec_from_file_location("pueblo_archive", Path(__file__).with_name("archive.py"))
archive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive)


def image(path):
    Image.new("RGB", (4, 4), "white").save(path, format="JPEG")


def test_page_cache_is_tied_to_image_checksum(tmp_path):
    img = tmp_path / "page-01.jpg"
    image(img)
    calls = []

    def extract(path):
        calls.append(path)
        return [{"product": "Arroz", "price_sale": 2.5}]

    first = archive.capture_page(img, tmp_path / "out", extract)
    second = archive.capture_page(img, tmp_path / "out", extract)
    assert first == second
    assert len(calls) == 1
    assert first["rows"][0]["product"] == "Arroz"
    img.write_bytes(img.read_bytes() + b"changed")
    archive.capture_page(img, tmp_path / "out", extract)
    assert len(calls) == 2


def test_empty_or_failed_page_never_marked_complete(tmp_path):
    folder = tmp_path / "images"
    folder.mkdir()
    image(folder / "page-01.jpg")
    with pytest.raises(ValueError):
        archive.capture_week("2026-09-30", folder, tmp_path / "out",
                             lambda path: [])
    assert not (tmp_path / "out" / "manifest.json").exists()


def test_complete_week_records_all_eight_pages(tmp_path):
    folder = tmp_path / "images"
    folder.mkdir()
    for n in range(1, 9):
        image(folder / f"page-{n:02d}.jpg")
    manifest = archive.capture_week("2026-09-30", folder, tmp_path / "out",
                                    lambda path: [{"product": path.stem, "price_sale": 0.99}])
    assert manifest["complete"] is True
    assert manifest["pages"] == 8
    assert manifest["rows"] == 8
    assert manifest["valid_from"] == "2026-09-30"
    assert manifest["valid_to"] == "2026-10-06"


def test_truncated_full_page_is_retried_in_overlapping_halves(tmp_path):
    img = tmp_path / "page-02.jpg"
    Image.new("RGB", (1200, 1500), "white").save(img, format="JPEG")
    sizes = []

    def extract(path):
        with Image.open(path) as part:
            sizes.append(part.size)
        if path == img:
            return []
        return [{"product": "Arroz" if "top" in path.stem else "Leche",
                 "price_sale": 2.49}]

    rows = archive.extract_with_tiles(img, extract)
    assert [r["product"] for r in rows] == ["Arroz", "Leche"]
    assert sizes[0] == (1200, 1500)
    assert len(sizes) == 3
    assert all(s[1] < 850 for s in sizes[1:])


def test_failed_half_retries_four_quadrants_without_silent_omission(tmp_path):
    img = tmp_path / "page-02.jpg"
    Image.new("RGB", (1200, 1500), "white").save(img, format="JPEG")

    def extract(path):
        if "quad" in path.stem:
            return [{"product": path.stem, "price_sale": 2.49}]
        return []

    rows = archive.extract_with_tiles(img, extract)
    assert len(rows) == 4
    assert all("quad" in r["product"] for r in rows)
