from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_owned_social_account
from app.database import get_db
from app.models.post import Post
from app.models.social_account import SocialAccount
from app.scheduler.jobs import generate_and_post

router = APIRouter(prefix="/social-accounts/{social_account_id}/posts", tags=["posts"])


class PostResponse(BaseModel):
    id: int
    content: str
    status: str
    platform_post_id: str | None
    error_message: str | None

    class Config:
        from_attributes = True


@router.get("", response_model=list[PostResponse])
def list_posts(
    account: SocialAccount = Depends(get_owned_social_account), db: Session = Depends(get_db)
) -> list[Post]:
    return (
        db.query(Post)
        .filter(Post.social_account_id == account.id)
        .order_by(Post.created_at.desc())
        .limit(100)
        .all()
    )


@router.post("/generate-now", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
def generate_now(
    account: SocialAccount = Depends(get_owned_social_account), db: Session = Depends(get_db)
) -> Post:
    if account.niche is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Set a niche for this account first")

    generate_and_post(account.id)

    latest = (
        db.query(Post)
        .filter(Post.social_account_id == account.id)
        .order_by(Post.created_at.desc())
        .first()
    )
    if latest is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Post generation failed silently")
    return latest
