"""ORM models for ``adapter_health`` and ``zlibrary_quota`` tables."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import CheckConstraint, Date, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from grabarr.db.base import Base


class AdapterHealthRow(Base):
    """Rolling health view per adapter."""

    __tablename__ = "adapter_health"

    adapter_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_check_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    next_recheck_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_success_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('healthy', 'degraded', 'unhealthy')",
            name="adapter_health_status_valid",
        ),
    )


class ZLibraryQuota(Base):
    """Singleton-per-day Z-Library quota counter (FR-005)."""

    __tablename__ = "zlibrary_quota"

    date_utc: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    downloads_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    downloads_max: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    reset_at_utc: Mapped[dt.datetime] = mapped_column(nullable=False)
