import base64
import hashlib

from app.config import get_settings
from app.platforms.twitter import TwitterPlatform, _code_challenge


def test_code_challenge_is_deterministic_and_matches_spec():
    verifier = "a-fixed-code-verifier-string-for-testing-purposes-1234567890"
    challenge = _code_challenge(verifier)

    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == expected
    assert "=" not in challenge


def test_generate_state_extras_returns_a_fresh_code_verifier():
    platform = TwitterPlatform()
    extras_one = platform.generate_state_extras()
    extras_two = platform.generate_state_extras()

    assert "code_verifier" in extras_one
    assert extras_one["code_verifier"] != extras_two["code_verifier"]
    assert len(extras_one["code_verifier"]) >= 43  # RFC 7636 minimum length


def test_get_authorization_url_includes_pkce_params(monkeypatch):
    monkeypatch.setattr(get_settings(), "twitter_client_id", "test-client-id")
    monkeypatch.setattr(get_settings(), "twitter_redirect_uri", "http://localhost:8000/auth/twitter/callback")

    platform = TwitterPlatform()
    extras = {"code_verifier": "fixed-verifier-for-this-test-1234567890abcdefg"}
    url = platform.get_authorization_url("signed-state-token", extras)

    assert url.startswith("https://twitter.com/i/oauth2/authorize?")
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    assert "state=signed-state-token" in url
    assert "client_id=test-client-id" in url


def test_get_authorization_url_requires_code_verifier():
    platform = TwitterPlatform()
    try:
        platform.get_authorization_url("state", extras={})
    except ValueError as exc:
        assert "code_verifier" in str(exc)
    else:
        raise AssertionError("Expected ValueError when code_verifier is missing")
