"""Vimm's Lair source adapter — Grabarr-native HTML scraper.

vimm.net is a curated multi-console ROM site (NES, SNES, N64, GB/GBC/GBA,
DS, GC, Wii, Genesis, etc.). No login, no Cloudflare, but downloads sit
behind a per-game ``mediaId`` that has to be extracted from the vault
page's embedded ``let media=[…]`` JS array.

Search:    GET https://vimm.net/vault/?p=list&system=<sys>&q=<q>
                  → HTML table, each row links to /vault/<numeric_id>
Download:  GET https://dl3.vimm.net/?mediaId=<media_id>  with Referer

The ``media`` JS array on the vault page exposes every disc/version
of a title. SortOrder=1 is the canonical pick. ``GoodTitle`` is the
base64-encoded filename. We grab the first entry's ID and feed it to
dl3.vimm.net.

Configuration:
  - ``sources.vimm.systems`` — comma-separated Vimm system slugs the
    adapter searches in parallel (default: NES, SNES, N64, GB, GBC,
    GBA, DS, GC, Wii, Genesis). The user can pin a single system via
    a profile's ``extra_query_terms`` containing ``system:N64``.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import re
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

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

_VIMM_BASE = "https://vimm.net"
_VIMM_DL_BASE = "https://dl3.vimm.net"

# Every Vimm system slug we know about, mapped to a human label. The
# slug is what /vault/?system= expects.
_VIMM_SYSTEMS: dict[str, str] = {
    "Atari2600": "Atari 2600",
    "Atari5200": "Atari 5200",
    "Atari7800": "Atari 7800",
    "Lynx": "Atari Lynx",
    "Jaguar": "Atari Jaguar",
    "JaguarCD": "Atari Jaguar CD",
    "NES": "Nintendo (NES)",
    "SNES": "Super Nintendo (SNES)",
    "N64": "Nintendo 64",
    "GameCube": "GameCube",
    "Wii": "Wii",
    "WiiWare": "WiiWare",
    "GB": "Game Boy",
    "GBC": "Game Boy Color",
    "GBA": "Game Boy Advance",
    "VB": "Virtual Boy",
    "DS": "Nintendo DS",
    "3DS": "Nintendo 3DS",
    "SMS": "Sega Master System",
    "Genesis": "Sega Genesis",
    "GG": "Game Gear",
    "32X": "Sega 32X",
    "SegaCD": "Sega CD",
    "Saturn": "Sega Saturn",
    "Dreamcast": "Sega Dreamcast",
    "TG16": "TurboGrafx-16",
    "TGCD": "TurboGrafx-CD",
    "PS1": "PlayStation",
    "PS2": "PlayStation 2",
    "PS3": "PlayStation 3",
    "PSP": "PlayStation Portable",
    "Xbox": "Xbox",
    "Xbox360": "Xbox 360",
    "X360-D": "Xbox 360 (Digital)",
    "CDi": "Philips CD-i",
}

# A reasonable default cross-section so a fresh "Mario" query returns
# something even if the operator hasn't pinned a system. We avoid the
# massive PS3/Xbox360 sets which are slow and rarely what *arr clients
# want by default. Operators override via sources.vimm.systems.
_DEFAULT_SYSTEMS = (
    "NES",
    "SNES",
    "N64",
    "GB",
    "GBC",
    "GBA",
    "DS",
    "GameCube",
    "Wii",
    "Genesis",
)

# Region flag → ISO 639-1 hint. The vault doesn't expose the language
# directly; we infer from region.
_REGION_LANG: dict[str, str] = {
    "USA": "en",
    "Europe": "en",
    "Australia": "en",
    "World": "en",
    "Japan": "ja",
    "Korea": "ko",
    "China": "zh",
    "Asia": None,  # type: ignore[dict-item]  # ambiguous
    "Brazil": "pt",
    "Spain": "es",
    "Germany": "de",
    "France": "fr",
    "Italy": "it",
    "Netherlands": "nl",
    "Russia": "ru",
}

# Approximate uncompressed cartridge / disc size per system, in bytes.
# Used as a search-time placeholder for size_bytes — Vimm's listing
# page doesn't expose actual file size, only the per-game page does
# (via the JS media[] array's `Zipped` field). Fetching every per-game
# page during search would multiply HTTP calls by N results, so we
# settle for a reasonable median that stops Prowlarr/Bookshelf from
# rendering "0 B". The DownloadInfo from get_download_info carries the
# real size and the Download row gets corrected post-fetch.
_TYPICAL_SIZE: dict[str, int] = {
    "NES": 256 * 1024,             # ~256 KB
    "SNES": 1 * 1024 ** 2,         # ~1 MB
    "N64": 16 * 1024 ** 2,         # ~16 MB
    "GameCube": 1400 * 1024 ** 2,  # ~1.4 GB DVD
    "Wii": 4400 * 1024 ** 2,       # ~4.4 GB
    "WiiWare": 32 * 1024 ** 2,     # ~32 MB
    "GB": 256 * 1024,
    "GBC": 512 * 1024,
    "GBA": 16 * 1024 ** 2,
    "VB": 1 * 1024 ** 2,
    "DS": 64 * 1024 ** 2,
    "3DS": 1024 * 1024 ** 2,
    "SMS": 256 * 1024,
    "Genesis": 1 * 1024 ** 2,
    "GG": 256 * 1024,
    "32X": 2 * 1024 ** 2,
    "SegaCD": 600 * 1024 ** 2,
    "Saturn": 600 * 1024 ** 2,
    "Dreamcast": 1024 * 1024 ** 2,
    "TG16": 512 * 1024,
    "TGCD": 600 * 1024 ** 2,
    "PS1": 600 * 1024 ** 2,
    "PS2": 4400 * 1024 ** 2,
    "PS3": 25 * 1024 ** 3,
    "PSP": 1700 * 1024 ** 2,
    "Xbox": 4400 * 1024 ** 2,
    "Xbox360": 8 * 1024 ** 3,
    "X360-D": 8 * 1024 ** 3,
    "Atari2600": 32 * 1024,
    "Atari5200": 32 * 1024,
    "Atari7800": 64 * 1024,
    "Lynx": 256 * 1024,
    "Jaguar": 4 * 1024 ** 2,
    "JaguarCD": 600 * 1024 ** 2,
    "CDi": 600 * 1024 ** 2,
}

# Format hint per Vimm system. Vimm doesn't expose the file extension
# in the search list — we know it from the system.
_SYSTEM_FORMAT: dict[str, str] = {
    "NES": "nes",
    "SNES": "smc",
    "N64": "z64",
    "GameCube": "iso",
    "Wii": "wbfs",
    "WiiWare": "wad",
    "GB": "gb",
    "GBC": "gbc",
    "GBA": "gba",
    "DS": "nds",
    "3DS": "3ds",
    "Genesis": "bin",
    "SMS": "sms",
    "GG": "gg",
    "32X": "32x",
    "Saturn": "iso",
    "Dreamcast": "gdi",
    "PS1": "iso",
    "PS2": "iso",
    "PS3": "iso",
    "PSP": "iso",
    "Xbox": "iso",
    "Xbox360": "iso",
    "Atari2600": "a26",
    "Atari5200": "a52",
    "Atari7800": "a78",
    "Lynx": "lnx",
    "Jaguar": "j64",
    "JaguarCD": "iso",
    "VB": "vb",
    "TG16": "pce",
    "TGCD": "iso",
    "SegaCD": "iso",
    "X360-D": "zip",
    "CDi": "iso",
}

# Reverse map: ISO-639-1 short code → "language token Vimm understands".
# Vimm doesn't filter by language — we use this to skip results when
# the profile pins a specific language and the row's region disagrees.

# Strip leading "system:XXX" out of the user query to use as a per-call
# system override.
_SYSTEM_HINT_RE = re.compile(r"\bsystem:([A-Za-z0-9_-]+)\b", re.IGNORECASE)


@register_adapter
class VimmsLairAdapter:
    """vimm.net source adapter (curated retro ROMs)."""

    id = "vimm"
    display_name = "Vimm's Lair"
    supported_media_types = {MediaType.GAME_ROM}
    requires_cf_bypass = False
    supports_member_key = False
    supports_authentication = False

    def __init__(self) -> None:
        rate_limiter.configure(self.id, "search", per_minute=30)
        rate_limiter.configure(self.id, "download", per_minute=15)

    def _systems_to_search(self, query: str, filters: SearchFilters) -> list[str]:
        """Resolve the system list for a single search call.

        Order of precedence:
          1. ``system:XXX`` token inside the query / extra_query_terms.
          2. ``sources.vimm.systems`` setting (comma-separated).
          3. ``_DEFAULT_SYSTEMS`` baseline.
        """
        for source in (query, filters.extra_query_terms):
            if not source:
                continue
            m = _SYSTEM_HINT_RE.search(source)
            if not m:
                continue
            slug = m.group(1)
            for known in _VIMM_SYSTEMS:
                if known.lower() == slug.lower():
                    return [known]
        configured = (get_sync("sources.vimm.systems", "") or "").strip()
        if configured:
            picks = [s.strip() for s in configured.split(",") if s.strip()]
            valid = [p for p in picks if p in _VIMM_SYSTEMS]
            if valid:
                return valid
        return list(_DEFAULT_SYSTEMS)

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
        if media_type != MediaType.GAME_ROM:
            return []
        # Vimm's search box requires minlength=3.
        # Strip any system:XXX hint before sending the query upstream.
        cleaned_q = _SYSTEM_HINT_RE.sub("", query).strip()
        if len(cleaned_q) < 3:
            return []

        systems = self._systems_to_search(query, filters)
        await rate_limiter.acquire(self.id, "search")
        # Per-system cap: distribute the global limit fairly.
        per_system = max(5, limit // max(1, len(systems)))

        async with self._client() as client:
            tasks = [
                self._search_one_system(client, sys_slug, cleaned_q, per_system)
                for sys_slug in systems
            ]
            results_by_system = await asyncio.gather(*tasks, return_exceptions=True)

        flat: list[SearchResult] = []
        for sys_slug, res in zip(systems, results_by_system, strict=True):
            if isinstance(res, BaseException):
                _log.info("vimm: %s search raised %s", sys_slug, res)
                continue
            flat.extend(res)
        # Cap total + sort by quality.
        flat.sort(key=lambda r: r.quality_score, reverse=True)
        return flat[:limit]

    async def _search_one_system(
        self,
        client: httpx.AsyncClient,
        system: str,
        query: str,
        limit: int,
    ) -> list[SearchResult]:
        url = f"{_VIMM_BASE}/vault/?p=list&system={system}&q={quote_plus(query)}"
        try:
            r = await client.get(url)
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if 500 <= exc.response.status_code < 600:
                raise AdapterServerError(f"vimm {system} HTTP {exc.response.status_code}") from exc
            raise AdapterConnectivityError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AdapterConnectivityError(str(exc)) from exc

        return _parse_vimm_list(r.text, system, query, self.id, limit)

    # ---- download -------------------------------------------------------

    async def get_download_info(
        self,
        external_id: str,
        media_type: MediaType,
        query_hint: str | None = None,
    ) -> DownloadInfo:
        if not external_id.isdigit():
            raise AdapterNotFound(f"vimm: invalid vault id {external_id!r}")
        await rate_limiter.acquire(self.id, "download")
        async with self._client() as client:
            try:
                r = await client.get(f"{_VIMM_BASE}/vault/{external_id}")
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise AdapterNotFound(f"vimm vault {external_id} not found") from exc
                if 500 <= exc.response.status_code < 600:
                    raise AdapterServerError(
                        f"vimm vault HTTP {exc.response.status_code}"
                    ) from exc
                raise AdapterConnectivityError(str(exc)) from exc
            except httpx.HTTPError as exc:
                raise AdapterConnectivityError(str(exc)) from exc

        media = _extract_media_array(r.text)
        if not media:
            raise AdapterNotFound(
                f"vimm vault {external_id}: no media[] array found on page "
                "(unsupported page layout — site likely changed)"
            )
        # SortOrder=1 is the canonical disc/version. Fall back to first.
        primary = next(
            (m for m in media if str(m.get("SortOrder", "1")) == "1"),
            media[0],
        )
        media_id = primary.get("ID")
        if not media_id:
            raise AdapterNotFound(
                f"vimm vault {external_id}: media entry missing ID"
            )
        # GoodTitle is base64-encoded filename.
        filename = _decode_b64_filename(
            primary.get("GoodTitle", "")
        ) or f"vimm-{external_id}.bin"
        # Size is in KB.
        size_kb_raw = primary.get("Zipped") or 0
        try:
            size_bytes: int | None = int(size_kb_raw) * 1024
        except (TypeError, ValueError):
            size_bytes = None

        return DownloadInfo(
            download_url=f"{_VIMM_DL_BASE}/?mediaId={media_id}",
            size_bytes=size_bytes,
            content_type=None,
            filename_hint=filename,
            extra_headers={
                # Vimm checks Referer; without it dl3.vimm.net responds 403.
                "Referer": f"{_VIMM_BASE}/vault/{external_id}",
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
                r = await client.get(f"{_VIMM_BASE}/vault/", timeout=10.0)
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
                    key="sources.vimm.systems",
                    label="Systems to search",
                    field_type="text",
                    options=None,
                    secret=False,
                    required=False,
                    help_text=(
                        "Comma-separated list of Vimm system slugs to query "
                        "in parallel. Leave blank for the default Nintendo+Sega "
                        f"set ({', '.join(_DEFAULT_SYSTEMS)}). Full list of "
                        f"valid slugs: {', '.join(sorted(_VIMM_SYSTEMS))}."
                    ),
                ),
            ]
        )

    async def get_quota_status(self) -> QuotaStatus | None:
        return None


# --------------------------------------------------------------------------
# Parsers (kept module-level + pure so they're easy to unit test)
# --------------------------------------------------------------------------

_MEDIA_ARRAY_RE = re.compile(r"let\s+media\s*=\s*(\[.*?\]);", re.DOTALL)


def _extract_media_array(html: str) -> list[dict[str, Any]]:
    """Parse the inline ``let media = [{...}, ...];`` array from a vault page.

    The shipped JSON is plain (no JS-only constructs) — ``json.loads``
    works directly.
    """
    m = _MEDIA_ARRAY_RE.search(html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict)]


def _decode_b64_filename(b64: str) -> str | None:
    if not b64:
        return None
    try:
        return base64.b64decode(b64).decode("utf-8", errors="replace").strip() or None
    except (ValueError, TypeError):
        return None


def _parse_vimm_list(
    html: str,
    system: str,
    query: str,
    source_id: str,
    limit: int,
) -> list[SearchResult]:
    """Parse a /vault/?p=list page into SearchResult rows.

    Each row is a <tr> with the first <a href="/vault/<id>"> as title,
    flag <img title="REGION"> for region, plain text for version + lang.
    The third column holds the version (``1.0``, ``1.1``, …) for most
    rows OR a release date (``1990-04-27``) for prototypes/dated dumps.
    We try to extract a year from the latter.
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[SearchResult] = []
    sys_label = _VIMM_SYSTEMS.get(system, system)
    fmt_hint = _SYSTEM_FORMAT.get(system, "rom")
    typical_size = _TYPICAL_SIZE.get(system)
    for row in soup.select("tr"):
        link = row.find("a", href=re.compile(r"^/vault/\d+$"))
        if not link:
            continue
        href = link.get("href", "")
        if not href:
            continue
        try:
            external_id = href.rsplit("/", 1)[-1]
        except IndexError:
            continue
        if not external_id.isdigit():
            continue
        title = link.get_text(strip=True)
        if not title:
            continue
        # Region: every <img class="flag" title="...">
        regions: list[str] = []
        for img in row.select("img.flag"):
            t = (img.get("title") or "").strip()
            if t:
                regions.append(t)
        language: str | None = None
        for region in regions:
            language = _REGION_LANG.get(region)
            if language:
                break
        # Year: parse the 3rd column. Either a version ("1.0") or a date
        # ("1990-04-27"). We extract a year only when the cell looks
        # like a date or a bare 4-digit year.
        year: int | None = None
        cells = row.find_all("td")
        if len(cells) >= 3:
            third = cells[2].get_text(strip=True)
            year_match = re.match(r"^(\d{4})(?:-\d{2}-\d{2})?$", third)
            if year_match:
                y = int(year_match.group(1))
                if 1970 <= y <= 2099:
                    year = y
        # Version: in-title marker (Pirate / Hack / Proto / Beta / etc.)
        # OR an adjacent <b class="redBorder" title="Virtual Console">VC</b>
        # tag for items like Virtual Console / e-Reader / Aftermarket.
        version_label: str | None = None
        for marker in (
            "Pirate", "Hack", "Beta", "Demo", "Proto", "Prototype",
            "Unl", "Aftermarket", "e-Reader", "Test", "Sample",
        ):
            if f"({marker}" in title:
                version_label = marker
                break
        if version_label is None:
            sib = link.find_next_sibling("b")
            if sib is not None and "redBorder" in (sib.get("class") or []):
                bt = (sib.get("title") or sib.get_text(strip=True) or "").strip()
                if bt:
                    version_label = bt[:24]
        # Quality score: substring match boosts the row.
        score = 50.0
        if query.lower() in title.lower():
            score += 25.0
        if version_label in ("Pirate", "Hack"):
            score -= 15.0
        out.append(
            SearchResult(
                external_id=external_id,
                title=title,  # bare; torznab adds [Console] [Region] tags
                author=None,
                year=year,
                format=fmt_hint,
                language=language,
                # _TYPICAL_SIZE lookup so Prowlarr / Bookshelf don't
                # render "0 B"; the real size lands on the Download row
                # after get_download_info pulls the media[] entry.
                size_bytes=typical_size,
                quality_score=score,
                source_id=source_id,
                media_type=MediaType.GAME_ROM,
                metadata={
                    "vimm_system": system,
                    "vimm_regions": regions,
                    "console_label": system,
                    "region_label": regions[0] if regions else None,
                    "version_label": version_label,
                    "size_is_estimate": True,
                },
            )
        )
        if len(out) >= limit:
            break
    return out


def _is_vimm_url(url: str) -> bool:
    """Helper for the download manager: True iff URL is a vimm download."""
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return False
    return host.endswith("vimm.net")
