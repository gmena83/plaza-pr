"""Account completion and chat stay inside the real PLAZA dashboard."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "api/static/dashboard.html"
NETLIFY = ROOT / "deploy/netlify/app/index.html"


def test_both_dashboard_copies_have_complete_profile_onboarding_and_assistant():
    html = DASH.read_text()
    assert html == NETLIFY.read_text()
    for marker in ('id="profile-card"', 'id="profile-chains"', 'id="profile-cadence"',
                   'id="profile-save"', 'id="assistant-card"', 'id="assistant-form"',
                   'id="assistant-messages"', 'id="assistant-input"'):
        assert marker in html
    assert "/api/profile" in html
    assert "/api/assistant" in html
    assert "requires_confirmation" in html
    assert "DATOS FICTICIOS" in html


def test_assistant_is_not_shown_to_logged_out_and_only_uses_auth_fetch():
    html = DASH.read_text()
    assert '<section class="card hidden" id="assistant-card"' in html
    assert "apiAuth('/api/assistant'" in html
    assert "apiAuth(action.path" in html
    assert "apiAuth('/api/profile'" in html
    assert "async function loadProfile" in html
