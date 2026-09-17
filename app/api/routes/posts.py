from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_owned_social_account
from app.database import get_db
from app.models.post import Post, PostStatus
from app.models.social_account import SocialAccount
from app.posting import generate_and_post, publish_pending_post, reject_pending_post

router = APIRouter(prefix="/social-accounts/{social_account_id}/posts", tags=["posts"])


class PostResponse(BaseModel):
    id: int
    content: str
    status: str
    image_url: str | None
    platform_post_id: str | None
    error_message: str | None

    class Config:
        from_attributes = True


def _get_owned_post(account: SocialAccount, post_id: int, db: Session) -> Post:
    post = db.get(Post, post_id)
    if post is None or post.social_account_id != account.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return post


@router.get("", response_model=list[PostResponse])
def list_posts(
    account: SocialAccount = Depends(get_owned_social_account),
    db: Session = Depends(get_db),
    status_filter: PostStatus | None = None,
) -> list[Post]:
    query = db.query(Post).filter(Post.social_account_id == account.id)
    if status_filter is not None:
        query = query.filter(Post.status == status_filter.value)
    return query.order_by(Post.created_at.desc()).limit(100).all()


@router.post("/generate-now", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
def generate_now(
    account: SocialAccount = Depends(get_owned_social_account), db: Session = Depends(get_db)
) -> Post:
    if account.niche is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Set a niche for this account first")
    if account.schedule is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Set a schedule for this account first")

    post_id = generate_and_post(account.id)
    if post_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nothing generated -- check the account is active and its schedule is active",
        )
    return _get_owned_post(account, post_id, db)


@router.post("/{post_id}/approve", response_model=PostResponse)
def approve_post(
    post_id: int, account: SocialAccount = Depends(get_owned_social_account), db: Session = Depends(get_db)
) -> Post:
    _get_owned_post(account, post_id, db)  # 404s if not ours before we touch it
    try:
        published_id = publish_pending_post(post_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _get_owned_post(account, published_id, db)


@router.post("/{post_id}/reject", response_model=PostResponse)
def reject_post(
    post_id: int, account: SocialAccount = Depends(get_owned_social_account), db: Session = Depends(get_db)
) -> Post:
    _get_owned_post(account, post_id, db)
    try:
        rejected_id = reject_pending_post(post_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _get_owned_post(account, rejected_id, db)
