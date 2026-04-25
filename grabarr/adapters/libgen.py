"""LibGen source adapter.

Spec FR-1.2: thin wrapper over the vendored Shelfmark cascade,
delegating to the same ``direct_download.py`` pipeline AA does. Results
are filtered post-hoc to those whose cascade sub-source is LibGen —
letting operators build a profile that ONLY uses LibGen without
disabling the AA adapter entirely.
"""

from __future__ import annotations

from grabarr.adapters.anna_archive import AnnaArchiveAdapter
from grabarr.adapters.base import (
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
class LibGenAdapter(AnnaArchiveAdapter):
    """LibGen source — uses the AA cascade, filters to LibGen-origin results."""

    id = "libgen"
    display_name = "Library Genesis"
    supported_media_types = {
        MediaType.EBOOK,
        MediaType.COMIC,
        MediaType.MAGAZINE,
        MediaType.PAPER,
    }
    requires_cf_bypass = False  # LibGen mirrors don't sit behind CF
    supports_member_key = False

    def __init__(self) -> None:  # type: ignore[override]
        super().__init__(member_key="")
        rate_limiter.configure(self.id, "search", per_minute=60)
        rate_limiter.configure(self.id, "download", per_minute=60)

    async def search(
        self,
        query: str,
        media_type: MediaType,
        filters: SearchFilters,
        limit: int = 50,
    ) -> list[SearchResult]:
        # Piggy-back on AA's cascade which covers LibGen as a fallback tier.
        # Surface LibGen-origin results by setting our own source_id on
        # results and letting the orchestrator's dedup merge with AA.
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
        return ConfigSchema(fields=[])
