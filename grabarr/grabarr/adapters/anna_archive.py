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
import socket
from typing import Any
from urllib.parse import urlparse

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


def _probe_reachable(url: str, timeout: float = 3.0) -> bool:
    """Return ``True`` if ``url`` accepts TCP connections on its host:port.

    AA's slow_download pages often hand out mirrors (momot.rs, libgen.li,
    etc.) that DNS-resolve fine but whose hosts block traffic from many
    networks. A short connect-probe lets us fall through to the next
    candidate instead of burning the 60s httpx timeout later.
    """
    try:
        p = urlparse(url)
    except Exception:
        return False
    host = p.hostname
    if not host:
        return False
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class _ShelfmarkSourcePriorityOverride:
    """Context manager that temporarily narrows Shelfmark's source
    cascade to AA-only sub-sources.

    Shelfmark's :func:`_download_book` reads ``FAST_SOURCES_DISPLAY`` +
    ``SOURCE_PRIORITY`` from its config proxy every call. Swapping the
    values on the proxy's ``_BUILTIN_DEFAULTS`` for the duration of the
    download scopes the cascade without persisting anything to Grabarr's
    settings table.
    """

    _FAST_KEY = "FAST_SOURCES_DISPLAY"
    _SLOW_KEY = "SOURCE_PRIORITY"

    def __init__(
        self,
        proxy: Any,
        *,
        fast: list[dict[str, Any]],
        slow: list[dict[str, Any]],
    ) -> None:
        self._proxy = proxy
        self._fast = fast
        self._slow = slow
        self._saved: dict[str, Any] = {}

    def __enter__(self) -> "_ShelfmarkSourcePriorityOverride":
        defaults = getattr(self._proxy, "_BUILTIN_DEFAULTS", None)
        if isinstance(defaults, dict):
            self._saved[self._FAST_KEY] = defaults.get(self._FAST_KEY)
            self._saved[self._SLOW_KEY] = defaults.get(self._SLOW_KEY)
            defaults[self._FAST_KEY] = self._fast
            defaults[self._SLOW_KEY] = self._slow
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        defaults = getattr(self._proxy, "_BUILTIN_DEFAULTS", None)
        if isinstance(defaults, dict):
            for k, v in self._saved.items():
                if v is None:
                    defaults.pop(k, None)
                else:
                    defaults[k] = v


def _resolve_aa_candidate(url: str, direct_download: Any, title: str = "") -> str | None:
    """Resolve a single candidate URL from ``BrowseRecord.download_urls``
    to a direct file URL by delegating to Shelfmark's own resolver.

    Shelfmark's ``_get_download_url(link, title, ...)`` handles every
    supported source page: AA fast-download JSON API, AA slow_download
    with countdown + multi-strategy extraction, LibGen ads.php,
    Z-Library page, generic GET/Download anchor fallback. We just call
    it and return the result.
    """
    if not url:
        return None
    fn = getattr(direct_download, "_get_download_url", None)
    if not callable(fn):
        # No extractor — return the URL raw and hope it's direct.
        return url
    try:
        resolved = fn(url, title or url)
    except Exception as exc:  # noqa: BLE001
        # Propagate so the caller logs + tries the next candidate.
        raise exc
    if not resolved:
        return None
    return str(resolved)


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
                self._call_download_via_shelfmark, external_id, media_type
            )
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterServerError(
                f"{self.id} get_download_info failed: {exc}"
            ) from exc
        local_path, size, content_type, filename = result
        return DownloadInfo(
            # Placeholder URL — sync_download sees local_path and skips HTTP.
            download_url=f"file://{local_path}",
            size_bytes=size,
            content_type=content_type,
            filename_hint=filename,
            extra_headers={},
            local_path=local_path,
        )

    def _call_download_via_shelfmark(
        self, external_id: str, media_type: MediaType
    ) -> tuple["Path", int | None, str | None, str]:
        """Run Shelfmark's full ``_download_book`` cascade into a temp file.

        Shelfmark drives the complete pipeline — source-priority ordering
        (aa-fast → welib → aa-slow tiers → libgen → zlib → ipfs), CF
        bypass via the configured bypasser, mirror rotation, per-URL
        failure thresholds, and actual file-content streaming — all in
        ``_download_book``. Letting it write to a temp path and handing
        that file back to the orchestrator uses 100 % of the vendored
        logic instead of trying to reimplement it at the Grabarr side.
        """
        from pathlib import Path as _Path
        import tempfile

        from grabarr.vendor.shelfmark.release_sources.direct_download import (
            _download_book,
            get_book_info,
        )

        if not callable(get_book_info):
            raise AdapterError(
                f"{self.id}: vendored direct_download exposes no get_book_info"
            )
        book_info = get_book_info(external_id, fetch_download_count=False)

        # BrowseRecord has no ``filename`` — derive from id + format.
        fmt = (getattr(book_info, "format", "") or "").strip().lower() or "bin"
        safe_title = (getattr(book_info, "title", "") or external_id).strip()
        # Keep it short + filesystem-safe; sync_download sanitizes anyway.
        safe_title = safe_title[:120]
        filename_hint = f"{safe_title}.{fmt}" if safe_title else f"{external_id}.{fmt}"
        size_hint = _parse_human_size(getattr(book_info, "size", None))
        content_type_hint = None

        # Stage into a private temp dir. sync_download moves the file to
        # /downloads/ready/<token>/<sanitized-filename> after verification,
        # so we only need a stable landing spot here.
        tmp_root = _Path(tempfile.mkdtemp(prefix="grabarr-aa-"))
        target_path = tmp_root / filename_hint
        _log.info(
            "%s delegating to Shelfmark _download_book: md5=%s → %s",
            self.id, external_id, target_path,
        )

        # Let Shelfmark drive its full cascade — aa-fast (if donator key),
        # libgen (no CF needed), aa-slow-* (CF bypass), welib, zlib. This
        # is what Shelfmark-in-Docker does, and matches the user's
        # expected "it just works" behaviour. Grabarr's profile-level
        # source ordering is now only used for SEARCH result ordering;
        # once a grab picks an AA result, Shelfmark's internal cascade
        # is authoritative for the download.
        success_url = _download_book(book_info, target_path)
        if not success_url or not target_path.exists() or target_path.stat().st_size == 0:
            # Clean up the empty scratch dir so we don't leak anything.
            try:
                if target_path.exists():
                    target_path.unlink()
                tmp_root.rmdir()
            except OSError:
                pass
            raise AdapterError(
                f"{self.id}: Shelfmark cascade exhausted every source for "
                f"md5={external_id} (see preceding log entries for per-source "
                "failure reasons — typically CF-bypass unavailable or "
                "donator-key-only)"
            )

        _log.info(
            "%s Shelfmark delivered %s (%d bytes) via %s",
            self.id, target_path, target_path.stat().st_size, success_url,
        )
        return (target_path, size_hint, content_type_hint, filename_hint)

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
