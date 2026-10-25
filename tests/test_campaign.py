from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import yaml

from app.platforms.base import PostResult, SocialPlatform
from app.platforms.meta import FacebookPagePlatform, InstagramPlatform
from campaign import publish

IST = ZoneInfo("Asia/Kolkata")


def _setup(tmp_path: Path, posts: list[dict]) -> Path:
    camp = tmp_path / "campaign"
    (camp / "queue").mkdir(parents=True)
    (camp / "settings.yaml").write_text("timezone: Asia/Kolkata\nmax_attempts: 2\nmax_late_hours: 24\n")
    (camp / "brands.yaml").write_text(
        yaml.safe_dump(
            {
                "accounts": [
                    {"id": "fb", "brand": "b", "platform": "facebook", "token_secret": "TOK", "target_secret": "PAGE"},
                    {
                        "id": "li",
                        "brand": "b",
                        "platform": "linkedin",
                        "token_secret": "LTOK",
                        "target_secret": "ORG",
                        "target_format": "urn:li:organization:{id}",
                    },
                ]
            }
        )
    )
    (camp / "queue" / "w.yaml").write_text(yaml.safe_dump({"posts": posts}))
    return camp


def _post(pid="p1", account="fb", when="2026-10-27 19:00", status="approved", **extra):
    return {"id": pid, "account": account, "publish_at": when, "text": "hello", "status": status, **extra}


class FakePlatform(SocialPlatform):
    name = "fake"
    calls: list = []
    result = PostResult(success=True, platform_post_id="123")

    def get_authorization_url(self, state, extras=None):
        return ""

    def exchange_code(self, code, code_verifier=None):
        raise NotImplementedError

    def post_content(self, access_token, author_platform_user_id, text, image_url=None):
        FakePlatform.calls.append((access_token, author_platform_user_id, text, image_url))
        return FakePlatform.result


def _run(camp, now, secrets=None):
    FakePlatform.calls = []
    return publish.publish_due(
        now=now,
        campaign_dir=camp,
        repo_root=camp.parent,
        secrets={"TOK": "t", "PAGE": "42", "LTOK": "lt", "ORG": "9"} if secrets is None else secrets,
        platforms={"facebook": FakePlatform, "linkedin": FakePlatform},
    )


def _posts(camp):
    return yaml.safe_load((camp / "queue" / "w.yaml").read_text())["posts"]


def test_posts_only_due_approved_posts(tmp_path):
    FakePlatform.result = PostResult(success=True, platform_post_id="123")
    camp = _setup(
        tmp_path,
        [_post("due"), _post("later", when="2026-10-28 19:00"), _post("draft", status="draft")],
    )
    report = _run(camp, datetime(2026, 10, 27, 19, 5, tzinfo=IST))

    assert [c[1] for c in FakePlatform.calls] == ["42"]
    posts = {p["id"]: p for p in _posts(camp)}
    assert posts["due"]["status"] == "posted"
    assert posts["due"]["platform_post_id"] == "123"
    assert posts["later"]["status"] == "approved"
    assert posts["draft"]["status"] == "draft"
    assert any(line.startswith("POSTED due") for line in report)


def test_linkedin_target_is_formatted_as_organization_urn(tmp_path):
    FakePlatform.result = PostResult(success=True, platform_post_id="x")
    camp = _setup(tmp_path, [_post(account="li")])
    _run(camp, datetime(2026, 10, 27, 20, 0, tzinfo=IST))
    assert FakePlatform.calls[0][1] == "urn:li:organization:9"


def test_missing_secret_waits_then_goes_missed(tmp_path):
    camp = _setup(tmp_path, [_post()])
    report = _run(camp, datetime(2026, 10, 27, 20, 0, tzinfo=IST), secrets={})
    assert FakePlatform.calls == []
    assert _posts(camp)[0]["status"] == "approved"
    assert "TOK" in report[0]

    _run(camp, datetime(2026, 10, 29, 20, 0, tzinfo=IST), secrets={})
    assert _posts(camp)[0]["status"] == "missed"


