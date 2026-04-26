"""Khinsider source adapter — video-game soundtracks via downloads.khinsider.com.

KHInsider hosts MP3 (and sometimes FLAC) recordings of video-game
soundtracks across thousands of games. No login, no Cloudflare for
the listing pages, plain HTML scraping.

Search:    GET https://downloads.khinsider.com/search?search=<q>
                  → table of matching album / game pages with link
                    to /game-soundtracks/album/<slug>.
Download:  GET /game-soundtracks/album/<slug>
                  → table of tracks with /game-soundtracks/album/<slug>/<track>.mp3
           GET that track page
                  → a `<a href="https://eta.vgmtreasurechest.com/...">`
                    direct MP3 URL to the audio file.

Single-file model: each search result is one **album** (game OST),
and ``get_download_info`` resolves to the **first track** of that
album. The user gets a representative sample — full albums are not
shipped because Grabarr's data model is single-file. Operators who
want the full album can search with track-specific terms or download
individual tracks one at a time.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any
from urllib.parse import quote_plus, unquote, urljoin

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

_log = setup_logger(__name__)

_KHI_BASE = "https://downloads.khinsider.com"

# A typical OST track is ~3-5 MB at 128 kbps MP3. Search results don't
# expose track sizes — we set a placeholder so Prowlarr's listing isn't
# rendered as 0 B; the real size lands on the Download row post-fetch.
_TYPICAL_TRACK_SIZE = 4 * 1024 * 1024

# Year hint: most VGM tracks are vintage. Default to 2000 so Prowlarr
# doesn't render "0 minute" age. Adapters can override per-album when
# the listing exposes a year (Khinsider's table sometimes does).
_DEFAULT_YEAR = 2000


@register_adapter
class KhinsiderAdapter:
    """KHInsider video-game soundtracks (album-level search, first-track download)."""

    id = "khinsider"
    display_name = "KHInsider"
    supported_media_types = {MediaType.MUSIC}
    requires_cf_bypass = False
    supports_member_key = False
    supports_authentication = False

    def __init__(self) -> None:
        rate_limiter.configure(self.id, "search", per_minute=20)
        rate_limiter.configure(self.id, "download", per_minute=15)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                ),
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
        if media_type != MediaType.MUSIC:
            return []
        q = query.strip()
        if len(q) < 3:
            return []

        await rate_limiter.acquire(self.id, "search")
        url = f"{_KHI_BASE}/search?search={quote_plus(q)}"
        async with self._client() as client:
            try:
                r = await client.get(url)
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if 500 <= exc.response.status_code < 600:
                    raise AdapterServerError(
                        f"khinsider HTTP {exc.response.status_code}"
                    ) from exc
                raise AdapterConnectivityError(str(exc)) from exc
            except httpx.HTTPError as exc:
                raise AdapterConnectivityError(str(exc)) from exc

        results = _parse_search_results(r.text, q, self.id)
        return results[:limit]

    # ---- download -------------------------------------------------------

    async def get_download_info(
        self,
        external_id: str,
        media_type: MediaType,
        query_hint: str | None = None,
    ) -> DownloadInfo:
        # external_id is the album slug (e.g. "super-mario-64")
        if not external_id or "/" in external_id:
            raise AdapterNotFound(f"khinsider: invalid album slug {external_id!r}")
        await rate_limiter.acquire(self.id, "download")

        async with self._client() as client:
            # 1. Fetch the album page to discover tracks.
            album_url = f"{_KHI_BASE}/game-soundtracks/album/{external_id}"
            try:
                r = await client.get(album_url)
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise AdapterNotFound(
                        f"khinsider album {external_id} not found"
                    ) from exc
                raise AdapterConnectivityError(str(exc)) from exc
            except httpx.HTTPError as exc:
                raise AdapterConnectivityError(str(exc)) from exc

            track_path = _pick_track_path(r.text, query_hint)
            if not track_path:
                raise AdapterNotFound(
                    f"khinsider album {external_id}: no MP3 track rows on page"
                )

            # 2. Fetch the track page to find the actual MP3 URL.
            track_page_url = urljoin(_KHI_BASE, track_path)
            try:
                rt = await client.get(track_page_url)
                rt.raise_for_status()
            except httpx.HTTPError as exc:
                raise AdapterConnectivityError(str(exc)) from exc

            mp3_url = _extract_mp3_url(rt.text)
            if not mp3_url:
                raise AdapterNotFound(
                    f"khinsider track page {track_page_url} has no MP3 link "
                    "(layout likely changed)"
                )

        # Filename hint from the URL tail.
        try:
            tail = mp3_url.rsplit("/", 1)[-1]
            filename = unquote(tail) or f"{external_id}.mp3"
        except Exception:
            filename = f"{external_id}.mp3"

        return DownloadInfo(
            download_url=mp3_url,
            size_bytes=None,
            content_type="audio/mpeg",
            filename_hint=filename,
            extra_headers={
                # Khinsider's CDN responds with 403 if the Referer is missing.
                "Referer": track_page_url,
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                ),
            },
        )

    # ---- health + config ------------------------------------------------

    async def health_check(self) -> HealthStatus:
        now = dt.datetime.now(dt.UTC)
        try:
            async with self._client() as client:
                r = await client.get(f"{_KHI_BASE}/", timeout=10.0)
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
        return ConfigSchema(fields=[])

    async def get_quota_status(self) -> QuotaStatus | None:
        return None


# --------------------------------------------------------------------------
# Pure parsers
# --------------------------------------------------------------------------

_ALBUM_LINK_RE = re.compile(r"^/game-soundtracks/album/([^/]+)/?$")
_TRACK_LINK_RE = re.compile(r"^/game-soundtracks/album/[^/]+/.+\.mp3$")


def _parse_search_results(
    html: str,
    query: str,
    source_id: str,
) -> list[SearchResult]:
    """Parse a /search?search=<q> page into album-level SearchResults."""
    soup = BeautifulSoup(html, "lxml")
    out: list[SearchResult] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        m = _ALBUM_LINK_RE.match(link["href"])
        if not m:
            continue
        slug = m.group(1)
        if slug in seen:
            continue
        seen.add(slug)
        title = link.get_text(strip=True)
        if not title or len(title) < 2:
            continue
        # Try to find a year on the same row (Khinsider's table sometimes
        # has a "Year" column near the album link). We scan adjacent text.
        year = _DEFAULT_YEAR
        row = link.find_parent("tr") or link.parent
        if row is not None:
            text = row.get_text(" ", strip=True)
            ymatch = re.search(r"\b(19[5-9]\d|20\d{2})\b", text)
            if ymatch:
                y = int(ymatch.group(1))
                if 1950 <= y <= 2099:
                    year = y
        # Try to find a "platform" tag (NES, PS1, etc) for the metadata.
        platform: str | None = None
        if row is not None:
            for img in row.find_all("img"):
                alt = (img.get("alt") or "").strip()
                if alt and 2 <= len(alt) <= 12 and " " not in alt:
                    platform = alt
                    break

        score = 50.0 + score_title_relevance(title, query)
        out.append(
            SearchResult(
                external_id=slug,
                title=title,
                author=None,  # composer often absent at search level
                year=year,
                format="mp3",
                language=None,  # VGM tracks are language-agnostic
                size_bytes=_TYPICAL_TRACK_SIZE,
                quality_score=score,
                source_id=source_id,
                media_type=MediaType.MUSIC,
                metadata={
                    "khinsider_slug": slug,
                    "platform": platform,
                    "size_is_estimate": True,
                    # Show the platform as the [Console] tag in titles.
                    "console_label": platform,
                },
            )
        )
    out.sort(key=lambda r: r.quality_score, reverse=True)
    return out


def _pick_track_path(album_html: str, query_hint: str | None) -> str | None:
    """Pick the best track URL from an album page.

    If ``query_hint`` is provided and matches a track filename
    substring, prefer that. Otherwise fall back to the first MP3.
    """
    soup = BeautifulSoup(album_html, "lxml")
    candidates: list[str] = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if _TRACK_LINK_RE.match(href):
            candidates.append(href)
    if not candidates:
        return None

    if query_hint:
        hint = query_hint.lower()
        for path in candidates:
            tail = path.rsplit("/", 1)[-1].lower()
            if hint in unquote(tail):
                return path
    return candidates[0]


def _extract_mp3_url(track_page_html: str) -> str | None:
    """Find the direct MP3 URL on a Khinsider track page."""
    soup = BeautifulSoup(track_page_html, "lxml")
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.lower().endswith(".mp3") and href.startswith("http"):
            return href
    # Fallback: <audio src=...>
    audio = soup.find("audio")
    if audio is not None:
        src = audio.get("src")
        if src and src.lower().endswith(".mp3"):
            return src
    return None
