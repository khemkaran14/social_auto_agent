"""Twitter/X integration using the official OAuth 2.0 (PKCE) + API v2.

Requires a Twitter/X developer app with OAuth 2.0 enabled as a confidential
client, and these scopes: tweet.read tweet.write users.read offline.access
(offline.access is what makes Twitter issue a refresh token) plus
media.write if you want image attachments to work.

PKCE note: the `code_verifier` is generated per authorization attempt and
must survive the round trip to Twitter and back. Rather than a server-side
session store, it's embedded in the signed OAuth `state` token (see
`generate_state_extras` / `app.core.security.sign_state`), so any API
instance can complete the callback.

Docs:
  https://developer.x.com/en/docs/authentication/oauth-2-0/user-access-token
  https://developer.x.com/en/docs/x-api/tweets/manage-tweets/api-reference/post-tweets
  https://developer.x.com/en/docs/x-api/v1/media/upload-media/api-reference/post-media-upload
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.platforms.base import PostResult, SocialPlatform, TokenData

settings = get_settings()

AUTHORIZATION_URL = "https://twitter.com/i/oauth2/authorize"
TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
USERINFO_URL = "https://api.twitter.com/2/users/me"
TWEETS_URL = "https://api.twitter.com/2/tweets"
MEDIA_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"

SCOPES = "tweet.read tweet.write users.read offline.access media.write"


def _basic_auth_header() -> dict:
    credentials = f"{settings.twitter_client_id}:{settings.twitter_client_secret}".encode()
    return {"Authorization": f"Basic {base64.b64encode(credentials).decode()}"}


def _code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


class TwitterPlatform(SocialPlatform):
    name = "twitter"
    max_post_length = 280
    supports_media = True

    def generate_state_extras(self) -> dict:
        return {"code_verifier": secrets.token_urlsafe(64)}

    def get_authorization_url(self, state: str, extras: dict | None = None) -> str:
        extras = extras or {}
        code_verifier = extras.get("code_verifier")
        if not code_verifier:
            raise ValueError("Twitter authorization requires a code_verifier (see generate_state_extras)")

        params = {
            "response_type": "code",
            "client_id": settings.twitter_client_id,
            "redirect_uri": settings.twitter_redirect_uri,
            "state": state,
            "scope": SCOPES,
            "code_challenge": _code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        return f"{AUTHORIZATION_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str | None = None) -> TokenData:
        if not code_verifier:
            raise ValueError("Twitter token exchange requires the original code_verifier")

        with httpx.Client(timeout=15.0) as client:
            token_resp = client.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.twitter_redirect_uri,
                    "client_id": settings.twitter_client_id,
                    "code_verifier": code_verifier,
                },
                headers={**_basic_auth_header(), "Content-Type": "application/x-www-form-urlencoded"},
            )
            token_resp.raise_for_status()
            token_json = token_resp.json()
            access_token = token_json["access_token"]

            profile_resp = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
            profile_resp.raise_for_status()
            profile = profile_resp.json()["data"]

        return TokenData(
            access_token=access_token,
            refresh_token=token_json.get("refresh_token"),
            expires_in_seconds=token_json.get("expires_in"),
            platform_user_id=profile["id"],
            display_name=profile.get("username"),
        )

    def refresh_access_token(self, refresh_token: str) -> TokenData:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": settings.twitter_client_id,
                },
                headers={**_basic_auth_header(), "Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            token_json = resp.json()
            access_token = token_json["access_token"]

            profile_resp = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
            profile_resp.raise_for_status()
            profile = profile_resp.json()["data"]

        return TokenData(
            access_token=access_token,
            refresh_token=token_json.get("refresh_token", refresh_token),
            expires_in_seconds=token_json.get("expires_in"),
            platform_user_id=profile["id"],
            display_name=profile.get("username"),
        )

    def _upload_media(self, access_token: str, image_url: str) -> str | None:
        try:
            image_bytes = httpx.get(image_url, timeout=15.0).content
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(
                    MEDIA_UPLOAD_URL,
                    files={"media": image_bytes},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if resp.status_code >= 400:
                return None
            return resp.json().get("media_id_string")
        except httpx.HTTPError:
            return None

    def post_content(
        self, access_token: str, author_platform_user_id: str, text: str, image_url: str | None = None
    ) -> PostResult:
        body: dict = {"text": text[: self.max_post_length]}
        if image_url:
            media_id = self._upload_media(access_token, image_url)
            if media_id:
                body["media"] = {"media_ids": [media_id]}

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    TWEETS_URL,
                    json=body,
                    headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                )

            if resp.status_code >= 500 or resp.status_code == 429:
                return PostResult(
                    success=False,
                    error_message=f"Twitter API {resp.status_code}: {resp.text[:500]}",
                    is_transient_error=True,
                )
            if resp.status_code >= 400:
                return PostResult(success=False, error_message=f"Twitter API {resp.status_code}: {resp.text[:500]}")

            tweet_id = resp.json().get("data", {}).get("id")
            return PostResult(success=True, platform_post_id=tweet_id)
        except httpx.HTTPError as exc:
            return PostResult(success=False, error_message=str(exc), is_transient_error=True)
