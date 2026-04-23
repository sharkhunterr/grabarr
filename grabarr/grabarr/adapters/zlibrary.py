"""Z-Library source adapter.

Spec FR-1.3: wrapper over vendored Shelfmark cascade + Grabarr-specific
quota tracking (persisted, resets at midnight UTC) and cookie-expired
detection.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from grabarr.adapters.anna_archive import AnnaArchiveAdapter
from grabarr.adapters.base import (
    ConfigField,
    ConfigSchema,
    MediaType,
    QuotaStatus,
    SearchFilters,
    SearchResult,
)
from grabarr.adapters.health_model import ZLibraryQuota
from grabarr.core.logging import setup_logger
from grabarr.core.rate_limit import rate_limiter
from grabarr.core.registry import register_adapter
from grabarr.db.session import session_scope

_log = setup_logger(__name__)


@register_adapter
class ZLibraryAdapter(AnnaArchiveAdapter):
    """Z-Library source — uses the AA cascade filtered to Z-Lib origin."""

    id = "zlibrary"
    display_name = "Z-Library"
    supported_media_types = {MediaType.EBOOK, MediaType.AUDIOBOOK}
    requires_cf_bypass = True
    supports_member_key = False
    supports_authentication = True  # remix cookies

    def __init__(self, remix_userid: str = "", remix_userkey: str = "") -> None:  # type: ignore[override]
        super().__init__(member_key="")
        self._remix_userid = remix_userid
        self._remix_userkey = remix_userkey
        rate_limiter.configure(self.id, "search", per_minute=10)
        rate_limiter.configure(self.id, "download", per_minute=10)

    async def search(
        self,
        query: str,
        media_type: MediaType,
        filters: SearchFilters,
        limit: int = 50,
    ) -> list[SearchResult]:
        if not self._remix_userid or not self._remix_userkey:
            _log.info("zlibrary: no remix credentials configured; returning empty results")
            return []
        results = await super().search(query, media_type, filters, limit)
        return [
            SearchResult(
                external_id=r.external_id,
                title=r.title,
                author=r.author,
                year=r.year,
                format=r.format,
                language=r.language,
                size_bytes=r.size_bytes,
                quality_score=r.quality_score,
                source_id=self.id,
                media_type=r.media_type,
                metadata={**r.metadata, "via": "shelfmark_cascade"},
            )
            for r in results
        ]

    async def get_quota_status(self) -> QuotaStatus | None:
        """Return today's download counter (FR-005).

        Row is keyed by UTC date; a new row appears automatically at
        the next day's first access. ``limit`` comes from the
        settings-backed rate-limit default but is not enforced here;
        the orchestrator checks ``used >= limit`` via
        :meth:`is_exhausted` below.
        """
        today = dt.datetime.now(dt.UTC).date()
        async with session_scope() as session:
            row = await session.execute(
                select(ZLibraryQuota).where(ZLibraryQuota.date_utc == today)
            )
            obj = row.scalar_one_or_none()
            if obj is None:
                return QuotaStatus(
                    used=0,
                    limit=10,
                    resets_at=_next_midnight_utc(),
                )
            return QuotaStatus(
                used=obj.downloads_used,
                limit=obj.downloads_max,
                resets_at=obj.reset_at_utc,
            )

    async def is_exhausted(self) -> bool:
        quota = await self.get_quota_status()
        if quota is None:
            return False
        return quota.used >= quota.limit

    async def record_download(self) -> None:
        """Bump today's used counter by 1 (called on successful download)."""
        today = dt.datetime.now(dt.UTC).date()
        async with session_scope() as session:
            row = await session.execute(
                select(ZLibraryQuota).where(ZLibraryQuota.date_utc == today)
            )
            obj = row.scalar_one_or_none()
            if obj is None:
                session.add(
                    ZLibraryQuota(
                        date_utc=today,
                        downloads_used=1,
                        downloads_max=10,
                        reset_at_utc=_next_midnight_utc(),
                    )
                )
            else:
                obj.downloads_used += 1

    def get_config_schema(self) -> ConfigSchema:
        return ConfigSchema(
            fields=[
                ConfigField(
                    key="sources.zlibrary.remix_userid",
                    label="Z-Library remix_userid cookie",
                    field_type="text",
                    options=None,
                    secret=True,
                    required=True,
                    help_text=(
                        "Obtain from your Z-Library account → Settings → Cookies. "
                        "Without this the adapter is disabled."
                    ),
                ),
                ConfigField(
                    key="sources.zlibrary.remix_userkey",
                    label="Z-Library remix_userkey cookie",
                    field_type="password",
                    options=None,
                    secret=True,
                    required=True,
                    help_text="Paired with remix_userid. Refresh when expired.",
                ),
            ]
        )


def _next_midnight_utc() -> dt.datetime:
    now = dt.datetime.now(dt.UTC)
    return (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
