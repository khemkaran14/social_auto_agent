"""Thin wrapper around APScheduler so the rest of the app doesn't touch it directly.

Runs in-process for v1. If this needs to scale past a single worker process
(e.g. running the API and the scheduler on separate machines for the SaaS
version), swap this for Celery beat + workers without changing job logic in
`jobs.py`.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.database import SessionLocal
from app.models.schedule import PostSchedule
from app.scheduler.jobs import generate_and_post


def _job_id(social_account_id: int) -> str:
    return f"post_social_account_{social_account_id}"


class AgentScheduler:
    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler()

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def sync_from_db(self) -> None:
        """Reconcile APScheduler's jobs with the current PostSchedule rows."""
        db = SessionLocal()
        try:
            schedules = db.query(PostSchedule).all()
            active_ids = set()
            for schedule in schedules:
                if schedule.active:
                    active_ids.add(schedule.social_account_id)
                    self.upsert_job(schedule.social_account_id, schedule.interval_hours)
                else:
                    self.remove_job(schedule.social_account_id)

            for job in self._scheduler.get_jobs():
                if job.id.startswith("post_social_account_"):
                    sa_id = int(job.id.rsplit("_", 1)[-1])
                    if sa_id not in active_ids:
                        self._scheduler.remove_job(job.id)
        finally:
            db.close()

    def upsert_job(self, social_account_id: int, interval_hours: int) -> None:
        self._scheduler.add_job(
            generate_and_post,
            trigger=IntervalTrigger(hours=interval_hours),
            args=[social_account_id],
            id=_job_id(social_account_id),
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def remove_job(self, social_account_id: int) -> None:
        job_id = _job_id(social_account_id)
        if self._scheduler.get_job(job_id) is not None:
            self._scheduler.remove_job(job_id)

    def run_now(self, social_account_id: int) -> None:
        generate_and_post(social_account_id)


scheduler = AgentScheduler()
