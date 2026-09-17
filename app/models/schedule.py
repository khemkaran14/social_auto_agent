from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PostSchedule(Base):
    """How often a social account should auto-post. Kept as a plain interval
    for v1; swap in a cron expression later if per-day-of-week control is needed."""

    __tablename__ = "post_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    social_account_id: Mapped[int] = mapped_column(
        ForeignKey("social_accounts.id", ondelete="CASCADE"), unique=True, index=True
    )

    interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # When true, generated posts are held as PostStatus.pending_approval instead of
    # being published immediately; a human must call the approve endpoint to publish.
    require_approval: Mapped[bool] = mapped_column(Boolean, default=False)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    social_account: Mapped["SocialAccount"] = relationship(back_populates="schedule")
