from datetime import datetime, timedelta, timezone

import pytest

import app.posting as posting
from app.content.generator import ContentGenerator
from app.core.security import encrypt_token
from app.database import SessionLocal
from app.models.niche import Niche
from app.models.post import Post, PostStatus
from app.models.schedule import PostSchedule
from app.models.social_account import SocialAccount
from app.models.user import User
from app.platforms.base import PostResult, SocialPlatform, TokenData


class FakePlatform(SocialPlatform):
    name = "fake"
    max_post_length = 3000

    def __init__(self, post_result: PostResult | None = None, refreshed_token_data: TokenData | None = None):
        self.post_result = post_result or PostResult(success=True, platform_post_id="fake-123")
        self.refreshed_token_data = refreshed_token_data
        self.post_content_calls: list[tuple] = []
        self.refresh_calls: list[str] = []

    def get_authorization_url(self, state, extras=None):
        return "https://example.invalid/authorize"

    def exchange_code(self, code, code_verifier=None):
        raise NotImplementedError

    def refresh_access_token(self, refresh_token):
        self.refresh_calls.append(refresh_token)
        if self.refreshed_token_data is None:
            raise RuntimeError("refresh failed")
        return self.refreshed_token_data

    def post_content(self, access_token, author_platform_user_id, text, image_url=None):
        self.post_content_calls.append((access_token, author_platform_user_id, text, image_url))
        return self.post_result


def _make_account(db, require_approval=False, token_expires_at=None, refresh_token=None) -> int:
    user = User(email=f"user-{datetime.now(timezone.utc).timestamp()}@example.com")
    db.add(user)
    db.flush()

    account = SocialAccount(
        user_id=user.id,
        platform="fake",
        platform_user_id="fake-user-id",
        access_token_encrypted=encrypt_token("initial-access-token"),
        refresh_token_encrypted=encrypt_token(refresh_token) if refresh_token else None,
        token_expires_at=token_expires_at,
        status="active",
    )
    db.add(account)
    db.flush()

    db.add(
        Niche(
            social_account_id=account.id,
            name="Test Niche",
            description="A niche for testing",
            content_pillars=[],
            keywords=[],
        )
    )
    db.add(
        PostSchedule(
            social_account_id=account.id, interval_hours=24, active=True, require_approval=require_approval
        )
    )
    db.commit()
    return account.id


@pytest.fixture(autouse=True)
def _fake_content_generator(monkeypatch):
    monkeypatch.setattr(
        ContentGenerator,
        "generate_post",
        lambda self, niche, recent_posts, max_length=3000: "Generated post content",
    )


@pytest.fixture
def fake_platform(monkeypatch):
    platform = FakePlatform()
    monkeypatch.setattr(posting, "get_platform", lambda name: platform)
    return platform


def test_generate_and_post_publishes_immediately_when_no_approval_required(fake_platform):
    db = SessionLocal()
    account_id = _make_account(db, require_approval=False)
    db.close()

    post_id = posting.generate_and_post(account_id)
    assert post_id is not None
    assert len(fake_platform.post_content_calls) == 1

    db = SessionLocal()
    post = db.get(Post, post_id)
    assert post.status == PostStatus.posted.value
    assert post.platform_post_id == "fake-123"
    db.close()


def test_generate_and_post_holds_for_approval(fake_platform):
    db = SessionLocal()
    account_id = _make_account(db, require_approval=True)
    db.close()

    post_id = posting.generate_and_post(account_id)
    assert fake_platform.post_content_calls == []  # never published up front

    db = SessionLocal()
    post = db.get(Post, post_id)
    assert post.status == PostStatus.pending_approval.value
    db.close()

    published_id = posting.publish_pending_post(post_id)
    assert len(fake_platform.post_content_calls) == 1

    db = SessionLocal()
    post = db.get(Post, published_id)
    assert post.status == PostStatus.posted.value
    db.close()


def test_reject_pending_post(fake_platform):
    db = SessionLocal()
    account_id = _make_account(db, require_approval=True)
    db.close()

    post_id = posting.generate_and_post(account_id)
    rejected_id = posting.reject_pending_post(post_id)

    db = SessionLocal()
    post = db.get(Post, rejected_id)
    assert post.status == PostStatus.rejected.value
    db.close()
    assert fake_platform.post_content_calls == []


def test_approve_only_works_on_pending_posts(fake_platform):
    db = SessionLocal()
    account_id = _make_account(db, require_approval=False)  # publishes immediately
    db.close()

    post_id = posting.generate_and_post(account_id)  # already posted, not pending
    with pytest.raises(ValueError):
        posting.publish_pending_post(post_id)


def test_expired_token_triggers_refresh_before_posting(fake_platform):
    fake_platform.refreshed_token_data = TokenData(
        access_token="refreshed-access-token",
        refresh_token="new-refresh-token",
        expires_in_seconds=3600,
        platform_user_id="fake-user-id",
    )

    db = SessionLocal()
    account_id = _make_account(
        db,
        require_approval=False,
        token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        refresh_token="old-refresh-token",
    )
    db.close()

    post_id = posting.generate_and_post(account_id)
    assert len(fake_platform.refresh_calls) == 1
    assert fake_platform.post_content_calls[0][0] == "refreshed-access-token"

    db = SessionLocal()
    post = db.get(Post, post_id)
    assert post.status == PostStatus.posted.value
    account = db.get(SocialAccount, account_id)
    assert account.status == "active"
    db.close()


def test_needs_reauth_when_refresh_fails(fake_platform):
    fake_platform.refreshed_token_data = None  # refresh_access_token raises

    db = SessionLocal()
    account_id = _make_account(
        db,
        require_approval=False,
        token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        refresh_token="old-refresh-token",
    )
    db.close()

    post_id = posting.generate_and_post(account_id)
    assert fake_platform.post_content_calls == []

    db = SessionLocal()
    account = db.get(SocialAccount, account_id)
    assert account.status == "needs_reauth"
    post = db.get(Post, post_id)
    assert post.status == PostStatus.failed.value
    db.close()


def test_transient_platform_error_is_raised_for_retryable_failures(fake_platform):
    fake_platform.post_result = PostResult(success=False, error_message="503", is_transient_error=True)

    db = SessionLocal()
    account_id = _make_account(db, require_approval=False)
    db.close()

    with pytest.raises(posting.TransientPlatformError):
        posting.generate_and_post(account_id)

    # The failed attempt is still recorded even though we raised for retry.
    db = SessionLocal()
    latest = db.query(Post).filter(Post.social_account_id == account_id).order_by(Post.id.desc()).first()
    assert latest.status == PostStatus.failed.value
    db.close()
