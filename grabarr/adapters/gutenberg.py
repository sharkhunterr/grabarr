"""Project Gutenberg source adapter — public domain ebooks via Gutendex.

Gutendex (https://gutendex.com) is a free, well-maintained JSON API
proxy in front of Project Gutenberg's catalog. No login, no rate
limits beyond reasonable use, no Cloudflare.

Search:    GET https://gutendex.com/books?search=<q>
Download:  the search payload itself carries per-format URLs in
           ``formats`` (epub, mobi, kf8, html, txt, plaintext, …).

We pick the best available format following the user's
``preferred_formats`` filter, falling back to a sensible ladder
(epub3 > epub > html > txt). The ``external_id`` is the Gutendex
numeric book id.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

from grabarr.adapters._rom_helpers import score_title_relevance
from grabarr.adapters.base import (
    AdapterConnectivityError,
    AdapterNotFound,
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
from grabarr.core.enums import AdapterHealth, UnhealthyReason
from grabarr.core.logging import setup_logger
from grabarr.core.rate_limit import rate_limiter
from grabarr.core.registry import register_adapter

_log = setup_logger(__name__)

_API_BASE = "https://gutendex.com/books"

# Format-key ladder. Gutendex returns MIME-prefixed keys like
# ``application/epub+zip`` or ``text/html; charset=utf-8`` — we match
# by substring against the user's preferred formats, then fall back to
# this ladder.
_FORMAT_LADDER: list[tuple[str, str]] = [
    # (substring to match in the format key, extension to record)
    ("epub", "epub"),
    ("x-mobipocket", "mobi"),
    ("kf8", "azw3"),
    ("html", "html"),
    ("plain", "txt"),
]

# Approximate size per format. Gutendex doesn't return file sizes in its
# search payload and HEAD-ing each result would multiply HTTP calls by N.
# These are conservative medians that prevent Prowlarr / Readarr from
# rendering "0 B" — the real size lands on the Download row after fetch.
_TYPICAL_SIZE: dict[str, int] = {
    "epub": 1 * 1024 * 1024,        # ~1 MB
    "mobi": 1 * 1024 * 1024,
    "azw3": 1 * 1024 * 1024,
    "html": 500 * 1024,             # ~500 KB
    "txt": 400 * 1024,              # ~400 KB
}


@register_adapter
class GutenbergAdapter:
    """Project Gutenberg via Gutendex (public domain ebooks)."""

    id = "gutenberg"
    display_name = "Project Gutenberg"
    supported_media_types = {MediaType.EBOOK}
    requires_cf_bypass = False
    supports_member_key = False
    supports_authentication = False

    def __init__(self) -> None:
        rate_limiter.configure(self.id, "search", per_minute=30)
        rate_limiter.configure(self.id, "download", per_minute=30)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0),
            headers={"User-Agent": "Grabarr/1.x (+https://github.com/sharkhunterr/grabarr)"},
            follow_redirects=True,
        )

    # ---- search ---------------------------------------------------------

    async def search(
        self,
        query: str,
        media_type: MediaType,
        filters: SearchFilters,
        limit: int = 50,
    ) -> list[SearchResult]:
        if media_type != MediaType.EBOOK:
            return []
        q = query.strip()
        if not q:
            return []

        await rate_limiter.acquire(self.id, "search")
        params: dict[str, Any] = {"search": q}
        if filters.languages:
            # Gutendex accepts comma-separated ISO 639-1 codes.
            params["languages"] = ",".join(filters.languages)

        async with self._client() as client:
            try:
                r = await client.get(_API_BASE, params=params)
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if 500 <= exc.response.status_code < 600:
                    raise AdapterServerError(
                        f"gutendex HTTP {exc.response.status_code}"
                    ) from exc
                raise AdapterConnectivityError(str(exc)) from exc
            except httpx.HTTPError as exc:
                raise AdapterConnectivityError(str(exc)) from exc

        try:
            payload = r.json()
        except ValueError as exc:
            raise AdapterServerError(f"gutendex returned non-JSON: {exc}") from exc

        out: list[SearchResult] = []
        for book in payload.get("results", []) or []:
            sr = _build_search_result(book, q, filters, self.id)
            if sr is not None:
                out.append(sr)
        out.sort(key=lambda r: r.quality_score, reverse=True)
        return out[:limit]

    # ---- download -------------------------------------------------------

    async def get_download_info(
        self,
        external_id: str,
        media_type: MediaType,
        query_hint: str | None = None,
    ) -> DownloadInfo:
        if not external_id.isdigit():
            raise AdapterNotFound(f"gutenberg: invalid id {external_id!r}")
        await rate_limiter.acquire(self.id, "download")
        async with self._client() as client:
            try:
                r = await client.get(f"{_API_BASE}/{external_id}")
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise AdapterNotFound(
                        f"gutenberg book {external_id} not found"
                    ) from exc
                if 500 <= exc.response.status_code < 600:
                    raise AdapterServerError(
                        f"gutendex HTTP {exc.response.status_code}"
                    ) from exc
                raise AdapterConnectivityError(str(exc)) from exc
            except httpx.HTTPError as exc:
                raise AdapterConnectivityError(str(exc)) from exc

        book = r.json()
        url, ext = _pick_format(book.get("formats", {}) or {}, preferred=None)
        if not url:
            raise AdapterNotFound(
                f"gutenberg book {external_id}: no downloadable format found"
            )
        title = (book.get("title") or f"gutenberg-{external_id}").strip()
        # Gutenberg URLs sometimes lack a clean extension when they're
        # served as zipped epubs; force one based on what we picked.
        filename = f"{_safe_filename(title)}-{external_id}.{ext}"
        return DownloadInfo(
            download_url=url,
            size_bytes=None,
            content_type=None,
            filename_hint=filename,
        )

    # ---- health + config ------------------------------------------------

    async def health_check(self) -> HealthStatus:
        now = dt.datetime.now(dt.UTC)
        try:
            async with self._client() as client:
                r = await client.get(f"{_API_BASE}/?search=ping", timeout=10.0)
            if r.status_code < 500:
                return HealthStatus(
                    status=AdapterHealth.HEALTHY,
                    reason=None,
                    message=f"HTTP {r.status_code}",
                    checked_at=now,
                )
            return HealthStatus(
                status=AdapterHealth.DEGRADED,
                reason=UnhealthyReason.SERVER_ERROR_5XX,
                message=f"HTTP {r.status_code}",
                checked_at=now,
            )
        except httpx.HTTPError as exc:
            return HealthStatus(
                status=AdapterHealth.UNHEALTHY,
                reason=UnhealthyReason.CONNECTIVITY,
                message=str(exc)[:200],
                checked_at=now,
            )

    def get_config_schema(self) -> ConfigSchema:
        return ConfigSchema(
            fields=[
                ConfigField(
                    key="sources.gutenberg.preferred_formats",
                    label="Preferred formats",
                    field_type="text",
                    options=None,
                    secret=False,
                    required=False,
                    help_text=(
                        "Comma-separated format extensions in priority order "
                        "(e.g. 'epub,mobi,html'). Blank = epub > mobi > html > txt."
                    ),
                ),
            ]
        )

    async def get_quota_status(self) -> QuotaStatus | None:
        return None


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


def _build_search_result(
    book: dict[str, Any],
    query: str,
    filters: SearchFilters,
    source_id: str,
) -> SearchResult | None:
    title = (book.get("title") or "").strip()
    if not title:
        return None
    book_id = book.get("id")
    if not isinstance(book_id, int):
        return None

    formats = book.get("formats", {}) or {}
    pref = filters.preferred_formats[0] if filters.preferred_formats else None
    _, ext = _pick_format(formats, preferred=pref)
    if not ext:
        # No usable format — skip; Gutenberg always has at least html/txt
        # but be defensive against catalog edge cases.
        return None

    authors = book.get("authors") or []
    author = None
    if authors and isinstance(authors[0], dict):
        author = authors[0].get("name") or None

    languages = book.get("languages") or []
    language = languages[0] if languages else None

    score = 50.0 + score_title_relevance(title, query)
    # Tiebreaker: more downloads = more popular = better default order.
    download_count = book.get("download_count") or 0
    if isinstance(download_count, int) and download_count > 0:
        score += min(10.0, download_count / 5000.0)

    return SearchResult(
        external_id=str(book_id),
        title=title,
        author=author,
        year=None,  # Gutendex doesn't expose publication year reliably
        format=ext,
        language=language,
        size_bytes=_TYPICAL_SIZE.get(ext),
        quality_score=score,
        source_id=source_id,
        media_type=MediaType.EBOOK,
        metadata={
            "gutenberg_id": book_id,
            "subjects": (book.get("subjects") or [])[:5],
            "download_count": download_count,
            "size_is_estimate": True,
        },
    )


def _pick_format(
    formats: dict[str, str],
    preferred: str | None,
) -> tuple[str | None, str | None]:
    """Pick the best (url, extension) pair from Gutendex's ``formats`` dict.

    Gutendex keys look like ``application/epub+zip``, ``text/html``,
    ``application/x-mobipocket-ebook``, etc. We match by substring.
    """
    if not formats:
        return None, None
    # ``preferred`` is a bare extension like "epub". Match it first.
    if preferred:
        pref_low = preferred.lower().lstrip(".")
        for substr, ext in _FORMAT_LADDER:
            if ext != pref_low:
                continue
            url = _find_format_url(formats, substr)
            if url:
                return url, ext
    # Fall back to the standard ladder.
    for substr, ext in _FORMAT_LADDER:
        url = _find_format_url(formats, substr)
        if url:
            return url, ext
    return None, None


def _find_format_url(formats: dict[str, str], substr: str) -> str | None:
    """Return the URL of the first MIME-key whose name contains ``substr``.

    Skips the ``.zip`` wrapped variants Gutendex sometimes lists for
    images-included epubs — those tend to be larger and a strict
    superset of the regular epub.
    """
    fallback: str | None = None
    for key, url in formats.items():
        if substr not in key.lower():
            continue
        if not isinstance(url, str):
            continue
        if url.endswith(".zip"):
            fallback = url
            continue
        return url
    return fallback


def _safe_filename(title: str) -> str:
    """Slug a title down to filesystem-safe ASCII-ish."""
    out = []
    for ch in title:
        if ch.isalnum() or ch in (" ", "-", "_"):
            out.append(ch)
        else:
            out.append(" ")
    return "_".join("".join(out).split())[:80] or "book"
