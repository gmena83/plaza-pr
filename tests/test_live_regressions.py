"""Regression checks for boot-time network races and Mi Gente's logo images."""
from datetime import date, timedelta

import pytest
from PIL import Image

from scrapers import image_fetch, validity


def test_migente_uses_circular_pages_not_the_two_wide_logos(tmp_path):
    paths = []
    for name, size in (("logo-1.jpg", (2072, 749)),
                       ("logo-2.jpg", (2444, 867)),
                       ("circular.jpg", (2850, 3375))):
        path = tmp_path / name
        Image.new("RGB", size).save(path)
        paths.append(path)
    assert image_fetch.circular_pages(paths, min_aspect=0.95) == [paths[2]]


def test_migente_rejects_hallucinated_old_validity(monkeypatch):
    monkeypatch.setattr(validity, "from_page", lambda chain: None)
    old = date.today() - timedelta(days=730)
    monkeypatch.setattr(validity, "from_image_vl", lambda *a: (old.isoformat(), (old + timedelta(days=13)).isoformat()))
    with pytest.raises(ValueError, match="implausible validity"):
        validity.detect({"type": "images"}, "migente", {}, image_path="circular.jpg", strict=True)


def test_migente_does_not_fallback_to_today_when_date_unreadable(monkeypatch):
    monkeypatch.setattr(validity, "from_page", lambda chain: None)
    monkeypatch.setattr(validity, "from_image_vl", lambda *a: None)
    with pytest.raises(ValueError, match="validity.*not detected"):
        validity.detect({"type": "images"}, "migente", {}, image_path="circular.jpg", strict=True)


def test_database_wait_retries_transient_connect_failure():
    from deploy.wait_for_db import wait_for_database

    attempts = []
    pauses = []
    class Connection:
        def close(self):
            pass
    def connect(dsn, **kwargs):
        attempts.append(dsn)
        if len(attempts) < 3:
            raise ConnectionError("name resolution unavailable")
        return Connection()
    assert wait_for_database("private-dsn", timeout=60, interval=5,
                             connect=connect, clock=lambda: len(pauses) * 5,
                             pause=pauses.append)
    assert len(attempts) == 3
    assert pauses == [5, 5]


def test_database_wait_times_out_without_exposing_credentials():
    from deploy.wait_for_db import wait_for_database

    pauses = []
    def connect(dsn, **kwargs):
        raise ConnectionError("name resolution unavailable")
    with pytest.raises(TimeoutError, match="database unavailable") as exc:
        wait_for_database("postgres://secret@example.test", timeout=10, interval=5,
                          connect=connect, clock=lambda: len(pauses) * 5,
                          pause=pauses.append)
    assert "secret" not in str(exc.value)
    assert pauses == [5, 5]
