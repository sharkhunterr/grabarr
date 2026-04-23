"""Internet Archive adapter — Grabarr-native (not vendored).

Shelfmark does not cover Internet Archive, so this adapter is fresh
Grabarr code per spec FR-1.4. Search goes through
``archive.org/advancedsearch.php``; metadata + file selection goes
through ``archive.org/metadata/{identifier}``.

File-selection rubric is a per-MediaType preference ladder (research §R-4).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import httpx

from grabarr import __version__
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

_IA_BASE = "https://archive.org"

# --------------------------------------------------------------------------
# File-preference ladders (spec FR-1.4 + research R-4)
#
# Each entry scores an IA ``format`` string. First match wins; ties are
# broken by extension hint (for when IA lists the same format at different
# bit-rates).
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FilePref:
    format_name: str
    score: int
    ext_hint: str | None = None


_LADDERS: dict[MediaType, list[FilePref]] = {
    MediaType.EBOOK: [
        FilePref("EPUB", 100, "epub"),
        FilePref("Text PDF", 80, "pdf"),
        FilePref("Image Container PDF", 75, "pdf"),
        FilePref("DjVu", 50, "djvu"),
        FilePref("Single Page Processed JP2 ZIP", 30, "zip"),
    ],
    MediaType.AUDIOBOOK: [
        FilePref("VBR MP3", 100, "mp3"),
        FilePref("128Kbps MP3", 95, "mp3"),
        FilePref("64Kbps MP3", 90, "mp3"),
        FilePref("Ogg Vorbis", 70, "ogg"),
        FilePref("Flac", 60, "flac"),
    ],
    MediaType.MUSIC: [
        FilePref("Flac", 100, "flac"),
        FilePref("VBR MP3", 80, "mp3"),
        FilePref("128Kbps MP3", 60, "mp3"),
        FilePref("Ogg Vorbis", 50, "ogg"),
    ],
    MediaType.GAME_ROM: [
        FilePref("ZIP", 100, "zip"),
        FilePref("7z", 95, "7z"),
        FilePref("ROM", 90, None),
        FilePref("ISO Image", 90, "iso"),
    ],
    MediaType.VIDEO: [
        FilePref("h.264", 100, "mp4"),
        FilePref("MPEG4", 90, "mp4"),
        FilePref("Matroska", 85, "mkv"),
        FilePref("Ogg Video", 50, "ogv"),
    ],
    MediaType.SOFTWARE: [
        FilePref("ISO Image", 100, "iso"),
        FilePref("ZIP", 95, "zip"),
        FilePref("Executable", 90, "exe"),
    ],
    MediaType.MAGAZINE: [
        FilePref("Image Container PDF", 100, "pdf"),
        FilePref("Text PDF", 95, "pdf"),
        FilePref("Comic Book ZIP", 90, "cbz"),
    ],
    MediaType.PAPER: [
        FilePref("Text PDF", 100, "pdf"),
        FilePref("Image Container PDF", 90, "pdf"),
    ],
    MediaType.COMIC: [
        FilePref("Comic Book ZIP", 100, "cbz"),
        FilePref("Comic Book RAR", 95, "cbr"),
        FilePref("Image Container PDF", 80, "pdf"),
    ],
}

# IA ``format`` values we never want to hand to a torrent client.
_FORMAT_BLACKLIST: frozenset[str] = frozenset(
    {
        "Metadata",
        "Item Tile",
        "Thumbnail",
        "JPEG Thumb",
        "Spectrogram",
        "Item Image",
        "Reviews",
        "JSON",
        "Web ARChive ZIP",
        "Archive BitTorrent",  # torrent wrapper; we create our own
    }
)


def _score_file(entry: dict[str, Any], media_type: MediaType) -> int:
    fmt = entry.get("format", "")
    if fmt in _FORMAT_BLACKLIST:
        return -1
    ladder = _LADDERS.get(media_type, [])
    for pref in ladder:
        if pref.format_name == fmt:
            return pref.score
    return 0


def _media_type_to_ia_query(media_type: MediaType) -> str:
    """Map our MediaType to IA's ``mediatype`` field filter."""
    return {
        MediaType.EBOOK: "texts",
        MediaType.AUDIOBOOK: "audio",
        MediaType.COMIC: "texts",
        MediaType.MAGAZINE: "texts",
        MediaType.MUSIC: "audio",
        MediaType.SOFTWARE: "software",
        MediaType.PAPER: "texts",
        MediaType.GAME_ROM: "software",
        MediaType.VIDEO: "movies",
    }[media_type]


