"""Facebook Page and Instagram (Business/Creator) posting via Meta's official Graph API.

Both use a Page access token. A Page token made from a long-lived user token
does not expire, so it can sit in a GitHub secret and be used by the campaign
runner (`campaign/publish.py`) without any OAuth round trip. The same Page
token also publishes to the Instagram account linked to that Page.

These classes are not in `registry.py`, because the web app's
`/auth/{platform}` flow does not support Meta login yet. The campaign runner
uses them directly.

Docs:
  https://developers.facebook.com/docs/pages-api/posts
  https://developers.facebook.com/docs/instagram-platform/content-publishing
"""

from __future__ import annotations

import time

import httpx

from app.config import get_settings
from app.platforms.base import PostResult, SocialPlatform, TokenData

GRAPH_HOST = "https://graph.facebook.com"


def _graph_url(path: str) -> str:
    return f"{GRAPH_HOST}/{get_settings().meta_graph_version}/{path.lstrip('/')}"


def _result_from_error(resp: httpx.Response, label: str) -> PostResult:
    transient = resp.status_code >= 500 or resp.status_code == 429
    try:
        err = resp.json().get("error", {})
        # Meta rate-limit and "temporarily unavailable" codes.
        if err.get("code") in (1, 2, 4, 17, 32, 341, 613) or err.get("is_transient"):
            transient = True
        message = f"{label} {resp.status_code}: {err.get('message') or resp.text[:500]}"
    except ValueError:
        message = f"{label} {resp.status_code}: {resp.text[:500]}"
    return PostResult(success=False, error_message=message, is_transient_error=transient)


class _MetaTokenOnly(SocialPlatform):
    def get_authorization_url(self, state: str, extras: dict | None = None) -> str:
        raise NotImplementedError(f"{self.name}: use a Page access token (see campaign/SETUP.md)")

    def exchange_code(self, code: str, code_verifier: str | None = None) -> TokenData:
        raise NotImplementedError(f"{self.name}: use a Page access token (see campaign/SETUP.md)")


class FacebookPagePlatform(_MetaTokenOnly):
    name = "facebook"
    max_post_length = 63206
    supports_media = True

    def post_content(
        self, access_token: str, author_platform_user_id: str, text: str, image_url: str | None = None
    ) -> PostResult:
        page_id = author_platform_user_id
        try:
            with httpx.Client(timeout=30.0) as client:
                if image_url:
                    resp = client.post(
                        _graph_url(f"{page_id}/photos"),
                        data={"url": image_url, "caption": text[: self.max_post_length], "access_token": access_token},
                    )
                else:
                    resp = client.post(
                        _graph_url(f"{page_id}/feed"),
                        data={"message": text[: self.max_post_length], "access_token": access_token},
                    )
            if resp.status_code >= 400:
                return _result_from_error(resp, "Facebook API")
            body = resp.json()
            return PostResult(success=True, platform_post_id=body.get("post_id") or body.get("id"))
        except httpx.HTTPError as exc:
            return PostResult(success=False, error_message=str(exc), is_transient_error=True)


class InstagramPlatform(_MetaTokenOnly):
    name = "instagram"
    max_post_length = 2200
    supports_media = True

    # How long to wait for Instagram to finish processing an uploaded image.
    poll_attempts = 10
    poll_seconds = 3.0

    def post_content(
        self, access_token: str, author_platform_user_id: str, text: str, image_url: str | None = None
    ) -> PostResult:
        if not image_url:
            return PostResult(success=False, error_message="Instagram posts need an image")
        ig_user_id = author_platform_user_id
        try:
            with httpx.Client(timeout=30.0) as client:
                create = client.post(
                    _graph_url(f"{ig_user_id}/media"),
                    data={"image_url": image_url, "caption": text[: self.max_post_length], "access_token": access_token},
                )
                if create.status_code >= 400:
                    return _result_from_error(create, "Instagram API")
                container_id = create.json()["id"]

                for _ in range(self.poll_attempts):
                    status = client.get(
                        _graph_url(container_id), params={"fields": "status_code", "access_token": access_token}
                    )
                    if status.status_code >= 400:
                        return _result_from_error(status, "Instagram API")
                    code = status.json().get("status_code")
                    if code == "FINISHED":
                        break
                    if code in ("ERROR", "EXPIRED"):
                        return PostResult(success=False, error_message=f"Instagram could not process the image ({code})")
                    time.sleep(self.poll_seconds)
                else:
                    return PostResult(
                        success=False, error_message="Instagram image still processing", is_transient_error=True
                    )

                publish = client.post(
                    _graph_url(f"{ig_user_id}/media_publish"),
                    data={"creation_id": container_id, "access_token": access_token},
                )
                if publish.status_code >= 400:
                    return _result_from_error(publish, "Instagram API")
                return PostResult(success=True, platform_post_id=publish.json().get("id"))
        except httpx.HTTPError as exc:
            return PostResult(success=False, error_message=str(exc), is_transient_error=True)
