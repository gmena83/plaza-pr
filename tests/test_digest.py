"""Unit tests for the Mi Lista digest logic (no database needed)."""
import datetime as dt

from normalize import basket, digest


def offer(chain, price, regular=None):
    return {"chain_slug": chain, "price_sale": price, "price_regular": regular, "_rank": price}


def items(n):
    return [{"id": i} for i in range(1, n + 1)]


def test_single_store_covering_everything_wins():
    its = items(3)
    per = {1: [offer("a", 1.0), offer("b", 0.9)],
           2: [offer("a", 2.0)],
           3: [offer("a", 3.0), offer("c", 1.0)]}
    p = basket.store_plan(its, per)
    assert p["stores"] == ["a"] and p["covered"] == 3 and p["total"] == 6.0
    assert p["elsewhere"] == [] and p["unavailable"] == []


def test_pair_beats_single_when_it_covers_more():
    its = items(4)
    per = {1: [offer("a", 1.0)], 2: [offer("a", 1.0)],
           3: [offer("b", 1.0)], 4: [offer("c", 9.0)]}
    p = basket.store_plan(its, per)
    assert p["covered"] == 3 and set(p["stores"]) == {"a", "b"}
    assert p["stores"][0] == "a"          # store carrying more items first
    assert p["elsewhere"] == [4]


def test_pair_assigns_each_item_to_cheaper_store():
    its = items(3)
    per = {1: [offer("a", 2.0), offer("b", 1.0)],
           2: [offer("a", 1.0)],
           3: [offer("b", 1.0)]}
    p = basket.store_plan(its, per)
    assert set(p["stores"]) == {"a", "b"}
    assert p["assign"][1]["chain_slug"] == "b" and p["total"] == 3.0


def test_tiebreak_uses_whole_list_cost_not_plan_subtotal():
    # {a,b} and {a,c} both cover 2 items. {a,c} has the lower subtotal only
    # because it leaves the expensive item 2 out; the full list is cheaper via {a,b}.
    its = items(3)
    per = {1: [offer("a", 1.0)], 2: [offer("b", 5.0), offer("d", 9.0)],
           3: [offer("c", 1.0), offer("e", 1.5)]}
    p = basket.store_plan(its, per)
    assert set(p["stores"]) == {"a", "b"}


def test_unavailable_items_reported():
    its = items(2)
    p = basket.store_plan(its, {1: [offer("a", 1.0)], 2: []})
    assert p["covered"] == 1 and p["unavailable"] == [2]


def test_no_offers_returns_none():
    assert basket.store_plan(items(2), {1: [], 2: []}) is None


def test_regular_saving_ignores_implausible_regular_prices():
    its = items(2)
    per = {1: [offer("a", 1.0, regular=1.5)], 2: [offer("a", 1.0, regular=50.0)]}
    p = basket.store_plan(its, per)
    assert p["regular_saving"] == 0.5


def test_slot_for_maps_days_to_monday_or_thursday():
    mon, thu = dt.date(2026, 10, 12), dt.date(2026, 10, 8)
    assert digest.slot_for(thu) == thu
    assert digest.slot_for(dt.date(2026, 10, 11)) == thu      # Sunday -> Thursday
    assert digest.slot_for(mon) == mon
    assert digest.slot_for(dt.date(2026, 10, 14)) == mon      # Wednesday -> Monday


def test_pretty_helpers():
    assert digest.pretty_size("8.0x10oz") == "8 × 10oz"
    assert digest.pretty_name("COCA COLA ZERO") == "Coca cola zero"
    assert digest.fmt_unit(0.5973, "$/lb") == "$0.60/lb"
    assert digest.fmt_unit(0.042, "$/oz") == "$0.042/oz"
    assert digest.fmt_unit(2.18, "$/lb") == "$2.18/lb"
    assert digest.short_chain("supermax") == "SuperMax"
    assert digest.short_chain("pueblo", {"pueblo": "Supermercados Pueblo"}) == "Pueblo"


def test_promo_noise_filtered_and_short_promos_kept():
    assert digest.clean_promo("No sujeto a raincheck o sustituto") is None
    assert digest.clean_promo("2x4") == "2x4"
    assert digest.clean_promo("") is None


def test_pct_off_rejects_implausible_regular():
    assert digest.pct_off(1.79, 2.89) == 38
    assert digest.pct_off(1.0, 50.0) is None
    assert digest.pct_off(1.0, 1.0) is None
