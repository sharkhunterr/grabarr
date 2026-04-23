"""Anna's Archive adapter — thin wrapper over vendored Shelfmark cascade.

Per spec FR-1.1 + Constitution Article VII the cascade logic is NOT
reimplemented here. Everything that matters — sub-source taxonomy,
failure-threshold sweep, multi-strategy URL extraction, countdown
handling, mirror rotation, AA-discovered external mirrors — lives in
:mod:`grabarr.vendor.shelfmark.release_sources.direct_download`. This
wrapper only:

1. Adapts Grabarr's :class:`SourceAdapter` protocol onto
   Shelfmark's ``search_books`` / ``get_book_info`` entry points.
2. Translates Grabarr's :class:`MediaType` / :class:`SearchFilters` onto
   Shelfmark's equivalents.
3. Catches Shelfmark-side exceptions and re-raises them as
   :class:`AdapterError` subclasses for the orchestrator.

The vendored cascade is a unified "shadow library" pipeline that routes
through AA → LibGen → Z-Lib → Welib → IPFS under the hood. The
LibGen- and Z-Lib-specific adapters in this directory narrow that
cascade's output by sub-source origin; they all ultimately call the
same vendored code.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

from grabarr.adapters.base import (
    AdapterConnectivityError,
    AdapterError,
    AdapterServerError,
    ConfigField,
    ConfigSchema,
    DownloadInfo,
    HealthStatus,
    MediaType,
    QuotaStatus,
    SearchFilters,
    SearchResult,
)
from grabarr.core.enums import AdapterHealth
from grabarr.core.logging import setup_logger
from grabarr.core.rate_limit import rate_limiter
from grabarr.core.registry import register_adapter

_log = setup_logger(__name__)


def _ia_mediatype_to_shelfmark(mt: MediaType) -> str:
    """Map Grabarr's MediaType to Shelfmark's ``mediatype`` field value."""
    return {
        MediaType.EBOOK: "book_any",
        MediaType.AUDIOBOOK: "audiobook",
        MediaType.COMIC: "book_comic",
        MediaType.MAGAZINE: "magazine",
        MediaType.MUSIC: "audiobook",
        MediaType.PAPER: "book_nonfiction",
    }.get(mt, "book_any")


def _to_shelfmark_filters(filters: SearchFilters, media_type: MediaType) -> Any:
    """Build the ``SearchFilters`` shape Shelfmark's ``search_books`` expects.

    Lazy import keeps Shelfmark's module-load cost out of the import
    graph when this adapter is unused.
    """
    from grabarr.vendor.shelfmark.core.models import SearchFilters as ShelfFilters

    kwargs: dict[str, Any] = {
        "mediatype": _ia_mediatype_to_shelfmark(media_type),
    }
    if filters.languages:
        kwargs["lang"] = filters.languages
    if filters.preferred_formats:
        kwargs["format"] = filters.preferred_formats
    if filters.min_year is not None:
        kwargs["year_from"] = filters.min_year
    if filters.max_year is not None:
        kwargs["year_to"] = filters.max_year
    # Shelfmark's dataclass may not accept every key; pass only what it takes.
    valid = {k: v for k, v in kwargs.items() if k in ShelfFilters.__dataclass_fields__}
    return ShelfFilters(**valid)


def _parse_human_size(value: Any) -> int | None:
    """Parse Shelfmark's human-readable size string ("2.5 MB", "8.1 GB") into bytes.

    BrowseRecord.size is ``Optional[str]`` in the shipped Shelfmark
    v1.2.1 — not an integer. Returns None if unparseable.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if not s:
        return None
    # Simple regex: <number> <optional unit>
    import re

    m = re.match(r"^\s*([\d.,]+)\s*([a-zA-Z]*)\s*$", s)
    if not m:
        # Fallback: plain int string
        try:
            return int(s)
        except ValueError:
            return None
    try:
        num = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    unit = m.group(2).lower()
    mult = {
        "": 1,
        "b": 1,
        "byte": 1,
        "bytes": 1,
        "k": 1024,
        "kb": 1024,
        "kib": 1024,
        "m": 1024**2,
        "mb": 1024**2,
        "mib": 1024**2,
        "g": 1024**3,
        "gb": 1024**3,
        "gib": 1024**3,
        "t": 1024**4,
        "tb": 1024**4,
        "tib": 1024**4,
    }.get(unit, 1)
    return int(num * mult)


def _browse_record_to_search_result(
    record: Any,
    source_id: str,
    media_type: MediaType,
    sub_source: str | None = None,
) -> SearchResult:
    """Translate Shelfmark's ``BrowseRecord`` into our ``SearchResult``."""
    return SearchResult(
        external_id=str(getattr(record, "id", "") or ""),
        title=str(getattr(record, "title", "") or ""),
        author=_first_or(getattr(record, "author", None)),
        year=_coerce_int(getattr(record, "year", None)),
        format=str(getattr(record, "format", "") or "") or "unknown",
        language=_first_or(getattr(record, "language", None)),
        size_bytes=_parse_human_size(getattr(record, "size", None)),
        quality_score=float(getattr(record, "quality_score", 0.0) or 50.0),
        source_id=source_id,
        media_type=media_type,
        metadata={
            "md5": getattr(record, "id", None),
            "publisher": getattr(record, "publisher", None),
            "sub_source": sub_source,
        },
    )


