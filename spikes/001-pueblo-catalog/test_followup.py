"""The follow-up must wait for a changed printed shopper window."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import followup  # noqa: E402


def test_edition_date_reads_pueblo_spanish_header():
    assert followup.edition_date("<h3>Válido del 14 al 20 de Octubre 2026</h3>") == "2026-10-14"


def test_edition_date_refuses_missing_dates():
    with pytest.raises(ValueError):
        followup.edition_date("<h3>Shopper disponible</h3>")


def test_current_baseline_is_not_a_new_edition():
    assert followup.is_new_edition("2026-10-07") is False
    assert followup.is_new_edition("2026-10-14") is True
