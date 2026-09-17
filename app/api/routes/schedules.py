from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_owned_social_account
from app.database import get_db
from app.models.schedule import PostSchedule
from app.models.social_account import SocialAccount

router = APIRouter(prefix="/social-accounts/{social_account_id}/schedule", tags=["schedules"])


class ScheduleRequest(BaseModel):
    interval_hours: int = Field(default=24, ge=1, le=24 * 30)
    timezone: str = "UTC"
    active: bool = True
    # When true, generated posts wait for a human to call the approve endpoint
    # instead of publishing immediately.
    require_approval: bool = False


class ScheduleResponse(ScheduleRequest):
    id: int

    class Config:
        from_attributes = True


@router.get("", response_model=ScheduleResponse | None)
def get_schedule(account: SocialAccount = Depends(get_owned_social_account)) -> PostSchedule | None:
    return account.schedule


@router.put("", response_model=ScheduleResponse)
def upsert_schedule(
    payload: ScheduleRequest,
    account: SocialAccount = Depends(get_owned_social_account),
    db: Session = Depends(get_db),
) -> PostSchedule:
    schedule = account.schedule
    if schedule is None:
        schedule = PostSchedule(social_account_id=account.id)
        db.add(schedule)

    schedule.interval_hours = payload.interval_hours
    schedule.timezone = payload.timezone
    schedule.active = payload.active
    schedule.require_approval = payload.require_approval
    db.commit()
    db.refresh(schedule)
    # No job registration needed: the Celery beat dispatcher (app.tasks) polls
    # this table directly, so a plain DB write is all that's required for the
    # change to take effect on its next pass.
    return schedule
