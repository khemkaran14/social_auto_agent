from app.platforms.base import SocialPlatform
from app.platforms.linkedin import LinkedInPlatform

_PLATFORMS: dict[str, type[SocialPlatform]] = {
    "linkedin": LinkedInPlatform,
    # Add "twitter": TwitterPlatform, "instagram": InstagramPlatform, etc. here as they're built.
}


def get_platform(name: str) -> SocialPlatform:
    try:
        return _PLATFORMS[name]()
    except KeyError as exc:
        raise ValueError(f"Unsupported platform: {name!r}. Known platforms: {list(_PLATFORMS)}") from exc
