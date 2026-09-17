"""Celery app + tasks.

Scheduling design: rather than dynamically registering/unregistering a
per-account periodic task in Celery Beat (which needs an extra scheduler
backend like redbeat to do safely), a single beat task runs every
`DISPATCH_INTERVAL_MINUTES` and polls the database for schedules that are
due, enqueuing a `generate_and_post_task` for each. Toggling a schedule's
`active` flag (or an account's `status`) takes effect on the very next
poll -- no job registration/deregistration needed anywhere.

Run in dev with two extra processes alongside `uvicorn`:
    celery -A app.tasks worker --loglevel=info
    celery -A app.tasks beat --loglevel=info
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from celery import Celery

from app.config import get_settings
from app.database import SessionLocal
from app.models.schedule import PostSchedule
from app.models.social_account import SocialAccount
from app.posting import TransientPlatformError, generate_and_post

settings = get_settings()
logger = logging.getLogger(__name__)

celery_app = Celery("social_auto_agent", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.beat_schedule = {
    "dispatch-due-schedules": {
        "task": "app.tasks.dispatch_due_schedules_task",
        "schedule": timedelta(minutes=settings.dispatch_interval_minutes),
    }
}
celery_app.conf.timezone = "UTC"


def _is_due(schedule: PostSchedule, now: datetime) -> bool:
    last_run_at = schedule.last_run_at
    if last_run_at is None:
        return True
    if last_run_at.tzinfo is None:
        # SQLite (used in tests) doesn't preserve tzinfo on round-trip; Postgres does.
        last_run_at = last_run_at.replace(tzinfo=timezone.utc)
    return now - last_run_at >= timedelta(hours=schedule.interval_hours)


@celery_app.task(name="app.tasks.dispatch_due_schedules_task")
def dispatch_due_schedules_task() -> int:
    """Beat task: find every active schedule on an active account that's due
    to post, and enqueue a generate_and_post_task for each. Returns the count
    dispatched (useful in logs/tests)."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due_ids = [
            schedule.social_account_id
            for schedule in (
                db.query(PostSchedule)
                .join(SocialAccount)
                .filter(PostSchedule.active.is_(True), SocialAccount.status == "active")
                .all()
            )
            if _is_due(schedule, now)
        ]
    finally:
        db.close()

    for social_account_id in due_ids:
        generate_and_post_task.delay(social_account_id)
    if due_ids:
        logger.info("Dispatched %d due schedule(s): %s", len(due_ids), due_ids)
    return len(due_ids)


@celery_app.task(
    name="app.tasks.generate_and_post_task",
    autoretry_for=(TransientPlatformError,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
def generate_and_post_task(social_account_id: int) -> int | None:
    return generate_and_post(social_account_id)
