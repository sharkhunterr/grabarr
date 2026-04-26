"""AudioBookBay source adapter — magnet passthrough.

AudioBookBay (audiobookbay.lu by default; other mirrors exist) is a
torrent-only audiobook indexer. Each result links to a detail page
that exposes a ``magnet:?xt=urn:btih:…`` link; there is no HTTP
download for the audio itself — pieces flow over BitTorrent.

Search:    GET https://<host>/?s=<query>
                  → HTML post listings with title / author / language /
                    format / file-size / detail URL.
Download:  GET <detail_url>
                  → HTML containing one ``<a href="magnet:…">`` element.

Because Grabarr's normal pipeline (HTTP download → generate .torrent)
doesn't fit a torrent-only source, this adapter takes the **magnet
passthrough** path:

  - ``get_download_info()`` returns a :class:`DownloadInfo` with
    ``magnet_uri`` populated. ``download_url`` is set to the same
    magnet for symmetry but is never fetched by the download manager.
  - The download service short-circuits on ``magnet_uri`` and asks the
    torznab download endpoint to emit an HTTP 302 redirect.
  - Prowlarr / *arr / the torrent client follow the redirect and
    consume the magnet natively.

Configuration:
  - ``sources.audiobookbay.hostname`` — the ABB mirror to query
    (default: ``audiobookbay.lu``). Operators flip this when ABB
    shuffles domains.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup

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
from grabarr.core.settings_service import get_sync

_log = setup_logger(__name__)

_DEFAULT_HOST = "audiobookbay.lu"

_LANG_MAP = {
    "english": "en", "spanish": "es", "french": "fr", "german": "de",
    "italian": "it", "portuguese": "pt", "russian": "ru", "japanese": "ja",
    "chinese": "zh", "dutch": "nl", "swedish": "sv", "polish": "pl",
}

_LANGUAGE_RE = re.compile(r"Language:\s*([A-Za-z]+)")
_FORMAT_RE = re.compile(r"Format:\s*([A-Za-z0-9]+)")
_SIZE_RE = re.compile(r"File\s*Size:\s*([\d.]+)\s*([A-Za-z]+)")
_POSTED_RE = re.compile(r"Posted:\s*\d+\s+[A-Za-z]+\s+(\d{4})")
_MAGNET_RE = re.compile(r"magnet:\?[^\"'\s<>]+", re.IGNORECASE)

_SIZE_UNITS = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4}


@register_adapter
class AudioBookBayAdapter:
    """AudioBookBay (torrent-only audiobooks via magnet passthrough)."""

    id = "audiobookbay"
    display_name = "AudioBookBay"
    supported_media_types = {MediaType.AUDIOBOOK}
    requires_cf_bypass = False
    supports_member_key = False
    supports_authentication = False

    def __init__(self) -> None:
        rate_limiter.configure(self.id, "search", per_minute=15)
        rate_limiter.configure(self.id, "download", per_minute=15)

    def _hostname(self) -> str:
        h = (get_sync("sources.audiobookbay.hostname", "") or "").strip()
        return h or _DEFAULT_HOST

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=45.0, write=30.0, pool=30.0),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
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
        if media_type != MediaType.AUDIOBOOK:
            return []
        q = query.strip()
        if not q:
            return []

        await rate_limiter.acquire(self.id, "search")
        host = self._hostname()
        url = f"https://{host}/?s={quote_plus(q)}"
        async with self._client() as client:
            try:
                r = await client.get(url)
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if 500 <= exc.response.status_code < 600:
                    raise AdapterServerError(
                        f"audiobookbay HTTP {exc.response.status_code}"
                    ) from exc
                raise AdapterConnectivityError(str(exc)) from exc
            except httpx.HTTPError as exc:
                raise AdapterConnectivityError(str(exc)) from exc

        results = _parse_search(r.text, host, q, self.id)

        # Apply user-supplied language filter post-parse.
        wanted = {lang.lower() for lang in (filters.languages or [])}
        if wanted:
            results = [r for r in results if not r.language or r.language.lower() in wanted]
        results.sort(key=lambda x: x.quality_score, reverse=True)
        return results[:limit]

    # ---- download (magnet passthrough) ----------------------------------

    async def get_download_info(
        self,
        external_id: str,
        media_type: MediaType,
        query_hint: str | None = None,
    ) -> DownloadInfo:
        # external_id is the detail page path (e.g.
        # ``/abridged/the-foo-bar-by-jane-doe/``).
        if not external_id or not external_id.startswith("/"):
            raise AdapterNotFound(f"audiobookbay: bad external_id {external_id!r}")
        await rate_limiter.acquire(self.id, "download")
        host = self._hostname()
        detail_url = urljoin(f"https://{host}", external_id)

        async with self._client() as client:
            try:
                r = await client.get(detail_url)
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise AdapterNotFound(
                        f"audiobookbay {detail_url} not found"
                    ) from exc
                raise AdapterConnectivityError(str(exc)) from exc
            except httpx.HTTPError as exc:
                raise AdapterConnectivityError(str(exc)) from exc

        magnet = _extract_magnet(r.text)
        if not magnet:
            raise AdapterNotFound(
                f"audiobookbay detail page {detail_url} has no magnet "
                "(likely DMCA-removed or layout changed)"
            )

        # Filename hint from the detail-page slug — torrent clients use
        # this to pick a friendly display name.
        slug_tail = external_id.rstrip("/").rsplit("/", 1)[-1] or "audiobook"
        filename = f"{slug_tail}.torrent"

        return DownloadInfo(
            download_url=magnet,
            size_bytes=None,
            content_type="application/x-bittorrent",
            filename_hint=filename,
            magnet_uri=magnet,
        )

    # ---- health + config ------------------------------------------------

    async def health_check(self) -> HealthStatus:
        now = dt.datetime.now(dt.UTC)
        host = self._hostname()
        try:
            async with self._client() as client:
                r = await client.get(f"https://{host}/", timeout=15.0)
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
                    key="sources.audiobookbay.hostname",
                    label="ABB hostname",
                    field_type="text",
                    options=None,
                    secret=False,
                    required=False,
                    help_text=(
                        f"AudioBookBay mirror hostname. Default: {_DEFAULT_HOST}. "
                        "Update when ABB rotates domains."
                    ),
                ),
            ]
        )

    async def get_quota_status(self) -> QuotaStatus | None:
        return None


# --------------------------------------------------------------------------
# Pure parsers
# --------------------------------------------------------------------------


def _parse_search(
    html: str,
    host: str,
    query: str,
    source_id: str,
) -> list[SearchResult]:
    """Parse ABB's search page into SearchResults."""
    soup = BeautifulSoup(html, "lxml")
    out: list[SearchResult] = []
    seen_paths: set[str] = set()

    # ABB's posts are wrapped in <div class="post"> with an <h2><a> for
    # the title. Some templates use article tags; we accept both.
    for post in soup.select("div.post, article"):
        link = post.find("a", href=True)
        if not link:
            continue
        href = link.get("href", "")
        # Detail URLs are absolute or root-relative path under the host.
        path = _normalise_path(href, host)
        if not path or path in seen_paths:
            continue
        # Skip pagination / author / category links.
        if path.startswith(("/page/", "/author/", "/category/", "/tag/")):
            continue
        seen_paths.add(path)
        title = link.get_text(strip=True)
        if not title or len(title) < 2:
            continue

        text_blob = post.get_text(" ", strip=True)
        format_ = _first(_FORMAT_RE, text_blob)
        language_raw = _first(_LANGUAGE_RE, text_blob)
        language = _LANG_MAP.get((language_raw or "").lower()) if language_raw else None
        size_match = _SIZE_RE.search(text_blob)
        size_bytes: int | None = None
        if size_match:
            try:
                num = float(size_match.group(1))
                unit = size_match.group(2).lower()
                size_bytes = int(num * _SIZE_UNITS.get(unit, 1))
            except (TypeError, ValueError):
                size_bytes = None
        year: int | None = None
        posted_match = _POSTED_RE.search(text_blob)
        if posted_match:
            try:
                year = int(posted_match.group(1))
            except (TypeError, ValueError):
                year = None

        # Author: ABB sometimes embeds it in the title (Title - Author).
        author: str | None = None
        if " - " in title:
            t_part, a_part = title.rsplit(" - ", 1)
            if t_part.strip() and a_part.strip():
                title = t_part.strip()
                author = a_part.strip()

        score = 50.0 + score_title_relevance(title, query)
        out.append(
            SearchResult(
                external_id=path,
                title=title,
                author=author,
                year=year,
                format=(format_ or "mp3").lower(),
                language=language,
                size_bytes=size_bytes,
                quality_score=score,
                source_id=source_id,
                media_type=MediaType.AUDIOBOOK,
                metadata={
                    "abb_detail_url": f"https://{host}{path}",
                    "delivery": "magnet",  # signal to UI / downstream code
                },
            )
        )
    out.sort(key=lambda r: r.quality_score, reverse=True)
    return out


def _normalise_path(href: str, host: str) -> str | None:
    """Reduce an ABB result URL to its host-relative path."""
    if not href:
        return None
    if href.startswith(f"https://{host}"):
        return href[len(f"https://{host}"):] or "/"
    if href.startswith(f"http://{host}"):
        return href[len(f"http://{host}"):] or "/"
    if href.startswith("/"):
        return href
    # Some templates emit relative paths; reject anything off-host.
    if href.startswith(("http://", "https://", "//")):
        return None
    return "/" + href.lstrip("/")


def _extract_magnet(html: str) -> str | None:
    m = _MAGNET_RE.search(html)
    if not m:
        return None
    return m.group(0)


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1).strip() if m else None
