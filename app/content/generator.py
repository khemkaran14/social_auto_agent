"""Generates on-niche social posts with Claude.

Kept platform-agnostic: it takes a target character limit rather than
assuming LinkedIn, so the same generator can serve other platforms later.
"""

from __future__ import annotations

import anthropic

from app.config import get_settings
from app.models.niche import Niche

settings = get_settings()

SYSTEM_PROMPT = """\
You are a ghostwriter who writes original social media posts for a specific \
niche/brand. You write in the requested tone, stay strictly on-topic for the \
niche described, and never repeat ideas, hooks, or phrasing the user has \
recently posted. Output ONLY the finished post text -- no preamble, no \
quotation marks around it, no markdown formatting, no explanations."""


def _build_user_prompt(niche: Niche, recent_posts: list[str], max_length: int) -> str:
    pillars = ", ".join(niche.content_pillars) if niche.content_pillars else "no specific pillars set"
    keywords = ", ".join(niche.keywords) if niche.keywords else "none specified"

    recent_block = "\n".join(f"- {p[:200]}" for p in recent_posts[-10:]) or "(no prior posts yet)"

    return f"""\
Niche: {niche.name}
Description: {niche.description}
Tone: {niche.tone}
Content pillars to draw from: {pillars}
Keywords/themes to weave in naturally when relevant: {keywords}

Recently published posts (do NOT repeat these ideas or openings):
{recent_block}

Write ONE new post for this niche, at most {max_length} characters, following \
best practices for the platform: a strong hook in the first line, short \
paragraphs with whitespace between them, no hashtag stuffing (0-3 relevant \
hashtags at the end at most), and a natural, human voice."""


class ContentGenerator:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str | None = None):
        self.client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=3)
        self.model = model or settings.content_model

    def generate_post(self, niche: Niche, recent_posts: list[str], max_length: int = 3000) -> str:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_prompt(niche, recent_posts, max_length)}],
        )
        text = "".join(block.text for block in message.content if block.type == "text").strip()
        return text[:max_length]
