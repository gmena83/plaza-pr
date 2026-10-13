"""Next-edition comparison must not invent regular prices."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare  # noqa: E402


def row(sku, size, price):
    return {"sku": sku, "size_text": size, "price_number": price,
            "product_raw": sku, "price_text": f"${price}"}


def test_transitions_are_compared_only_with_same_sku_and_pack():
    old_catalog = [row("ended", "8 OZ", "2.0000"), row("new", "12 OZ", "5.0000"),
                   row("resized", "1 LB", "1.0000")]
    old_shopper = [old_catalog[0], old_catalog[2]]
    new_catalog = [row("ended", "8 OZ", "3.0000"), row("new", "12 OZ", "3.0000"),
                   row("resized", "2 LB", "2.0000")]
    new_shopper = [new_catalog[1]]

    result = compare.compare_snapshots(old_catalog, old_shopper, new_catalog, new_shopper)

    assert result["summary"]["ended_shopper"] == 2
    assert result["summary"]["new_shopper"] == 1
    assert result["summary"]["size_changed_skipped"] == 1
    assert result["ended"][0]["sku"] == "ended"
    assert result["ended"][0]["price_change"] == "1.0000"
    assert result["ended"][0]["baseline_kind"] == "out_of_shopper_displayed_price_not_verified_regular"
    assert result["newly_advertised"][0]["sku"] == "new"
    assert result["newly_advertised"][0]["price_change"] == "-2.0000"


def test_disappeared_sku_is_not_reported_as_price_change():
    result = compare.compare_snapshots([row("gone", "8 OZ", "2.0000")],
                                       [row("gone", "8 OZ", "2.0000")], [], [])
    assert result["summary"]["missing_in_new_catalog"] == 1
    assert result["ended"] == []


def test_same_edition_keeps_total_shopper_count_and_zero_new_promotions():
    catalog = [row("same", "8 OZ", "2.0000")]
    result = compare.compare_snapshots(catalog, catalog, catalog, catalog)
    assert result["summary"]["new_shopper"] == 1
    assert result["summary"]["newly_advertised"] == 0
