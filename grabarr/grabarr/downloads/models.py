"""ORM model for the ``downloads`` table.

Schema per ``data-model.md`` §"downloads" table. State lifecycle is
enforced by the ``DownloadStatus`` enum + a CHECK constraint.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from grabarr.db.base import Base, UUIDColumn, _new_uuidv7


class Download(Base):
    """A single grab request from an *arr client."""

    __tablename__ = "downloads"

    id: Mapped[str] = mapped_column(UUIDColumn, primary_key=True, default=_new_uuidv7)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    profile_id: Mapped[str] = mapped_column(
        UUIDColumn, ForeignKey("profiles.id", ondelete="RESTRICT"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    download_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    torrent_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(nullable=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    magic_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    info_hash: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.UTC)
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    ready_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    seeded_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    file_removed_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','resolving','downloading','verifying',"
            "'ready','seeding','completed','failed')",
            name="downloads_status_valid",
        ),
        CheckConstraint(
            "info_hash IS NULL OR length(info_hash) = 40",
            name="downloads_info_hash_length",
        ),
        Index("ix_downloads_profile_status", "profile_id", "status"),
        Index("ix_downloads_started_at_desc", "started_at"),
        Index("ix_downloads_info_hash", "info_hash", unique=True),
    )
