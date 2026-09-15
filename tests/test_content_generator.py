from app.content.generator import _build_user_prompt
from app.models.niche import Niche


def _make_niche(**overrides) -> Niche:
    defaults = dict(
        name="Indie SaaS Building",
        description="Practical lessons from building and marketing small SaaS products.",
        tone="candid, first-person",
        content_pillars=["pricing", "marketing", "shipping fast"],
        keywords=["bootstrapped", "MRR"],
    )
    defaults.update(overrides)
    return Niche(**defaults)


def test_prompt_includes_niche_details():
    niche = _make_niche()
    prompt = _build_user_prompt(niche, recent_posts=[], max_length=3000)
    assert niche.name in prompt
    assert niche.description in prompt
    assert "pricing" in prompt
    assert "bootstrapped" in prompt
    assert "3000" in prompt


def test_prompt_includes_recent_posts_to_avoid_repetition():
    niche = _make_niche()
    prompt = _build_user_prompt(niche, recent_posts=["Why I killed my pricing page"], max_length=3000)
    assert "Why I killed my pricing page" in prompt


def test_prompt_handles_no_recent_posts():
    niche = _make_niche()
    prompt = _build_user_prompt(niche, recent_posts=[], max_length=3000)
    assert "no prior posts yet" in prompt
