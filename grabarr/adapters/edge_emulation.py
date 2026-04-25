"""Edge Emulation source adapter — Grabarr-native HTML scraper.

edgeemu.net covers a wide cross-section of retro consoles (NES, SNES,
N64, GameCube, Game Boy line, DS, Genesis, PS1, Saturn, Dreamcast,
Atari, Commodore, Neo Geo, etc.). Search results carry the download
URL inline — no detail-page hop, no captcha, no auth, no Cloudflare.

Search:    POST https://edgeemu.net/search.php
                  body: search=<q>&system=<sys-or-"all">
Download:  GET  https://edgeemu.net/download/<system-slug>/<URL-encoded-filename>

Each result is a ``<div class="item"><details data-name="filename.ext">
<summary>title</summary><p><a href="/download/<sys>/<file>">download</a>
(<span>SIZE, NN DLs</span>)</p><p>system: <span>...</span></p>
<p>unpacked size: <span>1.46g</span></p><p>hash: <span>...</span></p>
</details></div>`` — the data-name attribute carries the canonical
filename + extension.
"""

from __future__ import annotations

import datetime as dt
import re
from urllib.parse import quote, unquote

import httpx
from bs4 import BeautifulSoup

from grabarr.adapters.base import (
    AdapterConnectivityError,
    AdapterNotFound,
    AdapterServerError,
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

_EDGE_BASE = "https://edgeemu.net"

# Edge Emulation system slugs (from the home page <select name="system">).
# Mirrored here so operators can pin a profile to a single system via
# extra_query_terms="system:nintendo-snes" (case-insensitive).
_EDGE_SYSTEMS: frozenset[str] = frozenset(
    {
        "all",
        "atari-2600", "atari-5200", "atari-7800", "atari-jaguar",
        "atari-jaguar-cd", "atari-lynx", "atari-st",
        "bandai-wonderswan",
        "colecovision",
        "commodore-64", "commodore-amiga", "commodore-amiga-cd",
        "commodore-amiga-cd32", "commodore-plus-4", "commodore-vic-20",
        "fairchild-channel-f",
        "gce-vectrex",
        "microsoft-msx",
        "nec-pc-engine-cd-turbografx-cd", "nec-pc-engine-supergrafx",
        "nec-pc-engine-turbografx-16",
        "nintendo-ds", "nintendo-fds", "nintendo-gameboy",
        "nintendo-gameboy-advance", "nintendo-gameboy-color",
        "nintendo-gamecube", "nintendo-64", "nintendo-nes",
        "nintendo-satellaview", "nintendo-virtualboy", "nintendo-snes",
        "panasonic-3do", "philips-cdi", "rca-studioii",
        "sega-32x", "sega-dreamcast", "sega-gamegear", "sega-sms",
        "sega-cd", "sega-genesis", "sega-pico", "sega-saturn",
        "sega-sg1000",
        "sinclair-zx-spectrum-3",
        "snk-neo-geo-cd", "snk-ngpc",
        "watara-supervision",
    }
)

# Pretty system label per slug, for the [SOURCE] tag.
_EDGE_SYSTEM_LABEL: dict[str, str] = {
    "nintendo-nes": "NES",
    "nintendo-snes": "SNES",
    "nintendo-64": "N64",
    "nintendo-gameboy": "GB",
    "nintendo-gameboy-color": "GBC",
    "nintendo-gameboy-advance": "GBA",
    "nintendo-ds": "NDS",
    "nintendo-gamecube": "GameCube",
    "nintendo-virtualboy": "VirtualBoy",
    "nintendo-fds": "Famicom DS",
    "sega-genesis": "Genesis",
    "sega-cd": "Sega CD",
    "sega-saturn": "Saturn",
    "sega-dreamcast": "Dreamcast",
    "sega-gamegear": "Game Gear",
    "sega-sms": "Master System",
    "sega-32x": "32X",
    "atari-2600": "Atari 2600",
    "atari-jaguar": "Atari Jaguar",
    "atari-lynx": "Atari Lynx",
    "snk-ngpc": "Neo Geo Pocket",
    "snk-neo-geo-cd": "Neo Geo CD",
    "panasonic-3do": "3DO",
    "nec-pc-engine-turbografx-16": "TurboGrafx-16",
}

_SYSTEM_HINT_RE = re.compile(r"\bsystem:([A-Za-z0-9_-]+)\b", re.IGNORECASE)
_SIZE_RE = re.compile(r"^([\d.,]+)\s*([kmgtKMGT]?)\s*$")


@register_adapter
class EdgeEmulationAdapter:
    """edgeemu.net source adapter (multi-platform retro ROMs)."""

    id = "edge_emulation"
    display_name = "Edge Emulation"
    supported_media_types = {MediaType.GAME_ROM}
    requires_cf_bypass = False
    supports_member_key = False
    supports_authentication = False

    def __init__(self) -> None:
        rate_limiter.configure(self.id, "search", per_minute=30)
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

    def _resolve_system(self, query: str, filters: SearchFilters) -> str:
        """Pull a ``system:XXX`` hint out of the query / extra terms."""
        for source in (query, filters.extra_query_terms):
            if not source:
                continue
            m = _SYSTEM_HINT_RE.search(source)
            if not m:
                continue
            slug = m.group(1).lower()
            if slug in _EDGE_SYSTEMS:
                return slug
        return "all"

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
        cleaned_q = _SYSTEM_HINT_RE.sub("", query).strip()
        if not cleaned_q:
            return []
        system = self._resolve_system(query, filters)
        await rate_limiter.acquire(self.id, "search")
        try:
            async with self._client() as client:
                r = await client.post(
                    f"{_EDGE_BASE}/search.php",
                    data={"search": cleaned_q, "system": system},
                )
                r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if 500 <= exc.response.status_code < 600:
                raise AdapterServerError(
                    f"edgeemu HTTP {exc.response.status_code}"
                ) from exc
            raise AdapterConnectivityError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AdapterConnectivityError(str(exc)) from exc

        return _parse_edge_results(r.text, cleaned_q, self.id, limit)

    # ---- download -------------------------------------------------------

    async def get_download_info(
        self,
        external_id: str,
        media_type: MediaType,
        query_hint: str | None = None,
    ) -> DownloadInfo:
        # external_id is the URL-encoded path "<system>/<filename>".
        # The search adapter encodes the bare path; we decode once for the
        # filename hint and re-encode the filename portion for the URL.
        if "/" not in external_id:
            raise AdapterNotFound(
                f"edge_emulation: external_id {external_id!r} missing system/filename split"
            )
        system, encoded_name = external_id.split("/", 1)
        if system not in _EDGE_SYSTEMS:
            raise AdapterNotFound(
                f"edge_emulation: unknown system {system!r}"
            )
        filename = unquote(encoded_name)
        # Re-quote so spaces / parentheses are URL-safe; matches what
        # the search results emit so we don't 404 on a round-trip.
        url = f"{_EDGE_BASE}/download/{system}/{quote(filename)}"
        await rate_limiter.acquire(self.id, "download")
        return DownloadInfo(
            download_url=url,
            size_bytes=None,
            content_type=None,
            filename_hint=filename,
            extra_headers={
                "Referer": f"{_EDGE_BASE}/?s={quote(filename)}",
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
                r = await client.get(f"{_EDGE_BASE}/", timeout=10.0)
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
# Parsers (module-level + pure for unit-test friendliness)
# --------------------------------------------------------------------------


def _parse_size_edge(text: str) -> int | None:
    """Parse ``5.95m`` / ``948.52k`` / ``1.00g`` into bytes.

    edgeemu uses lowercase-suffix base-2 sizes (m=MiB, g=GiB, k=KiB).
    """
    if not text:
        return None
    m = _SIZE_RE.match(text.strip())
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    suffix = m.group(2).lower()
    mult = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4}.get(
        suffix, 1
    )
    return int(value * mult)


def _format_from_filename(name: str) -> str:
    if "." not in name:
        return "rom"
    return name.rsplit(".", 1)[-1].lower()


def _parse_edge_results(
    html: str, query: str, source_id: str, limit: int
) -> list[SearchResult]:
    """Extract `<details>` rows from the search-results HTML."""
    soup = BeautifulSoup(html, "lxml")
    grid = soup.select_one("div.grid")
    if grid is None:
        return []
    out: list[SearchResult] = []
    for item in grid.select("div.item details"):
        data_name = (item.get("data-name") or "").strip()
        summary = item.find("summary")
        title = summary.get_text(strip=True) if summary else data_name
        if not title or not data_name:
            continue
        # Find the <a href="/download/<sys>/<file>"> within this row.
        link = item.find(
            "a", href=re.compile(r"^/download/[^/]+/.+", re.IGNORECASE)
        )
        if not link:
            continue
        href = link.get("href", "")
        if not href.startswith("/download/"):
            continue
        external_id = href[len("/download/") :]
        try:
            system, encoded_name = external_id.split("/", 1)
        except ValueError:
            continue
        # Size from the <span> after the link.
        size_bytes: int | None = None
        size_span = link.find_next("span")
        if size_span:
            raw = (size_span.get_text(strip=True) or "").split(",", 1)[0].strip()
            size_bytes = _parse_size_edge(raw)

        # File hash is in <p>hash: <span>SHA-1 or CRC32</span></p>.
        file_hash: str | None = None
        for p in item.find_all("p"):
            txt = p.get_text(strip=True).lower()
            if txt.startswith("hash:"):
                hs = p.find("span")
                if hs:
                    h = hs.get_text(strip=True)
                    if re.fullmatch(r"[0-9a-fA-F]{8,40}", h):
                        file_hash = h.lower()
                break

        system_label = _EDGE_SYSTEM_LABEL.get(
            system, system.replace("-", " ").title()
        )

        # Parse parenthesised tags from the filename / title:
        #   (USA), (Japan), (Europe), (World), (USA, Australia)
        #   (Rev 1), (Beta), (Hack), (Demo), (Proto), (Unl)
        #   (En,Fr,De,Es,It)
        region_label, version_label, lang_code = _parse_edge_tags(
            data_name or title
        )

        # Stripped title for the bare display: drop the parenthesised
        # block(s) since the tags are now exposed by the torznab builder.
        clean_title = re.sub(r"\s*\([^)]*\)\s*", " ", title).strip()
        if not clean_title:
            clean_title = title

        from grabarr.adapters._rom_helpers import score_title_relevance

        decoded_name = unquote(encoded_name)
        # Score against the prettier "summary" title; fall back to the
        # filename so partial-name matches still bubble up.
        score = 50.0 + max(
            score_title_relevance(title, query),
            score_title_relevance(decoded_name, query),
        )
        if version_label in {"Hack", "Pirate"}:
            score -= 15.0

        out.append(
            SearchResult(
                external_id=external_id,
                title=clean_title,
                author=None,
                year=None,
                format=_format_from_filename(data_name),
                language=lang_code,
                size_bytes=size_bytes,
                quality_score=score,
                source_id=source_id,
                media_type=MediaType.GAME_ROM,
                metadata={
                    "edge_system": system,
                    "edge_filename": data_name,
                    "console_label": system_label,
                    "region_label": region_label,
                    "version_label": version_label,
                    "file_hash": file_hash,
                },
            )
        )
    # Sort by quality_score desc so the most relevant rows survive
    # the per-source `limit` cap.
    out.sort(key=lambda r: r.quality_score, reverse=True)
    return out[:limit]


# ----- filename-tag parsing -------------------------------------------------

_REGION_KEYWORDS: tuple[str, ...] = (
    "USA", "Japan", "Europe", "World", "Australia", "Korea", "China",
    "Brazil", "France", "Germany", "Spain", "Italy", "Netherlands",
    "Asia",
)
_VERSION_KEYWORDS: tuple[str, ...] = (
    "Hack", "Pirate", "Beta", "Demo", "Proto", "Prototype", "Unl",
    "Aftermarket", "Sample", "Test", "Translation", "Fan Translation",
)


def _parse_edge_tags(name: str) -> tuple[str | None, str | None, str | None]:
    """Pull (region, version, lang) out of an Edge data-name / summary.

    Filenames look like ``Mario Kart DS (USA, Australia) (En,Fr,De,Es,It).zip``
    — multiple parenthesised groups, comma-separated entries inside.
    """
    region = None
    version = None
    lang = None
    for paren in re.findall(r"\(([^)]*)\)", name):
        items = [it.strip() for it in paren.split(",")]
        if not items:
            continue
        # Region: any item matches a known region keyword.
        if region is None:
            hits = [it for it in items if it in _REGION_KEYWORDS]
            if hits:
                region = ", ".join(hits)
                continue
        # Languages: items look like 2-letter codes (En, Fr, De, …).
        if lang is None and all(
            len(it) == 2 and it.isalpha() and it[0].isupper() for it in items
        ):
            lang = items[0].lower()
            continue
        # Version markers: contains a known keyword (case-insensitive).
        if version is None:
            for kw in _VERSION_KEYWORDS:
                if any(kw.lower() in it.lower() for it in items):
                    version = kw
                    break
            else:
                # Rev N
                for it in items:
                    if it.lower().startswith("rev "):
                        version = it
                        break
    return region, version, lang