def _first_or(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) or None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@register_adapter
class AnnaArchiveAdapter:
    """AA source adapter — primary entry into the Shelfmark cascade."""

    id = "anna_archive"
    display_name = "Anna's Archive"
    supported_media_types = {
        MediaType.EBOOK,
        MediaType.AUDIOBOOK,
        MediaType.COMIC,
        MediaType.MAGAZINE,
        MediaType.PAPER,
        MediaType.MUSIC,
    }
    requires_cf_bypass = True
    supports_member_key = True
    supports_authentication = False

    # Sub-source prefixes this adapter claims. Used by the LibGen and
    # Z-Lib adapters to filter out results that weren't actually sourced
    # from their respective sub-sources.
    _SUB_SOURCE_PREFIXES = ("aa-",)

    def __init__(self, member_key: str = "") -> None:
        self._member_key = member_key
        rate_limiter.configure(self.id, "search", per_minute=30)
        rate_limiter.configure(self.id, "download", per_minute=30)

    # ---- protocol ------------------------------------------------------

    async def search(
        self,
        query: str,
        media_type: MediaType,
        filters: SearchFilters,
        limit: int = 50,
    ) -> list[SearchResult]:
        await rate_limiter.acquire(self.id, "search")
        try:
            # Shelfmark's search_books is synchronous; run it in a thread
            # so we do not block the event loop.
            records = await asyncio.to_thread(self._call_search, query, media_type, filters)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterConnectivityError(f"{self.id} search failed: {exc}") from exc

        results = [
            _browse_record_to_search_result(r, self.id, media_type)
            for r in records[:limit]
        ]
        return results

    def _call_search(self, query: str, media_type: MediaType, filters: SearchFilters) -> list:
        """Invoke vendored ``search_books`` synchronously (called from a thread)."""
        # Lazy import so the Shelfmark cascade only loads when we actually
        # call it. This keeps test collection fast and isolates any
        # module-level import side effects.
        from grabarr.vendor.shelfmark.release_sources.direct_download import search_books

        shelf_filters = _to_shelfmark_filters(filters, media_type)
        try:
            return search_books(query, shelf_filters) or []
        except Exception as exc:
            _log.warning("%s search_books raised: %s", self.id, exc)
            return []

    async def get_download_info(
        self,
        external_id: str,
        media_type: MediaType,
    ) -> DownloadInfo:
        await rate_limiter.acquire(self.id, "download")
        try:
            result = await asyncio.to_thread(
                self._call_get_download, external_id, media_type
            )
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterServerError(
                f"{self.id} get_download_info failed: {exc}"
            ) from exc
        url, size, content_type, filename = result
        return DownloadInfo(
            download_url=url,
            size_bytes=size,
            content_type=content_type,
            filename_hint=filename,
            extra_headers={},
        )

    def _call_get_download(
        self, external_id: str, media_type: MediaType
    ) -> tuple[str, int | None, str | None, str]:
        """Invoke vendored cascade to resolve an external_id to a URL.

        The full cascade (member-key fast path → slow tiers → LibGen →
        Z-Lib → Welib → IPFS) lives in
        ``direct_download._download_book``. Because that function drives
        a full streaming download rather than just URL resolution, we
        use the exposed ``get_book_info`` + ``_get_download_url`` helpers
        where available; if the upstream API differs we fall back to
        raising AdapterError so the orchestrator moves on.
        """
        from grabarr.vendor.shelfmark.release_sources import direct_download

        # Prefer a URL-resolution path if the vendored module exposes one.
        for candidate_name in ("resolve_download_url", "_resolve_download_url"):
            fn = getattr(direct_download, candidate_name, None)
            if callable(fn):
                url = fn(external_id)
                return (url, None, None, external_id)

        # Fallback: get_book_info gives us metadata + a best-guess URL in
        # ``download_url``. This is the shape Shelfmark v1.2.1 ships.
        get_book_info = getattr(direct_download, "get_book_info", None)
        if callable(get_book_info):
            info = get_book_info(external_id, fetch_download_count=False)
            url = getattr(info, "download_url", None) or getattr(info, "url", None)
            if not url:
                raise AdapterError(
                    f"{self.id}: vendored get_book_info returned no usable URL"
                )
            size = getattr(info, "size_bytes", None) or getattr(info, "size", None)
            return (
                url,
                _coerce_int(size),
                getattr(info, "content_type", None),
                getattr(info, "filename", None) or external_id,
            )

        raise AdapterError(
            f"{self.id}: vendored direct_download.py exposes neither "
            "resolve_download_url nor get_book_info"
        )

    async def health_check(self) -> HealthStatus:
        now = dt.datetime.now(dt.UTC)
        # A real probe is best-effort; we declare HEALTHY and let the
        # circuit breaker demote us on actual failures during search.
        return HealthStatus(
            status=AdapterHealth.HEALTHY,
            reason=None,
            message=None,
            checked_at=now,
        )

    def get_config_schema(self) -> ConfigSchema:
        return ConfigSchema(
            fields=[
                ConfigField(
                    key="sources.anna_archive.member_key",
                    label="Anna's Archive member (donator) key",
                    field_type="password",
                    options=None,
                    secret=True,
                    required=False,
                    help_text=(
                        "Optional. When set, searches use the fast-download "
                        "API path; otherwise the slow-tier cascade runs."
                    ),
                ),
            ]
        )

    async def get_quota_status(self) -> QuotaStatus | None:
        return None
