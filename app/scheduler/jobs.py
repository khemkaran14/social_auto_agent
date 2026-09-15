"""The actual "generate content and post it" job that runs on a schedule."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.content.generator import ContentGenerator
from app.core.security import decrypt_token
from app.database import SessionLocal
from app.models.post import Post, PostStatus
from app.models.social_account import SocialAccount
from app.platforms.registry import get_platform

logger = logging.getLogger(__name__)


def generate_and_post(social_account_id: int) -> None:
    db = SessionLocal()
    try:
        account = db.get(SocialAccount, social_account_id)
        if account is None or account.status != "active":
            logger.info("Skipping social_account_id=%s: inactive or missing", social_account_id)
            return

        niche = account.niche
        if niche is None:
            logger.warning("Skipping social_account_id=%s: no niche configured", social_account_id)
            return

        schedule = account.schedule
        if schedule is None or not schedule.active:
            logger.info("Skipping social_account_id=%s: schedule missing or inactive", social_account_id)
            return

        recent_posts = [
            p.content
            for p in sorted(account.posts, key=lambda p: p.created_at, reverse=True)
            if p.status == PostStatus.posted.value
        ][:10]

        platform = get_platform(account.platform)
        generator = ContentGenerator()
        content = generator.generate_post(niche, recent_posts, max_length=platform.max_post_length)

        access_token = decrypt_token(account.access_token_encrypted)
        result = platform.post_content(access_token, account.platform_user_id, content)

        post = Post(
            social_account_id=account.id,
            niche_id=niche.id,
            content=content,
            status=PostStatus.posted.value if result.success else PostStatus.failed.value,
            platform_post_id=result.platform_post_id,
            error_message=result.error_message,
            posted_at=datetime.now(timezone.utc) if result.success else None,
        )
        db.add(post)

        schedule.last_run_at = datetime.now(timezone.utc)
        db.commit()

        if result.success:
            logger.info("Posted to social_account_id=%s (platform_post_id=%s)", account.id, result.platform_post_id)
        else:
            logger.error("Failed to post to social_account_id=%s: %s", account.id, result.error_message)
    finally:
        db.close()
