from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_owned_social_account
from app.database import get_db
from app.models.social_account import SocialAccount
from app.models.user import User

router = APIRouter(prefix="/social-accounts", tags=["social-accounts"])


class SocialAccountResponse(BaseModel):
    id: int
    platform: str
    display_name: str | None
    status: str

    class Config:
        from_attributes = True


@router.get("", response_model=list[SocialAccountResponse])
def list_social_accounts(user: User = Depends(get_current_user)) -> list[SocialAccount]:
    return user.social_accounts


@router.get("/{social_account_id}", response_model=SocialAccountResponse)
def get_social_account(account: SocialAccount = Depends(get_owned_social_account)) -> SocialAccount:
    return account


@router.delete("/{social_account_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_social_account(
    account: SocialAccount = Depends(get_owned_social_account), db: Session = Depends(get_db)
) -> None:
    account.status = "revoked"
    db.commit()
    # No job to explicitly cancel: the Celery beat dispatcher only picks up
    # schedules on accounts with status == "active", so this alone stops it.
