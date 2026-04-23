"""Z-Library source adapter.

Spec FR-1.3: wrapper over vendored Shelfmark cascade + Grabarr-specific
quota tracking and cookie-expired detection (the latter lands in US4).
"""

from __future__ import annotations

from grabarr.adapters.anna_archive import AnnaArchiveAdapter
from grabarr.adapters.base import (
    ConfigField,
    ConfigSchema,
    MediaType,
    SearchFilters,
    SearchResult,
)
from grabarr.core.logging import setup_logger
from grabarr.core.rate_limit import rate_limiter
from grabarr.core.registry import register_adapter

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
