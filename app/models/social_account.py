import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Platform(str, enum.Enum):
    """Every social platform the agent knows how to post to.

    Add new platforms here and implement app.platforms.<name>; the rest of the
    app (scheduler, content generator, API) is platform-agnostic.
    """

    linkedin = "linkedin"
    twitter = "twitter"


class SocialAccount(Base):
    __tablename__ = "social_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    platform: Mapped[str] = mapped_column(String(32))
    platform_user_id: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    access_token_encrypted: Mapped[str] = mapped_column(String)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="active")  # active | revoked | needs_reauth
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user: Mapped["User"] = relationship(back_populates="social_accounts")
    niche: Mapped["Niche | None"] = relationship(
        back_populates="social_account", cascade="all, delete-orphan", uselist=False
    )
    schedule: Mapped["PostSchedule | None"] = relationship(
        back_populates="social_account", cascade="all, delete-orphan", uselist=False
    )
    posts: Mapped[list["Post"]] = relationship(back_populates="social_account", cascade="all, delete-orphan")
