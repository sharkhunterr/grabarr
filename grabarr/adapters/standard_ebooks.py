"""Standard Ebooks source adapter — public domain, retypeset.

Standard Ebooks (https://standardebooks.org) reissues public domain
classics with modern typography, proper covers, and clean metadata.
The catalog is a few thousand titles — small enough to fetch and
filter in-memory once.

Search:    GET https://standardebooks.org/feeds/opds/all   → Atom XML
Download:  per-entry ``<link rel="http://opds-spec.org/acquisition"
           type="application/epub+zip" href="…">`` carries the EPUB URL.

The OPDS feed is fetched once per process and cached for an hour;
"search" is then a substring filter against title + author + subjects.
This avoids hammering Standard Ebooks for every Prowlarr query.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

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

_SE_BASE = "https://standardebooks.org"
_SE_OPDS_ALL = f"{_SE_BASE}/feeds/opds/all"

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/terms/",
    "schema": "http://schema.org/",
}

# Typical Standard Ebooks epub3 size sits 0.5–3 MB. 1.5 MB is a
# reasonable median that beats the Prowlarr "0 B" rendering.
_TYPICAL_SIZE_EPUB = int(1.5 * 1024 * 1024)

# Cache the catalog for one hour to avoid hammering OPDS on every search.
_CATALOG_TTL = dt.timedelta(hours=1)


@dataclass(frozen=True)
class _CatalogEntry:
    external_id: str
    title: str
    author: str | None
    year: int | None
    language: str  # ISO 639-1
    epub_url: str
    subjects: tuple[str, ...]


@register_adapter
class StandardEbooksAdapter:
    """Standard Ebooks (public-domain retypeset)."""

    id = "standard_ebooks"
    display_name = "Standard Ebooks"
    supported_media_types = {MediaType.EBOOK}
    requires_cf_bypass = False
    supports_member_key = False
    supports_authentication = False

    def __init__(self) -> None:
        rate_limiter.configure(self.id, "search", per_minute=30)
        rate_limiter.configure(self.id, "download", per_minute=30)
        self._cache: list[_CatalogEntry] | None = None
        self._cache_at: dt.datetime | None = None
        self._cache_lock = asyncio.Lock()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=30.0),
            headers={"User-Agent": "Grabarr/1.x (+https://github.com/sharkhunterr/grabarr)"},
            follow_redirects=True,
        )

    # ---- catalog cache --------------------------------------------------

    async def _get_catalog(self) -> list[_CatalogEntry]:
        async with self._cache_lock:
            now = dt.datetime.now(dt.UTC)
            if (
                self._cache is not None
                and self._cache_at is not None
                and now - self._cache_at < _CATALOG_TTL
            ):
                return self._cache

            async with self._client() as client:
                try:
                    r = await client.get(_SE_OPDS_ALL)
                    r.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if 500 <= exc.response.status_code < 600:
                        raise AdapterServerError(
                            f"standard-ebooks HTTP {exc.response.status_code}"
                        ) from exc
                    raise AdapterConnectivityError(str(exc)) from exc
                except httpx.HTTPError as exc:
                    raise AdapterConnectivityError(str(exc)) from exc

            entries = _parse_opds(r.text)
            self._cache = entries
            self._cache_at = now
            _log.info("standard_ebooks: cached %d catalog entries", len(entries))
            return entries

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
        catalog = await self._get_catalog()

        # Language filter applied first.
        wanted_langs = {lang.lower() for lang in (filters.languages or [])}
        # Year filter.
        min_y = filters.min_year
        max_y = filters.max_year

        q_low = q.lower()
        matches: list[tuple[float, _CatalogEntry]] = []
        for entry in catalog:
            if wanted_langs and entry.language.lower() not in wanted_langs:
                continue
            if min_y is not None and entry.year is not None and entry.year < min_y:
                continue
            if max_y is not None and entry.year is not None and entry.year > max_y:
                continue
            haystack = " ".join(
                (
                    entry.title.lower(),
                    (entry.author or "").lower(),
                    " ".join(s.lower() for s in entry.subjects),
                )
            )
            if q_low not in haystack:
                # Token-level fallback: any query token present in haystack?
                tokens = [t for t in re.split(r"\W+", q_low) if len(t) > 2]
                if not tokens or not any(t in haystack for t in tokens):
                    continue
            score = 50.0 + score_title_relevance(entry.title, q)
            matches.append((score, entry))

        matches.sort(key=lambda pair: pair[0], reverse=True)
        out: list[SearchResult] = []
        for score, entry in matches[:limit]:
            out.append(
                SearchResult(
                    external_id=entry.external_id,
                    title=entry.title,
                    author=entry.author,
                    year=entry.year,
                    format="epub",
                    language=entry.language,
                    size_bytes=_TYPICAL_SIZE_EPUB,
                    quality_score=score,
                    source_id=self.id,
                    media_type=MediaType.EBOOK,
                    metadata={
                        "standard_ebooks_url": f"{_SE_BASE}/ebooks/{entry.external_id}",
                        "subjects": list(entry.subjects)[:5],
                        "size_is_estimate": True,
                    },
                )
            )
        return out

    # ---- download -------------------------------------------------------

    async def get_download_info(
        self,
        external_id: str,
        media_type: MediaType,
        query_hint: str | None = None,
    ) -> DownloadInfo:
        await rate_limiter.acquire(self.id, "download")
        catalog = await self._get_catalog()
        entry = next((e for e in catalog if e.external_id == external_id), None)
        if entry is None:
            raise AdapterNotFound(
                f"standard_ebooks: id {external_id!r} not in catalog"
            )
        # OPDS gives us a relative or absolute href; normalise.
        url = entry.epub_url
        if url.startswith("/"):
            url = _SE_BASE + url
        return DownloadInfo(
            download_url=url,
            size_bytes=None,
            content_type="application/epub+zip",
            filename_hint=f"{entry.external_id}.epub",
        )

    # ---- health + config ------------------------------------------------

    async def health_check(self) -> HealthStatus:
        now = dt.datetime.now(dt.UTC)
        try:
            async with self._client() as client:
                r = await client.head(_SE_BASE, timeout=10.0)
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
# OPDS Atom parser (pure)
# --------------------------------------------------------------------------


def _parse_opds(xml_text: str) -> list[_CatalogEntry]:
    """Parse Standard Ebooks' /feeds/opds/all Atom payload into entries."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise AdapterServerError(f"standard_ebooks OPDS parse error: {exc}") from exc

    out: list[_CatalogEntry] = []
    for entry_el in root.findall("atom:entry", _NS):
        title_el = entry_el.find("atom:title", _NS)
        title = (title_el.text or "").strip() if title_el is not None else ""
        if not title:
            continue

        # Author: first <author><name>
        author: str | None = None
        author_el = entry_el.find("atom:author/atom:name", _NS)
        if author_el is not None and author_el.text:
            author = author_el.text.strip()

        # Language: <dc:language>
        lang_el = entry_el.find("dc:language", _NS)
        language = (lang_el.text or "en").strip().lower() if lang_el is not None else "en"
        # OPDS sometimes uses "en-US" — keep first 2 chars.
        language = language.split("-", 1)[0] or "en"

        # Year: <schema:datePublished> or <dc:issued>
        year: int | None = None
        for tag in ("schema:datePublished", "dc:issued"):
            date_el = entry_el.find(tag, _NS)
            if date_el is not None and date_el.text:
                m = re.match(r"(\d{4})", date_el.text.strip())
                if m:
                    y = int(m.group(1))
                    if 1500 <= y <= 2100:
                        year = y
                        break

        # External ID: derive from <id> or canonical <link rel="alternate">
        external_id = ""
        id_el = entry_el.find("atom:id", _NS)
        if id_el is not None and id_el.text:
            # IDs look like ``https://standardebooks.org/ebooks/jane-austen/pride-and-prejudice``.
            tail = id_el.text.rstrip("/").rsplit("/ebooks/", 1)
            if len(tail) == 2:
                external_id = tail[1]
        if not external_id:
            continue

        # EPUB acquisition link.
        epub_url: str | None = None
        for link in entry_el.findall("atom:link", _NS):
            rel = link.get("rel", "")
            t = link.get("type", "")
            if "acquisition" in rel and "epub+zip" in t:
                href = link.get("href")
                if href:
                    epub_url = href
                    break
        if not epub_url:
            continue

        # Subjects (categories).
        subjects: list[str] = []
        for cat in entry_el.findall("atom:category", _NS):
            label = cat.get("label") or cat.get("term") or ""
            label = label.strip()
            if label:
                subjects.append(label)

        out.append(
            _CatalogEntry(
                external_id=external_id,
                title=title,
                author=author,
                year=year,
                language=language,
                epub_url=epub_url,
                subjects=tuple(subjects[:8]),
            )
        )
    return out
