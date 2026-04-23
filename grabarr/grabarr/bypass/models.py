"""ORM model for the ``bypass_sessions`` cache (research R-5)."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import CheckConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from grabarr.db.base import Base


class BypassSession(Base):
    """Cached ``(cf_clearance, user_agent)`` per domain, 30-min TTL."""

    __tablename__ = "bypass_sessions"

    domain: Mapped[str] = mapped_column(String(256), primary_key=True)
    user_agent: Mapped[str] = mapped_column(Text, nullable=False)
    cf_clearance: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    mode_used: Mapped[str] = mapped_column(String(16), nullable=False)
    hit_count: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(
            "mode_used IN ('external', 'internal')",
            name="bypass_sessions_mode_valid",
        ),
        Index("ix_bypass_sessions_expires_at", "expires_at"),
    )
