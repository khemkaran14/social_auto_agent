import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PostStatus(str, enum.Enum):
    draft = "draft"
    pending_approval = "pending_approval"
    posted = "posted"
    failed = "failed"
    rejected = "rejected"


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    social_account_id: Mapped[int] = mapped_column(ForeignKey("social_accounts.id", ondelete="CASCADE"), index=True)
    niche_id: Mapped[int | None] = mapped_column(ForeignKey("niches.id", ondelete="SET NULL"), nullable=True)

    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=PostStatus.draft.value)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    platform_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    social_account: Mapped["SocialAccount"] = relationship(back_populates="posts")
