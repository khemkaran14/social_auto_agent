import time

import pytest
from cryptography.fernet import Fernet

from app.config import get_settings
from app.core import security


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch):
    monkeypatch.setattr(get_settings(), "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(get_settings(), "secret_key", "test-secret-key")
    security.settings = get_settings()
    yield


def test_encrypt_decrypt_roundtrip():
    plaintext = "super-secret-linkedin-access-token"
    ciphertext = security.encrypt_token(plaintext)
    assert ciphertext != plaintext
    assert security.decrypt_token(ciphertext) == plaintext


def test_sign_and_verify_state_roundtrip():
    token = security.sign_state({"user_id": 42, "platform": "linkedin"})
    payload = security.verify_state(token)
    assert payload["user_id"] == 42
    assert payload["platform"] == "linkedin"


def test_verify_state_rejects_tampered_token():
    token = security.sign_state({"user_id": 42})
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(ValueError):
        security.verify_state(tampered)


def test_verify_state_rejects_expired_token(monkeypatch):
    token = security.sign_state({"user_id": 42})
    future = time.time() + security._STATE_TTL_SECONDS + 1
    monkeypatch.setattr(time, "time", lambda: future)
    with pytest.raises(ValueError):
        security.verify_state(token)


def test_password_hash_roundtrip():
    password_hash = security.hash_password("correct-horse-battery-staple")
    assert password_hash != "correct-horse-battery-staple"
    assert security.verify_password("correct-horse-battery-staple", password_hash)
    assert not security.verify_password("wrong-password", password_hash)


def test_access_token_roundtrip():
    token = security.create_access_token(user_id=7)
    assert security.decode_access_token(token) == 7


def test_access_token_rejects_expired(monkeypatch):
    monkeypatch.setattr(get_settings(), "jwt_access_token_expire_minutes", -1)
    token = security.create_access_token(user_id=7)
    with pytest.raises(ValueError):
        security.decode_access_token(token)


def test_access_token_rejects_garbage():
    with pytest.raises(ValueError):
        security.decode_access_token("not-a-real-token")
