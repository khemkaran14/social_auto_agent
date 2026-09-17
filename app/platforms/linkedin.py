"""LinkedIn integration using LinkedIn's official OAuth 2.0 + Posts API.

Requires a LinkedIn developer app with the "Sign In with LinkedIn using
OpenID Connect" and "Share on LinkedIn" products enabled. This deliberately
does NOT use browser automation or scraping -- that violates LinkedIn's
Terms of Service and risks the end user's account being banned, which would
be a non-starter for a product meant to be resold to other people.

Uses the current versioned Posts API (`/rest/posts`), not the deprecated
`/v2/ugcPosts` endpoint.

Docs:
  https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2
  https://learn.microsoft.com/en-us/linkedin/marketing/integrations/community-management/shares/posts-api
  https://learn.microsoft.com/en-us/linkedin/marketing/integrations/community-management/shares/images-api
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.platforms.base import PostResult, SocialPlatform, TokenData

settings = get_settings()

AUTHORIZATION_URL = "https://www.linkedin.com/oauth/v2/authorization"
ACCESS_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
POSTS_URL = "https://api.linkedin.com/rest/posts"
IMAGES_URL = "https://api.linkedin.com/rest/images"

API_VERSION = "202405"
SCOPES = "openid profile w_member_social"


def _rest_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": API_VERSION,
    }


class LinkedInPlatform(SocialPlatform):
    name = "linkedin"
    max_post_length = 3000
    supports_media = True

    def get_authorization_url(self, state: str, extras: dict | None = None) -> str:
        params = {
            "response_type": "code",
            "client_id": settings.linkedin_client_id,
            "redirect_uri": settings.linkedin_redirect_uri,
            "state": state,
            "scope": SCOPES,
        }
        return f"{AUTHORIZATION_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str | None = None) -> TokenData:
        with httpx.Client(timeout=15.0) as client:
            token_resp = client.post(
                ACCESS_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.linkedin_redirect_uri,
                    "client_id": settings.linkedin_client_id,
                    "client_secret": settings.linkedin_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_resp.raise_for_status()
            token_json = token_resp.json()
            access_token = token_json["access_token"]

            profile_resp = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
            profile_resp.raise_for_status()
            profile = profile_resp.json()

        return TokenData(
            access_token=access_token,
            refresh_token=token_json.get("refresh_token"),
            expires_in_seconds=token_json.get("expires_in"),
            platform_user_id=profile["sub"],
            display_name=profile.get("name"),
        )

    def refresh_access_token(self, refresh_token: str) -> TokenData:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                ACCESS_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": settings.linkedin_client_id,
                    "client_secret": settings.linkedin_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            token_json = resp.json()
            access_token = token_json["access_token"]

            profile_resp = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
            profile_resp.raise_for_status()
            profile = profile_resp.json()

        return TokenData(
            access_token=access_token,
            refresh_token=token_json.get("refresh_token", refresh_token),
            expires_in_seconds=token_json.get("expires_in"),
            platform_user_id=profile["sub"],
            display_name=profile.get("name"),
        )

    def _upload_image(self, client: httpx.Client, access_token: str, author_urn: str, image_url: str) -> str | None:
        """Downloads `image_url` and uploads it to LinkedIn, returning the image URN, or None on failure."""
        try:
            image_bytes = httpx.get(image_url, timeout=15.0).content
        except httpx.HTTPError:
            return None

        init_resp = client.post(
            f"{IMAGES_URL}?action=initializeUpload",
            json={"initializeUploadRequest": {"owner": author_urn}},
            headers=_rest_headers(access_token),
        )
        if init_resp.status_code >= 400:
            return None
        init_data = init_resp.json().get("value", {})
        upload_url = init_data.get("uploadUrl")
        image_urn = init_data.get("image")
        if not upload_url or not image_urn:
            return None

        upload_resp = client.put(upload_url, content=image_bytes, headers={"Authorization": f"Bearer {access_token}"})
        if upload_resp.status_code >= 400:
            return None
        return image_urn

    def post_content(
        self, access_token: str, author_platform_user_id: str, text: str, image_url: str | None = None
    ) -> PostResult:
        author_urn = f"urn:li:person:{author_platform_user_id}"
        body = {
            "author": author_urn,
            "commentary": text[: self.max_post_length],
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        try:
            with httpx.Client(timeout=20.0) as client:
                if image_url:
                    image_urn = self._upload_image(client, access_token, author_urn, image_url)
                    if image_urn:
                        body["content"] = {"media": {"id": image_urn}}

                resp = client.post(POSTS_URL, json=body, headers=_rest_headers(access_token))

            if resp.status_code >= 500 or resp.status_code == 429:
                return PostResult(
                    success=False,
                    error_message=f"LinkedIn API {resp.status_code}: {resp.text[:500]}",
                    is_transient_error=True,
                )
            if resp.status_code >= 400:
                return PostResult(success=False, error_message=f"LinkedIn API {resp.status_code}: {resp.text[:500]}")

            post_id = resp.headers.get("x-restli-id") or resp.headers.get("x-linkedin-id")
            return PostResult(success=True, platform_post_id=post_id)
        except httpx.HTTPError as exc:
            return PostResult(success=False, error_message=str(exc), is_transient_error=True)
