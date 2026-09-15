from fastapi import Depends, HTTPException, Header, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.social_account import SocialAccount
from app.models.user import User


def get_current_user(
    x_api_key: str = Header(..., description="API key issued when the user was created"),
    db: Session = Depends(get_db),
) -> User:
    user = db.query(User).filter(User.api_key == x_api_key).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return user


def get_owned_social_account(
    social_account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SocialAccount:
    account = db.get(SocialAccount, social_account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Social account not found")
    return account
