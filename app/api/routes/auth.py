"""LinkedIn OAuth connect flow.

Flow:
  1. Client calls GET /auth/linkedin/authorize (with X-API-Key) -> gets a URL.
  2. Client sends the end user's browser to that URL; they approve access.
  3. LinkedIn redirects the browser to /auth/linkedin/callback, which has no
     auth header (it's a browser redirect), so identity travels in the
     signed `state` parameter instead.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import encrypt_token, sign_state, verify_state
from app.database import get_db
from app.models.social_account import SocialAccount
from app.models.user import User
from app.platforms.registry import get_platform

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/linkedin/authorize")
def linkedin_authorize(user: User = Depends(get_current_user)) -> dict:
    platform = get_platform("linkedin")
    state = sign_state({"user_id": user.id, "platform": "linkedin"})
    return {"authorization_url": platform.get_authorization_url(state)}


@router.get("/linkedin/callback")
def linkedin_callback(code: str, state: str, db: Session = Depends(get_db)) -> dict:
    try:
        payload = verify_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    user = db.get(User, payload["user_id"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    platform = get_platform("linkedin")
    token_data = platform.exchange_code(code)

    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.user_id == user.id,
            SocialAccount.platform == "linkedin",
            SocialAccount.platform_user_id == token_data.platform_user_id,
        )
        .first()
    )
    if account is None:
        account = SocialAccount(user_id=user.id, platform="linkedin", platform_user_id=token_data.platform_user_id)
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
        "message": "LinkedIn account connected. Next: set a niche and a posting schedule for this account.",
    }
