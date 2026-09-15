from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Niche(Base):
    """Describes what an account should post about, so the content generator
    stays on-topic and on-brand without a human writing every post."""

    __tablename__ = "niches"

    id: Mapped[int] = mapped_column(primary_key=True)
    social_account_id: Mapped[int] = mapped_column(
        ForeignKey("social_accounts.id", ondelete="CASCADE"), unique=True, index=True
    )

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    tone: Mapped[str] = mapped_column(String(64), default="professional")
    content_pillars: Mapped[list[str]] = mapped_column(JSON, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    social_account: Mapped["SocialAccount"] = relationship(back_populates="niche")
