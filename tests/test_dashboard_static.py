"""The public app must show its real supermarket coverage by the headline."""
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "api/static/dashboard.html"
COPY = ROOT / "deploy/netlify/app/index.html"


def test_dashboard_coverage_line_names_all_active_chains_below_headline():
    soup = BeautifulSoup(APP.read_text(), "html.parser")
    header = soup.select_one("header.top")
    line = header.select_one(".chainline")
    assert line is not None
    assert header.select_one(".tag").sourceline < line.sourceline
    for name in ("Pueblo", "Amigo", "Ralph", "Econo", "Selectos", "SuperMax",
                 "Mr. Special", "Mi Gente", "Agranel", "Freshmart", "Walmart"):
        assert name in line.get_text(" ")


def test_netlify_app_is_same_dashboard_as_api_copy():
    assert APP.read_bytes() == COPY.read_bytes()


def test_my_list_precedes_secondary_charts_on_phone():
    soup = BeautifulSoup(APP.read_text(), "html.parser")
    assert soup.select_one("#listcard").sourceline < soup.select_one("#hist").sourceline


def test_loginbox_has_all_auth_tabs_and_forms():
    soup = BeautifulSoup(APP.read_text(), "html.parser")
    loginbox = soup.select_one("#loginbox")
    assert loginbox is not None

    # Tab buttons
    for tab_id in ("#tab-login", "#tab-signup", "#tab-magic", "#tab-google"):
        assert loginbox.select_one(tab_id) is not None

    # Form containers
    for form_id in ("#form-login", "#form-signup", "#form-magic", "#form-google"):
        assert loginbox.select_one(form_id) is not None

    # Specific input elements & actions
    assert loginbox.select_one("#login-email") is not None
    assert loginbox.select_one("#login-pass") is not None
    assert loginbox.select_one("#signup-email") is not None
    assert loginbox.select_one("#signup-pass") is not None
    assert loginbox.select_one("#magic-email") is not None
    assert loginbox.select_one(".google-btn") is not None


def test_loginbox_contains_supabase_auth_js_handlers():
    content = APP.read_text()
    for handler in ("loginWithPassword", "signUpWithPassword", "sendMagicLink", "loginWithGoogle", "switchAuthTab"):
        assert handler in content
