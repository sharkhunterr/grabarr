"""ORM model for the orchestrator's ``search_cache`` table (FR-013)."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from grabarr.db.base import Base, UUIDColumn


class SearchCacheEntry(Base):
    """Per-profile-and-query cached result set (15-min TTL)."""

    __tablename__ = "search_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(UUIDColumn, nullable=False)
    results: Mapped[list] = mapped_column(JSON, nullable=False)
    stored_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(nullable=False)

    __table_args__ = (
        Index("ix_search_cache_expires_at", "expires_at"),
    )
