"""Account login (email+password -> JWT) and the social platform OAuth connect flow.

OAuth connect flow (works the same for every registered platform):
  1. Client calls GET /auth/{platform}/authorize (authenticated) -> gets a URL.
  2. Client sends the end user's browser to that URL; they approve access.
  3. The platform redirects the browser to /auth/{platform}/callback, which has
     no auth header (it's a browser redirect), so identity -- and, for
     platforms using PKCE, the code_verifier -- travels in the signed `state`
     parameter instead.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import (
    create_access_token,
    encrypt_token,
    hash_password,
    sign_state,
    verify_password,
    verify_state,
)
from app.database import get_db
from app.models.social_account import SocialAccount
from app.models.user import User
from app.platforms.registry import get_platform, known_platform_names

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if len(payload.password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    return TokenResponse(access_token=create_access_token(user.id))


def _get_platform_or_404(platform_name: str):
    if platform_name not in known_platform_names():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown platform {platform_name!r}. Known platforms: {known_platform_names()}",
        )
    return get_platform(platform_name)


@router.get("/{platform_name}/authorize")
def authorize(platform_name: str, user: User = Depends(get_current_user)) -> dict:
    platform = _get_platform_or_404(platform_name)
    extras = platform.generate_state_extras()
    state = sign_state({"user_id": user.id, "platform": platform_name, **extras})
    return {"authorization_url": platform.get_authorization_url(state, extras)}


@router.get("/{platform_name}/callback")
def callback(platform_name: str, code: str, state: str, db: Session = Depends(get_db)) -> dict:
    platform = _get_platform_or_404(platform_name)

    try:
        payload = verify_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if payload.get("platform") != platform_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State token does not match platform")

    user = db.get(User, payload["user_id"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    token_data = platform.exchange_code(code, code_verifier=payload.get("code_verifier"))

    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.user_id == user.id,
            SocialAccount.platform == platform_name,
            SocialAccount.platform_user_id == token_data.platform_user_id,
        )
        .first()
    )
    if account is None:
        account = SocialAccount(user_id=user.id, platform=platform_name, platform_user_id=token_data.platform_user_id)
        db.add(account)

    account.display_name = token_data.display_name
    account.access_token_encrypted = encrypt_token(token_data.access_token)
    account.refresh_token_encrypted = (
        encrypt_token(token_data.refresh_token) if token_data.refresh_token else None
    )
    account.token_expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=token_data.expires_in_seconds)
        if token_data.expires_in_seconds
        else None
    )
    account.status = "active"
    db.commit()
    db.refresh(account)

    return {
        "social_account_id": account.id,
        "platform": account.platform,
        "display_name": account.display_name,
        "message": f"{platform_name} account connected. Next: set a niche and a posting schedule for this account.",
    }
