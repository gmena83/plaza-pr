"""Contract tests for the throwaway Pueblo snapshot probe."""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe  # noqa: E402


def test_empty_200_response_is_a_valid_end_page(tmp_path, monkeypatch):
    class Session(requests.Session):
        def get(self, url, **kwargs):
            r = requests.Response()
            r.status_code = 200
            r._content = b""
            r.url = f"{url}?page=1122"
            return r

    (tmp_path / "pages").mkdir()
    monkeypatch.setattr(probe.time, "sleep", lambda _: None)
    data, meta, _, cached = probe.fetch(Session(), 1122, tmp_path, 0.5, 0.0)
    assert data == b""
    assert meta["bytes"] == 0
    assert cached is False


def test_shopper_mode_requests_shopper_products(tmp_path):
    class Session(requests.Session):
        def get(self, url, **kwargs):
            assert kwargs["params"]["type"] == "shopper"
            r = requests.Response()
            r.status_code = 200
            r._content = b""
            r.url = f"{url}?type=shopper&page=1"
            return r

    (tmp_path / "pages").mkdir()
    _, meta, _, _ = probe.fetch(Session(), 1, tmp_path, 0.5, 0.0, product_type="shopper")
    assert "type=shopper" in meta["url"]
