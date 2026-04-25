"""Ephemeral search-result → grab-token mapping.

Separated from ``downloads`` so search activity doesn't pollute the
downloads history. Each search item gets a row here; a row only
transitions into a real ``Download`` row the moment an *arr client
(or the UI) GETs ``/torznab/{slug}/download/{token}.torrent``.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from grabarr.db.base import Base, UUIDColumn, _new_uuidv7


class SearchToken(Base):
    """Mapping from a torznab ``<guid>`` token to the metadata needed
    to kick off a real grab on demand.

    TTL is managed by the periodic sweeper (default 24 h). No fk to
    profiles so the row survives a profile delete — the token just
    won't resolve when /download is hit.
    """

    __tablename__ = "search_tokens"

    id: Mapped[str] = mapped_column(UUIDColumn, primary_key=True, default=_new_uuidv7)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    profile_slug: Mapped[str] = mapped_column(String(128), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Original torznab `q` parameter. Forwarded to adapter.get_download_info
    # as `query_hint` so the IA adapter can filename-match inside
    # multi-file ROM romsets.
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.UTC)
    )

    __table_args__ = (
        Index("ix_search_tokens_created_at", "created_at"),
    )
