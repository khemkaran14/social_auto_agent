from fastapi import Depends, HTTPException, Header, status
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database import get_db
from app.models.social_account import SocialAccount
from app.models.user import User


def get_current_user(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Authenticates via either `X-API-Key: <key>` or `Authorization: Bearer <jwt>`."""
    if x_api_key:
        user = db.query(User).filter(User.api_key == x_api_key).first()
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        return user

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        try:
            user_id = decode_access_token(token)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Provide either an X-API-Key header or an Authorization: Bearer <token> header",
    )


def get_owned_social_account(
    social_account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SocialAccount:
    account = db.get(SocialAccount, social_account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Social account not found")
    return account
