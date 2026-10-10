"""Offline contract tests for shared scraper parsing helpers."""

import pytest

from scrapers.common import parse_size_unit


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12 oz", ("12 oz", "oz")),
        ("1 lb", ("1 lb", "lb")),
        ("cajá\u00a024 UN", ("24 un", "un")),
        ("0.5 litro", ("0.5 litro", "l")),
        ("12 ounces", (None, None)),
        ("", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_size_unit_documented_and_boundary_inputs(text, expected):
    """Supported units parse across case/Unicode whitespace; longer unit words do not."""
    result = parse_size_unit(text)

    assert result == expected
    assert isinstance(result, tuple)
    assert len(result) == 2
