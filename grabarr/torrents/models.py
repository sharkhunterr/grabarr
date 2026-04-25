"""ORM models for the ``torrents`` and ``tracker_peers`` tables."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from grabarr.db.base import Base, UUIDColumn


class Torrent(Base):
    """Per-``.torrent`` metadata for observability + sweeper."""

    __tablename__ = "torrents"

    info_hash: Mapped[str] = mapped_column(String(40), primary_key=True)
    download_id: Mapped[str] = mapped_column(
        UUIDColumn,
        ForeignKey("downloads.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    total_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    piece_size_bytes: Mapped[int] = mapped_column(nullable=False)
    piece_count: Mapped[int] = mapped_column(nullable=False)
    webseed_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.UTC)
    )
    expires_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    last_announced_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint("length(info_hash) = 40", name="torrents_info_hash_length"),
        CheckConstraint(
            "mode IN ('active_seed', 'webseed')", name="torrents_mode_valid"
        ),
        Index("ix_torrents_expires_at", "expires_at"),
    )


class TrackerPeer(Base):
    """Internal HTTP tracker peer table (30-min TTL sweep)."""

    __tablename__ = "tracker_peers"

    info_hash: Mapped[str] = mapped_column(String(40), primary_key=True)
    peer_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False)
    port: Mapped[int] = mapped_column(nullable=False)
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.UTC)
    )
    uploaded: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    downloaded: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    left_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    event: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "event IS NULL OR event IN ('started','stopped','completed')",
            name="tracker_peers_event_valid",
        ),
        Index("ix_tracker_peers_last_seen_at", "last_seen_at"),
    )