@register_adapter
class InternetArchiveAdapter:
    """Internet Archive source adapter (spec FR-1.4)."""

    id = "internet_archive"
    display_name = "Internet Archive"
    supported_media_types = {
        MediaType.EBOOK,
        MediaType.AUDIOBOOK,
        MediaType.COMIC,
        MediaType.MAGAZINE,
        MediaType.MUSIC,
        MediaType.SOFTWARE,
        MediaType.PAPER,
        MediaType.GAME_ROM,
        MediaType.VIDEO,
    }
    requires_cf_bypass = False
    supports_member_key = False
    supports_authentication = False

    def __init__(self, contact_email: str = "", user_agent_suffix: str = "") -> None:
        self._contact_email = contact_email
        self._ua_suffix = user_agent_suffix
        # Default-configure the bucket; actual limits come from settings later.
        rate_limiter.configure(self.id, "search", per_minute=30)
        rate_limiter.configure(self.id, "download", per_minute=30)

    # ---- helpers -------------------------------------------------------

    def _user_agent(self) -> str:
        base = f"Grabarr/{__version__}"
        if self._contact_email:
            base += f" ({self._contact_email})"
        if self._ua_suffix:
            base += f" {self._ua_suffix}"
        return base

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0),
            headers={"User-Agent": self._user_agent()},
        )

    # ---- primary API ---------------------------------------------------

    async def search(
        self,
        query: str,
        media_type: MediaType,
        filters: SearchFilters,
        limit: int = 50,
    ) -> list[SearchResult]:
        await rate_limiter.acquire(self.id, "search")
        q_parts = [query, f"mediatype:{_media_type_to_ia_query(media_type)}"]
        # Filter CDL-restricted items per spec FR-1.4.
        q_parts.append("-access-restricted-item:true")
        if filters.min_year is not None:
            q_parts.append(f"year:[{filters.min_year} TO 9999]")
        if filters.max_year is not None:
            q_parts.append(f"year:[0 TO {filters.max_year}]")
        if filters.languages:
            langs = " OR ".join(f"language:{lang}" for lang in filters.languages)
            q_parts.append(f"({langs})")
        if filters.extra_query_terms:
            q_parts.append(filters.extra_query_terms)

        params = [
            ("q", " AND ".join(q_parts)),
            ("fl[]", "identifier"),
            ("fl[]", "title"),
            ("fl[]", "creator"),
            ("fl[]", "year"),
            ("fl[]", "language"),
            ("fl[]", "item_size"),
            ("fl[]", "mediatype"),
            ("rows", str(limit)),
            ("output", "json"),
        ]

        try:
            async with self._client() as client:
                r = await client.get(f"{_IA_BASE}/advancedsearch.php", params=params)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as exc:
            if 500 <= exc.response.status_code < 600:
                raise AdapterServerError(f"IA advancedsearch returned {exc.response.status_code}") from exc
            raise AdapterConnectivityError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AdapterConnectivityError(str(exc)) from exc

        docs = data.get("response", {}).get("docs", [])
        results: list[SearchResult] = []
        for doc in docs:
            ident = doc.get("identifier")
            if not ident:
                continue
            title = doc.get("title") or ident
            creator = doc.get("creator")
            if isinstance(creator, list):
                creator = creator[0] if creator else None
            year = _coerce_year(doc.get("year"))
            lang = doc.get("language")
            if isinstance(lang, list):
                lang = lang[0] if lang else None
            size = doc.get("item_size")
            size_bytes = int(size) if isinstance(size, (int, str)) and str(size).isdigit() else None

            # Quality score: base 50 + up to +20 for title substring match.
            score = 50.0
            if query.lower() in title.lower():
                score += 20.0

            results.append(
                SearchResult(
                    external_id=ident,
                    title=title,
                    author=creator,
                    year=year,
                    format="?",  # resolved at get_download_info time
                    language=lang,
                    size_bytes=size_bytes,
                    quality_score=score,
                    source_id=self.id,
                    media_type=media_type,
                    metadata={"ia_mediatype": doc.get("mediatype")},
                )
            )
        return results

    async def get_download_info(
        self,
        external_id: str,
        media_type: MediaType,
    ) -> DownloadInfo:
        await rate_limiter.acquire(self.id, "download")
        try:
            async with self._client() as client:
                r = await client.get(f"{_IA_BASE}/metadata/{external_id}")
                r.raise_for_status()
                meta = r.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise AdapterNotFound(external_id) from exc
            if 500 <= exc.response.status_code < 600:
                raise AdapterServerError(f"IA metadata returned {exc.response.status_code}") from exc
            raise AdapterConnectivityError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AdapterConnectivityError(str(exc)) from exc

        files = meta.get("files", [])
        # Pick the best file per the ladder.
        best: tuple[int, dict[str, Any]] | None = None
        for entry in files:
            score = _score_file(entry, media_type)
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, entry)
        if best is None:
            raise AdapterNotFound(f"no suitable file in IA item {external_id}")

        entry = best[1]
        name = entry.get("name", "")
        server = meta.get("server", "archive.org")
        # IA serves item files at https://{server}/{dir}/{name} where
        # dir = meta["dir"].
        directory = meta.get("dir", f"/items/{external_id}")
        url = f"https://{server}{directory}/{name}"
        size_bytes: int | None = None
        raw_size = entry.get("size")
        if raw_size and str(raw_size).isdigit():
            size_bytes = int(raw_size)

        return DownloadInfo(
            download_url=url,
            size_bytes=size_bytes,
            content_type=entry.get("format"),
            filename_hint=name,
            extra_headers={"User-Agent": self._user_agent()},
        )

    async def health_check(self) -> HealthStatus:
        now = dt.datetime.now(dt.UTC)
        try:
            async with self._client() as client:
                r = await client.get(
                    f"{_IA_BASE}/services/search/v1/scrape",
                    params={"q": "title:*", "count": "1"},
                )
            status = (
                AdapterHealth.HEALTHY
                if r.status_code < 500
                else AdapterHealth.DEGRADED
            )
            return HealthStatus(
                status=status,
                reason=None if status == AdapterHealth.HEALTHY else UnhealthyReason.SERVER_ERROR_5XX,
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
                    key="sources.internet_archive.contact_email",
                    label="Contact email",
                    field_type="text",
                    options=None,
                    secret=False,
                    required=True,
                    help_text=(
                        "Per Internet Archive's API policy, identify yourself "
                        "in the User-Agent string. Use a reachable email."
                    ),
                ),
                ConfigField(
                    key="sources.internet_archive.user_agent_suffix",
                    label="User-Agent suffix",
                    field_type="text",
                    options=None,
                    secret=False,
                    required=False,
                    help_text="Optional extra suffix appended to every request's UA.",
                ),
            ]
        )

    async def get_quota_status(self) -> QuotaStatus | None:
        return None  # IA has no per-user daily quota relevant to Grabarr.


def _coerce_year(raw: Any) -> int | None:
    """IA's `year` field may arrive as int, str, or list."""
    if raw is None:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if raw is None:
        return None
    try:
        s = str(raw)[:4]
        return int(s)
    except (TypeError, ValueError):
        return None
