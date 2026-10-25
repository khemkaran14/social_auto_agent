"""List the image cards the queue needs, as JSON for render-cards.mjs.

    python -m campaign.cards > /tmp/cards.json
    node campaign/render-cards.mjs /tmp/cards.json

A post gets a card when it has both `image:` (where the PNG goes) and
`card:` (headline, optional kicker / sub / footer). Existing PNGs are
skipped unless --all is given.
"""

from __future__ import annotations

import json
import sys

from campaign.publish import CAMPAIGN_DIR, REPO_ROOT, load_accounts, load_yaml


def needed_cards(include_existing: bool = False) -> list[dict]:
    accounts = load_accounts()
    brands = load_yaml(CAMPAIGN_DIR / "brands.yaml").get("brands", {})
    cards = []
    for qfile in sorted((CAMPAIGN_DIR / "queue").glob("*.yaml")):
        for post in load_yaml(qfile).get("posts", []) or []:
            card, image = post.get("card"), post.get("image")
            if not card or not image or post.get("status") not in ("draft", "approved"):
                continue
            out = REPO_ROOT / image
            if out.exists() and not include_existing:
                continue
            brand_key = card.get("brand") or accounts[post["account"]].brand
            brand = brands.get(brand_key, {})
            cards.append(
                {
                    "out": str(out),
                    "kicker": card.get("kicker", ""),
                    "headline": card["headline"],
                    "sub": card.get("sub", ""),
                    "footer": card.get("footer") or brand.get("url", "").replace("https://", "").rstrip("/"),
                    "brand": brand.get("name", brand_key),
                    "colors": brand.get("colors", {"bg": "#111", "fg": "#fff", "accent": "#ffcc00"}),
                }
            )
    return cards


if __name__ == "__main__":
    json.dump(needed_cards(include_existing="--all" in sys.argv), sys.stdout, ensure_ascii=False, indent=1)
