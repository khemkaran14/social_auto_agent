"""Platform-agnostic interface every social network integration implements.

Adding a new platform means writing one class here and registering it in
`registry.py` -- nothing else in the app (models, tasks, content generator,
API routes) needs to change; the `/auth/{platform}/authorize` and
`/auth/{platform}/callback` routes and the posting logic in `app/posting.py`
are all written against this interface, not against LinkedIn or Twitter
specifically.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TokenData:
    access_token: str
    refresh_token: str | None
    expires_in_seconds: int | None
    platform_user_id: str
    display_name: str | None = None


@dataclass
class PostResult:
    success: bool
    platform_post_id: str | None = None
    error_message: str | None = None
    # True for failures worth retrying (rate limits, 5xx, network blips) as opposed
    # to permanent failures (bad token, content rejected) that a retry can't fix.
    is_transient_error: bool = False


class SocialPlatform(ABC):
    """One implementation per social network. Stateless: every call takes
    whatever credentials it needs as arguments rather than holding them."""

    name: str
    max_post_length: int = 3000
    supports_media: bool = False

    def generate_state_extras(self) -> dict:
        """Extra data to embed in the signed OAuth state token before redirecting
        the user, for platforms that need it (e.g. Twitter's PKCE code_verifier).
        Returned values round-trip through `get_authorization_url` and back into
        `exchange_code` via the verified state payload."""
        return {}

    @abstractmethod
    def get_authorization_url(self, state: str, extras: dict | None = None) -> str:
        """Return the URL to send the end user to, to grant posting access."""

    @abstractmethod
    def exchange_code(self, code: str, code_verifier: str | None = None) -> TokenData:
        """Exchange an OAuth authorization code for tokens + profile info."""

    def refresh_access_token(self, refresh_token: str) -> TokenData:
        raise NotImplementedError(f"{self.name} does not support token refresh")

    @abstractmethod
    def post_content(
        self, access_token: str, author_platform_user_id: str, text: str, image_url: str | None = None
    ) -> PostResult:
        """Publish `text` (optionally with an attached image) on behalf of the authorized user."""
