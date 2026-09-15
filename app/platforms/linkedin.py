"""LinkedIn integration using LinkedIn's official OAuth 2.0 + Marketing API.

Requires a LinkedIn developer app with the "Sign In with LinkedIn using
OpenID Connect" and "Share on LinkedIn" products enabled. This deliberately
does NOT use browser automation or scraping -- that violates LinkedIn's
Terms of Service and risks the end user's account being banned, which would
be a non-starter for a product meant to be resold to other people.

Docs:
  https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2
  https://learn.microsoft.com/en-us/linkedin/marketing/integrations/community-management/shares/ugc-post-api
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
UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"

SCOPES = "openid profile w_member_social"


class LinkedInPlatform(SocialPlatform):
    name = "linkedin"
    max_post_length = 3000

    def get_authorization_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": settings.linkedin_client_id,
            "redirect_uri": settings.linkedin_redirect_uri,
            "state": state,
            "scope": SCOPES,
        }
        return f"{AUTHORIZATION_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> TokenData:
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
            expires_in = token_json.get("expires_in")

            profile_resp = client.get(
                USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
            profile_resp.raise_for_status()
            profile = profile_resp.json()

        return TokenData(
            access_token=access_token,
            refresh_token=token_json.get("refresh_token"),
            expires_in_seconds=expires_in,
            platform_user_id=profile["sub"],
            display_name=profile.get("name"),
        )

    def post_content(self, access_token: str, author_platform_user_id: str, text: str) -> PostResult:
        body = {
            "author": f"urn:li:person:{author_platform_user_id}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text[: self.max_post_length]},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    UGC_POSTS_URL,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                        "X-Restli-Protocol-Version": "2.0.0",
                    },
                )
            if resp.status_code >= 400:
                return PostResult(success=False, error_message=f"LinkedIn API {resp.status_code}: {resp.text[:500]}")
            post_id = resp.headers.get("x-restli-id") or resp.json().get("id")
            return PostResult(success=True, platform_post_id=post_id)
        except httpx.HTTPError as exc:
            return PostResult(success=False, error_message=str(exc))
