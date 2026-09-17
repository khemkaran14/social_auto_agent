"""Test-session setup: point the app at a throwaway SQLite DB before any
`app.*` module is imported, so `app.database`'s module-level engine binds to
it instead of the real Postgres URL."""

import os
from pathlib import Path

_TEST_DB_PATH = Path(__file__).parent / "test.db"
_TEST_DB_PATH.unlink(missing_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
os.environ["SECRET_KEY"] = "test-secret-key"

from cryptography.fernet import Fernet  # noqa: E402

os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

import app.models  # noqa: E402,F401 -- registers every model on Base.metadata
from app.database import Base, engine  # noqa: E402

Base.metadata.create_all(bind=engine)
