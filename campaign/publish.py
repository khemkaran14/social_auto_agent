"""Campaign runner: publishes due posts from `campaign/queue/*.yaml`.

Runs from GitHub Actions every 30 minutes (see .github/workflows/publish.yml),
with no database or server. Each post's result is written back into its
queue file, so the repo itself is the audit log.

    python -m campaign.publish            # post everything that is due
    python -m campaign.publish --dry-run  # show what would post, post nothing
    python -m campaign.publish --check    # validate queue files only

Post statuses:
    draft     written but not approved; never published
    approved  will publish once publish_at has passed
    posted    published (platform_post_id is set)
    failed    gave up after a permanent error or too many attempts
    missed    still unpublished more than `max_late_hours` after publish_at
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from app.platforms.base import PostResult, SocialPlatform
from app.platforms.linkedin import LinkedInPlatform
from app.platforms.meta import FacebookPagePlatform, InstagramPlatform

CAMPAIGN_DIR = Path(__file__).resolve().parent
REPO_ROOT = CAMPAIGN_DIR.parent
STATUSES = {"draft", "approved", "posted", "failed", "missed"}
TIME_FORMAT = "%Y-%m-%d %H:%M"

PLATFORMS: dict[str, type[SocialPlatform]] = {
    "facebook": FacebookPagePlatform,
    "instagram": InstagramPlatform,
    "linkedin": LinkedInPlatform,
}
NEEDS_IMAGE = {"instagram"}


@dataclass
class Account:
    id: str
    brand: str
    platform: str
    token_secret: str
    target_secret: str
    target_format: str = "{id}"


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class _QueueDumper(yaml.SafeDumper):
    """Writes multi-line post text as readable `|` blocks, so a pull request
    diff shows posts the way they will appear."""


def _str_representer(dumper: yaml.SafeDumper, value: str):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_QueueDumper.add_representer(str, _str_representer)


def save_yaml(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, Dumper=_QueueDumper, sort_keys=False, allow_unicode=True, width=1000)


def load_settings(campaign_dir: Path = CAMPAIGN_DIR) -> dict:
    settings = load_yaml(campaign_dir / "settings.yaml")
    settings.setdefault("timezone", "Asia/Kolkata")
    settings.setdefault("max_attempts", 3)
    settings.setdefault("max_late_hours", 24)
    return settings


def load_accounts(campaign_dir: Path = CAMPAIGN_DIR) -> dict[str, Account]:
    data = load_yaml(campaign_dir / "brands.yaml")
    return {a["id"]: Account(**a) for a in data.get("accounts", [])}


def load_secrets() -> dict[str, str]:
    """GitHub Actions passes every repo secret as one JSON blob in SECRETS_JSON,
    so new accounts need no workflow edit. Plain env vars also work locally."""
    secrets = dict(os.environ)
    raw = os.environ.get("SECRETS_JSON")
    if raw:
        try:
            secrets.update({k: v for k, v in json.loads(raw).items() if isinstance(v, str)})
        except json.JSONDecodeError:
            print("warning: SECRETS_JSON is not valid JSON", file=sys.stderr)
    return secrets


def image_public_url(image_path: str) -> str | None:
    """Instagram and Facebook fetch images by URL. A public repo's raw files work,
    pinned to the running commit so the URL never changes under the post."""
    base = os.environ.get("CAMPAIGN_IMAGE_BASE_URL")
    if base:
        return f"{base.rstrip('/')}/{image_path}"
    repo = os.environ.get("GITHUB_REPOSITORY")
    ref = os.environ.get("GITHUB_SHA")
    if repo and ref:
        return f"https://raw.githubusercontent.com/{repo}/{ref}/{image_path}"
    return None


def parse_time(value: str, tz: ZoneInfo) -> datetime:
    return datetime.strptime(str(value), TIME_FORMAT).replace(tzinfo=tz)


def validate(campaign_dir: Path = CAMPAIGN_DIR, repo_root: Path = REPO_ROOT) -> list[str]:
    """Return a list of problems across all queue files (empty means valid)."""
    problems: list[str] = []
    accounts = load_accounts(campaign_dir)
    for acc in accounts.values():
        if acc.platform not in PLATFORMS:
            problems.append(f"account {acc.id}: unknown platform {acc.platform!r}")
    tz = ZoneInfo(load_settings(campaign_dir)["timezone"])
    seen: set[str] = set()
    for qfile in sorted((campaign_dir / "queue").glob("*.yaml")):
        for i, post in enumerate(load_yaml(qfile).get("posts", []) or []):
            where = f"{qfile.name} post {post.get('id', i)}"
            pid = post.get("id")
            if not pid:
                problems.append(f"{where}: missing id")
            elif pid in seen:
                problems.append(f"{where}: duplicate id")
            seen.add(pid)
            acc = accounts.get(post.get("account"))
            if not acc:
                problems.append(f"{where}: unknown account {post.get('account')!r}")
                continue
            if post.get("status") not in STATUSES:
                problems.append(f"{where}: status must be one of {sorted(STATUSES)}")
            try:
                parse_time(post.get("publish_at"), tz)
            except (TypeError, ValueError):
                problems.append(f"{where}: publish_at must look like 2026-10-27 19:00")
            text = post.get("text") or ""
            if not text.strip():
                problems.append(f"{where}: empty text")
            limit = PLATFORMS[acc.platform].max_post_length if acc.platform in PLATFORMS else None
            if limit and len(text) > limit:
                problems.append(f"{where}: text is {len(text)} chars, {acc.platform} allows {limit}")
            image = post.get("image")
            if acc.platform in NEEDS_IMAGE and not image:
                problems.append(f"{where}: {acc.platform} needs an image")
            if image and post.get("status") in ("draft", "approved") and not (repo_root / image).is_file():
                problems.append(f"{where}: image file {image} not found")
    return problems


def publish_due(
    now: datetime | None = None,
    dry_run: bool = False,
    campaign_dir: Path = CAMPAIGN_DIR,
    repo_root: Path = REPO_ROOT,
    secrets: dict[str, str] | None = None,
    platforms: dict[str, type[SocialPlatform]] | None = None,
) -> list[str]:
    """Publish every approved post whose time has come. Returns report lines."""
    settings = load_settings(campaign_dir)
    tz = ZoneInfo(settings["timezone"])
    now = now or datetime.now(tz)
    accounts = load_accounts(campaign_dir)
    secrets = load_secrets() if secrets is None else secrets
    platforms = platforms or PLATFORMS
    late_limit = timedelta(hours=settings["max_late_hours"])
    report: list[str] = []

    for qfile in sorted((campaign_dir / "queue").glob("*.yaml")):
        data = load_yaml(qfile)
        changed = False
        for post in data.get("posts", []) or []:
            if post.get("status") != "approved":
                continue
            due = parse_time(post["publish_at"], tz)
            if due > now:
                continue
            pid = post["id"]
            if now - due > late_limit:
                post["status"] = "missed"
                changed = True
                report.append(f"MISSED {pid}: more than {settings['max_late_hours']}h late ({post.get('last_error', 'not run')})")
                continue

            acc = accounts[post["account"]]
            token = secrets.get(acc.token_secret)
            target = secrets.get(acc.target_secret)
            if not token or not target:
                missing = [n for n, v in ((acc.token_secret, token), (acc.target_secret, target)) if not v]
                post["last_error"] = f"waiting for secret(s): {', '.join(missing)}"
                changed = True
                report.append(f"WAITING {pid}: add {', '.join(missing)} in GitHub secrets, or post it by hand")
                continue

            image_url = None
            if post.get("image"):
                image_url = image_public_url(post["image"])
                if not image_url:
                    report.append(f"SKIP {pid}: no public URL for {post['image']} (run inside GitHub Actions)")
                    continue

            if dry_run:
                report.append(f"WOULD POST {pid} to {acc.id}")
                continue

            platform = platforms[acc.platform]()
            result: PostResult = platform.post_content(
                token, acc.target_format.format(id=target), post["text"].strip(), image_url
            )
            post["attempts"] = int(post.get("attempts", 0)) + 1
            changed = True
            if result.success:
                post["status"] = "posted"
                post["posted_at"] = now.strftime(TIME_FORMAT)
                post["platform_post_id"] = result.platform_post_id
                post.pop("last_error", None)
                report.append(f"POSTED {pid} to {acc.id} ({result.platform_post_id})")
            else:
                post["last_error"] = result.error_message
                if not result.is_transient_error or post["attempts"] >= settings["max_attempts"]:
                    post["status"] = "failed"
                    report.append(f"FAILED {pid}: {result.error_message}")
                else:
                    report.append(f"RETRY {pid}: {result.error_message}")
        if changed and not dry_run:
            save_yaml(qfile, data)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    problems = validate()
    if problems:
        print("Queue problems:\n  " + "\n  ".join(problems))
        return 1
    if args.check:
        print("Queue OK")
        return 0

    report = publish_due(dry_run=args.dry_run) or ["Nothing due."]
    text = "\n".join(report)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Campaign publish\n\n" + "\n".join(f"- {line}" for line in report) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
