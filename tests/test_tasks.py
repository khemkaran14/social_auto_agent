from datetime import datetime, timedelta, timezone

from app import tasks
from app.core.security import encrypt_token
from app.database import SessionLocal
from app.models.schedule import PostSchedule
from app.models.social_account import SocialAccount
from app.models.user import User


def _make_schedule(db, interval_hours=24, active=True, last_run_at=None, account_status="active") -> int:
    user = User(email=f"dispatch-{datetime.now(timezone.utc).timestamp()}@example.com")
    db.add(user)
    db.flush()

    account = SocialAccount(
        user_id=user.id,
        platform="fake",
        platform_user_id="fake-user",
        access_token_encrypted=encrypt_token("token"),
        status=account_status,
    )
    db.add(account)
    db.flush()

    db.add(
        PostSchedule(
            social_account_id=account.id, interval_hours=interval_hours, active=active, last_run_at=last_run_at
        )
    )
    db.commit()
    return account.id


def test_is_due_when_never_run():
    schedule = PostSchedule(interval_hours=24, last_run_at=None)
    assert tasks._is_due(schedule, datetime.now(timezone.utc))


def test_is_due_when_interval_elapsed():
    now = datetime.now(timezone.utc)
    schedule = PostSchedule(interval_hours=24, last_run_at=now - timedelta(hours=25))
    assert tasks._is_due(schedule, now)


def test_not_due_when_interval_not_elapsed():
    now = datetime.now(timezone.utc)
    schedule = PostSchedule(interval_hours=24, last_run_at=now - timedelta(hours=1))
    assert not tasks._is_due(schedule, now)


def test_dispatch_only_dispatches_due_schedules_on_active_accounts(monkeypatch):
    dispatched = []
    monkeypatch.setattr(tasks.generate_and_post_task, "delay", lambda account_id: dispatched.append(account_id))

    db = SessionLocal()
    due_id = _make_schedule(db, last_run_at=None)  # never run -> due
    not_due_id = _make_schedule(db, last_run_at=datetime.now(timezone.utc))  # just ran -> not due
    inactive_account_id = _make_schedule(db, last_run_at=None, account_status="revoked")  # due but account inactive
    inactive_schedule_id = _make_schedule(db, last_run_at=None, active=False)  # due but schedule inactive
    db.close()

    count = tasks.dispatch_due_schedules_task()

    assert due_id in dispatched
    assert not_due_id not in dispatched
    assert inactive_account_id not in dispatched
    assert inactive_schedule_id not in dispatched
    assert count == len(dispatched)
