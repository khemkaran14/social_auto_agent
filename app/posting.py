"""Core "generate content and publish it" logic, shared by the Celery task
and the synchronous /generate-now and /approve API endpoints.

Every function here opens and closes its own DB session and returns plain
IDs rather than ORM objects, so callers (which may hold a different session,
e.g. a FastAPI request's) always re-fetch fresh, session-bound rows instead
of touching a detached instance from a session that's already closed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.content.generator import ContentGenerator
from app.core.security import decrypt_token, encrypt_token
from app.database import SessionLocal
from app.models.post import Post, PostStatus
from app.models.social_account import SocialAccount
from app.platforms.base import SocialPlatform
from app.platforms.registry import get_platform

logger = logging.getLogger(__name__)

_TOKEN_REFRESH_BUFFER = timedelta(minutes=5)


class TransientPlatformError(Exception):
    """Raised after a failed attempt is recorded, to tell the Celery task layer
    the failure is worth retrying (rate limit, 5xx, network blip)."""


def _ensure_fresh_access_token(db: Session, account: SocialAccount, platform: SocialPlatform) -> str | None:
    """Returns a usable access token, refreshing it first if it's near expiry.
    Marks the account as needing re-authorization (and returns None) if no
    refresh token is available or the refresh attempt fails."""
    now = datetime.now(timezone.utc)
    expires_at = account.token_expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        # SQLite (used in tests) doesn't preserve tzinfo on round-trip; Postgres does.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at is None or expires_at - _TOKEN_REFRESH_BUFFER > now:
        return decrypt_token(account.access_token_encrypted)

    if not account.refresh_token_encrypted:
        logger.warning("social_account_id=%s token expired and has no refresh token", account.id)
        account.status = "needs_reauth"
        db.commit()
        return None

    try:
        refresh_token = decrypt_token(account.refresh_token_encrypted)
        token_data = platform.refresh_access_token(refresh_token)
    except Exception as exc:  # noqa: BLE001 -- any refresh failure means the same thing: re-auth needed
        logger.warning("Token refresh failed for social_account_id=%s: %s", account.id, exc)
        account.status = "needs_reauth"
        db.commit()
        return None

    account.access_token_encrypted = encrypt_token(token_data.access_token)
    if token_data.refresh_token:
        account.refresh_token_encrypted = encrypt_token(token_data.refresh_token)
    account.token_expires_at = (
        now + timedelta(seconds=token_data.expires_in_seconds) if token_data.expires_in_seconds else None
    )
    db.commit()
    return token_data.access_token


def generate_and_post(social_account_id: int) -> int | None:
    """Generates one on-niche post and either publishes it immediately or, if
    the account's schedule requires approval, saves it as pending_approval.
    Returns the created Post's id, or None if nothing was generated (account
    inactive/misconfigured -- not an error, just nothing to do)."""
    db = SessionLocal()
    try:
        account = db.get(SocialAccount, social_account_id)
        if account is None or account.status != "active":
            logger.info("Skipping social_account_id=%s: inactive or missing", social_account_id)
            return None

        niche = account.niche
        if niche is None:
            logger.warning("Skipping social_account_id=%s: no niche configured", social_account_id)
            return None

        schedule = account.schedule
        if schedule is None or not schedule.active:
            logger.info("Skipping social_account_id=%s: schedule missing or inactive", social_account_id)
            return None

        platform = get_platform(account.platform)

        access_token = _ensure_fresh_access_token(db, account, platform)
        if access_token is None:
            post = Post(
                social_account_id=account.id,
                niche_id=niche.id,
                content="",
                status=PostStatus.failed.value,
                error_message="Account needs re-authorization (token expired/refresh failed).",
            )
            db.add(post)
            db.commit()
            return post.id

        recent_posts = [
            p.content
            for p in sorted(account.posts, key=lambda p: p.created_at, reverse=True)
            if p.status == PostStatus.posted.value
        ][:10]

        try:
            content = ContentGenerator().generate_post(niche, recent_posts, max_length=platform.max_post_length)
        except Exception as exc:  # noqa: BLE001 -- Anthropic/network errors, all recorded the same way
            logger.error("Content generation failed for social_account_id=%s: %s", account.id, exc)
            post = Post(
                social_account_id=account.id,
                niche_id=niche.id,
                content="",
                status=PostStatus.failed.value,
                error_message=f"Content generation failed: {exc}",
            )
            db.add(post)
            schedule.last_run_at = datetime.now(timezone.utc)
            db.commit()
            return post.id

        if schedule.require_approval:
            post = Post(
                social_account_id=account.id,
                niche_id=niche.id,
                content=content,
                image_url=niche.default_image_url,
                status=PostStatus.pending_approval.value,
            )
            db.add(post)
            schedule.last_run_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("social_account_id=%s: post %s awaiting approval", account.id, post.id)
            return post.id

        result = platform.post_content(access_token, account.platform_user_id, content, image_url=niche.default_image_url)

        post = Post(
            social_account_id=account.id,
            niche_id=niche.id,
            content=content,
            image_url=niche.default_image_url,
            status=PostStatus.posted.value if result.success else PostStatus.failed.value,
            platform_post_id=result.platform_post_id,
            error_message=result.error_message,
            posted_at=datetime.now(timezone.utc) if result.success else None,
        )
        db.add(post)
        schedule.last_run_at = datetime.now(timezone.utc)
        db.commit()
        post_id = post.id

        if result.success:
            logger.info("Posted to social_account_id=%s (platform_post_id=%s)", account.id, result.platform_post_id)
        else:
            logger.error("Failed to post to social_account_id=%s: %s", account.id, result.error_message)
            if result.is_transient_error:
                raise TransientPlatformError(result.error_message)

        return post_id
    finally:
        db.close()


def publish_pending_post(post_id: int) -> int:
    """Publishes a post that was held for approval. Raises ValueError if the
    post doesn't exist or isn't pending approval."""
    db = SessionLocal()
    try:
        post = db.get(Post, post_id)
        if post is None or post.status != PostStatus.pending_approval.value:
            raise ValueError("Post not found or not pending approval")

        account = post.social_account
        platform = get_platform(account.platform)

        access_token = _ensure_fresh_access_token(db, account, platform)
        if access_token is None:
            post.status = PostStatus.failed.value
            post.error_message = "Account needs re-authorization (token expired/refresh failed)."
            db.commit()
            return post.id

        result = platform.post_content(access_token, account.platform_user_id, post.content, image_url=post.image_url)
        post.status = PostStatus.posted.value if result.success else PostStatus.failed.value
        post.platform_post_id = result.platform_post_id
        post.error_message = result.error_message
        post.posted_at = datetime.now(timezone.utc) if result.success else None
        db.commit()
        post_id_result = post.id

        if not result.success and result.is_transient_error:
            raise TransientPlatformError(result.error_message)
        return post_id_result
    finally:
        db.close()


def reject_pending_post(post_id: int) -> int:
    db = SessionLocal()
    try:
        post = db.get(Post, post_id)
        if post is None or post.status != PostStatus.pending_approval.value:
            raise ValueError("Post not found or not pending approval")
        post.status = PostStatus.rejected.value
        db.commit()
        return post.id
    finally:
        db.close()
