"""ORM model for the ``profiles`` table.

Schema per ``data-model.md`` §"profiles" table.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, CheckConstraint, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from grabarr.db.base import Base, UUIDColumn, _new_uuidv7


class Profile(Base):
    """A named routing recipe. Each profile exposes one Torznab endpoint."""

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(UUIDColumn, primary_key=True, default=_new_uuidv7)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sources: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    filters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="first_match")
    newznab_categories: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    download_mode_override: Mapped[str | None] = mapped_column(String(32), nullable=True)
    torrent_mode_override: Mapped[str | None] = mapped_column(String(32), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    api_key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.UTC)
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.UTC)
    )

    __table_args__ = (
        CheckConstraint(
            "slug GLOB '[a-z0-9][a-z0-9_-]*'",
            name="profiles_slug_charset",
        ),
        CheckConstraint(
            "length(slug) >= 2 AND length(slug) <= 64",
            name="profiles_slug_length",
        ),
        CheckConstraint(
            "mode IN ('first_match', 'aggregate_all')",
            name="profiles_mode_valid",
        ),
        Index("ix_profiles_enabled_default", "enabled", "is_default"),
    )