def test_transient_failure_retries_then_fails(tmp_path):
    FakePlatform.result = PostResult(success=False, error_message="429", is_transient_error=True)
    camp = _setup(tmp_path, [_post()])
    now = datetime(2026, 10, 27, 19, 30, tzinfo=IST)
    _run(camp, now)
    assert _posts(camp)[0]["status"] == "approved"
    _run(camp, now)
    post = _posts(camp)[0]
    assert post["status"] == "failed"
    assert post["attempts"] == 2


def test_permanent_failure_fails_immediately(tmp_path):
    FakePlatform.result = PostResult(success=False, error_message="bad token")
    camp = _setup(tmp_path, [_post()])
    _run(camp, datetime(2026, 10, 27, 19, 30, tzinfo=IST))
    assert _posts(camp)[0]["status"] == "failed"


def test_dry_run_changes_nothing(tmp_path):
    camp = _setup(tmp_path, [_post()])
    before = (camp / "queue" / "w.yaml").read_text()
    report = publish.publish_due(
        now=datetime(2026, 10, 27, 19, 30, tzinfo=IST),
        dry_run=True,
        campaign_dir=camp,
        repo_root=camp.parent,
        secrets={"TOK": "t", "PAGE": "42"},
        platforms={"facebook": FakePlatform},
    )
    assert report == ["WOULD POST p1 to fb"]
    assert (camp / "queue" / "w.yaml").read_text() == before


def test_validate_catches_common_mistakes(tmp_path):
    camp = _setup(
        tmp_path,
        [
            _post("a"),
            _post("a"),
            _post("b", account="nope"),
            _post("c", when="tomorrow"),
            _post("d", image="campaign/images/missing.png"),
        ],
    )
    problems = "\n".join(publish.validate(camp, camp.parent))
    assert "duplicate id" in problems
    assert "unknown account" in problems
    assert "publish_at" in problems
    assert "not found" in problems


def test_real_queue_is_valid():
    assert publish.validate() == []


def test_image_url_uses_commit_sha(monkeypatch):
    monkeypatch.delenv("CAMPAIGN_IMAGE_BASE_URL", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/repo")
    monkeypatch.setenv("GITHUB_SHA", "abc")
    assert publish.image_public_url("campaign/images/x.png") == (
        "https://raw.githubusercontent.com/me/repo/abc/campaign/images/x.png"
    )


# --- Meta platform request shapes ------------------------------------------------


def _mock_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr("app.platforms.meta.httpx.Client", factory)


def test_facebook_photo_post(monkeypatch):
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"id": "ph", "post_id": "page_post"})

    _mock_client(monkeypatch, handler)
    result = FacebookPagePlatform().post_content("tok", "42", "hi", "https://img/x.png")
    assert result.success and result.platform_post_id == "page_post"
    assert seen[0].url.path.endswith("/42/photos")
    assert b"caption=hi" in seen[0].content


def test_facebook_text_post_and_rate_limit(monkeypatch):
    _mock_client(monkeypatch, lambda req: httpx.Response(400, json={"error": {"code": 4, "message": "slow down"}}))
    result = FacebookPagePlatform().post_content("tok", "42", "hi")
    assert not result.success and result.is_transient_error


def test_instagram_requires_image():
    assert not InstagramPlatform().post_content("tok", "1", "hi").success


def test_instagram_create_poll_publish(monkeypatch):
    paths = []

    def handler(req):
        paths.append(req.url.path)
        if req.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "c1"})
        if req.url.path.endswith("/c1"):
            return httpx.Response(200, json={"status_code": "FINISHED"})
        return httpx.Response(200, json={"id": "m1"})

    _mock_client(monkeypatch, handler)
    result = InstagramPlatform().post_content("tok", "17", "hi", "https://img/x.png")
    assert result.success and result.platform_post_id == "m1"
    assert [p.rsplit("/", 1)[-1] for p in paths] == ["media", "c1", "media_publish"]
