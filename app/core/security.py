"""Token encryption-at-rest, signed OAuth state tokens, password hashing, and JWTs.

Uses Fernet (symmetric, authenticated) for encrypting OAuth access/refresh
tokens before they're stored in the database, and HMAC-signed, timestamped
tokens for the OAuth `state` parameter (avoids needing a server-side session
store for the short-lived OAuth handshake).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

settings = get_settings()

_STATE_TTL_SECONDS = 600  # OAuth handshake must complete within 10 minutes
_JWT_ALGORITHM = "HS256"


def _fernet() -> Fernet:
    key = settings.encryption_key
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Could not decrypt stored token; ENCRYPTION_KEY may have changed") from exc


def sign_state(payload: dict) -> str:
    """Create a signed, timestamped, URL-safe state token carrying `payload`."""
    body = dict(payload)
    body["_ts"] = int(time.time())
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(settings.secret_key.encode(), raw, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(raw).decode() + "." + base64.urlsafe_b64encode(sig).decode()
    return token


def verify_state(token: str) -> dict:
    """Verify and decode a state token created by `sign_state`. Raises ValueError if invalid/expired."""
    try:
        raw_b64, sig_b64 = token.split(".", 1)
        raw = base64.urlsafe_b64decode(raw_b64.encode())
        sig = base64.urlsafe_b64decode(sig_b64.encode())
    except (ValueError, TypeError) as exc:
        raise ValueError("Malformed state token") from exc

    expected_sig = hmac.new(settings.secret_key.encode(), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError("State token signature mismatch")

    payload = json.loads(raw)
    if time.time() - payload.get("_ts", 0) > _STATE_TTL_SECONDS:
        raise ValueError("State token expired")
    return payload


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), password_hash.encode())


def create_access_token(user_id: int) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {"sub": str(user_id), "exp": expires_at}
    return jwt.encode(payload, settings.secret_key, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> int:
    """Return the user id encoded in a valid, unexpired access token. Raises ValueError otherwise."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[_JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise ValueError("Invalid or expired access token") from exc
