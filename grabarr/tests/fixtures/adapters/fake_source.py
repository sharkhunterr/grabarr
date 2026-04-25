"""Fake adapter used by the US5 registry-discovery tests."""

from __future__ import annotations

import datetime as dt

from grabarr.adapters.base import (
    ConfigSchema,
    DownloadInfo,
    HealthStatus,
    MediaType,
    QuotaStatus,
    SearchFilters,
    SearchResult,
)
from grabarr.core.enums import AdapterHealth
from grabarr.core.registry import register_adapter


@register_adapter
class FakeTestAdapter:
    id = "fake_test"
    display_name = "Fake Test Source"
    supported_media_types = {MediaType.EBOOK}
    requires_cf_bypass = False
    supports_member_key = False
    supports_authentication = False

    async def search(
        self,
        query: str,
        media_type: MediaType,
        filters: SearchFilters,
        limit: int = 50,
    ) -> list[SearchResult]:
        return [
            SearchResult(
                external_id="fake-1",
                title=f"Fake result for {query}",
                author="Test Author",
                year=2026,
                format="epub",
                language="en",
                size_bytes=1024,
                quality_score=42.0,
                source_id=self.id,
                media_type=media_type,
                metadata={},
            )
        ]

    async def get_download_info(
        self,
        external_id: str,
        media_type: MediaType,
        query_hint: str | None = None,  # noqa: ARG002
    ) -> DownloadInfo:
        return DownloadInfo(
            download_url="http://fake/placeholder.epub",
            size_bytes=1024,
            content_type="application/epub+zip",
            filename_hint=f"{external_id}.epub",
            extra_headers={},
        )

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            status=AdapterHealth.HEALTHY,
            reason=None,
            message=None,
            checked_at=dt.datetime.now(dt.UTC),
        )

    def get_config_schema(self) -> ConfigSchema:
        return ConfigSchema(fields=[])

    async def get_quota_status(self) -> QuotaStatus | None:
        return None
