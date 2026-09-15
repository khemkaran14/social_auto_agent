"""Platform-agnostic interface every social network integration implements.

Adding a new platform (Twitter/X, Instagram, ...) means writing one class
here and registering it in `registry.py` -- nothing else in the app (models,
scheduler, content generator, API routes) needs to change.
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


class SocialPlatform(ABC):
    """One implementation per social network. Stateless: every call takes
    whatever credentials it needs as arguments rather than holding them."""

    name: str
    max_post_length: int = 3000

    @abstractmethod
    def get_authorization_url(self, state: str) -> str:
        """Return the URL to send the end user to, to grant posting access."""

    @abstractmethod
    def exchange_code(self, code: str) -> TokenData:
        """Exchange an OAuth authorization code for tokens + profile info."""

    def refresh_access_token(self, refresh_token: str) -> TokenData:
        raise NotImplementedError(f"{self.name} does not support token refresh")

    @abstractmethod
    def post_content(self, access_token: str, author_platform_user_id: str, text: str) -> PostResult:
        """Publish `text` on behalf of the authorized user."""
