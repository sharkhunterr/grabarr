"""RomsFun source adapter — full search + countdown-aware download.

romsfun.com sits behind Cloudflare and gates the actual file URL
behind a 7-second JS countdown that REWRITES the link's ``href``
when ``#download-button`` loses its ``hidden`` class. The HTML
served on the per-file landing page contains a *placeholder* token
(always identical) before the countdown — fetching that one returns
403 from the CDN. The real, signed token only appears after the JS
mutates the DOM.

Search:    GET https://romsfun.com/?s=<q>             (CF JS challenge)
Detail:    GET /roms/<console>/<slug>.html             (CF)
Lvl-1 dl:  GET /download/<slug>-<id>                   (CF, exposes lvl-2)
Lvl-2 dl:  GET /download/<slug>-<id>/<n>               (CF + 7 s countdown)

Final file URL is read from ``#download-link`` AFTER the
``#download-button`` div drops its ``hidden`` class. The CDN
(``sto.romsfast.com``) accepts a plain httpx GET as long as we
forward the right Referer + Sec-Fetch-* headers; no special cookie
beyond ``cf_clearance`` is required.

Note: ``www.romsfun.com`` triggers a fake "website has been stopped"
stub. We hardcode the bare ``romsfun.com`` host.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from urllib.parse import quote_plus, urlparse

from bs4 import BeautifulSoup

from grabarr.adapters.base import (
    AdapterBypassError,
    AdapterError,
    AdapterNotFound,
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

# bypass.* imports are deferred to runtime to avoid a circular import.

_log = setup_logger(__name__)

_RFUN_BASE = "https://romsfun.com"
_DETAIL_RE = re.compile(r"^https?://romsfun\.com/roms/([a-z0-9-]+)/([a-z0-9-]+)\.html$")
# Per-console size estimate (bytes). Used as a search-time placeholder
# so Prowlarr doesn't render "0 B"; the real size comes from the
# Content-Length response header during the actual download.
# RomsFun's URL slugs use full English names ("playstation",
# "playstation-2") rather than scene abbreviations. Keep both forms
# so older/newer URL patterns both resolve.
_TYPICAL_SIZE: dict[str, int] = {
    # Nintendo
    "nes": 256 * 1024,
    "snes": 1 * 1024 ** 2,
    "super-nintendo": 1 * 1024 ** 2,
    "n64": 16 * 1024 ** 2,
    "nintendo-64": 16 * 1024 ** 2,
    "gameboy": 256 * 1024,
    "gbc": 512 * 1024,
    "gameboy-color": 512 * 1024,
    "gba": 16 * 1024 ** 2,
    "gameboy-advance": 16 * 1024 ** 2,
    "nds": 64 * 1024 ** 2,
    "nintendo-ds": 64 * 1024 ** 2,
    "3ds": 1024 * 1024 ** 2,
    "nintendo-3ds": 1024 * 1024 ** 2,
    "gamecube": 1400 * 1024 ** 2,
    "wii": 4400 * 1024 ** 2,
    "wiiu": 8 * 1024 ** 3,
    "nintendo-switch": 16 * 1024 ** 3,
    # PlayStation family
    "ps1": 600 * 1024 ** 2,
    "playstation": 600 * 1024 ** 2,
    "ps2": 4400 * 1024 ** 2,
    "playstation-2": 4400 * 1024 ** 2,
    "ps3": 25 * 1024 ** 3,
    "playstation-3": 25 * 1024 ** 3,
    "ps4": 50 * 1024 ** 3,
    "playstation-4": 50 * 1024 ** 3,
    "psp": 1700 * 1024 ** 2,
    "playstation-portable": 1700 * 1024 ** 2,
    "psvita": 4 * 1024 ** 3,
    "playstation-vita": 4 * 1024 ** 3,
    # Sega
    "genesis": 1 * 1024 ** 2,
    "mega-drive": 1 * 1024 ** 2,
    "saturn": 600 * 1024 ** 2,
    "sega-saturn": 600 * 1024 ** 2,
    "dreamcast": 1024 * 1024 ** 2,
    "sega-dreamcast": 1024 * 1024 ** 2,
    # Microsoft
    "xbox": 4400 * 1024 ** 2,
    "xbox-360": 8 * 1024 ** 3,
    "xbox-one": 50 * 1024 ** 3,
    # Atari + retro
    "atari-2600": 32 * 1024,
    "atari-7800": 64 * 1024,
    "neogeo": 32 * 1024 ** 2,
    "neo-geo": 32 * 1024 ** 2,
}
# Per-system pretty label for the [<system>] suffix in result titles.
_SYSTEM_LABEL: dict[str, str] = {
    "nes": "NES",
    "snes": "SNES",
    "super-nintendo": "SNES",
    "n64": "N64",
    "nintendo-64": "N64",
    "gameboy": "GB",
    "gbc": "GBC",
    "gameboy-color": "GBC",
    "gba": "GBA",
    "gameboy-advance": "GBA",
    "nds": "NDS",
    "nintendo-ds": "NDS",
    "3ds": "3DS",
    "nintendo-3ds": "3DS",
    "gamecube": "GameCube",
    "wii": "Wii",
    "wiiu": "Wii U",
    "nintendo-switch": "Switch",
    "playstation": "PS1",
    "ps1": "PS1",
    "playstation-2": "PS2",
    "ps2": "PS2",
    "playstation-3": "PS3",
    "playstation-4": "PS4",
    "playstation-portable": "PSP",
    "psp": "PSP",
    "playstation-vita": "PSVita",
    "genesis": "Genesis",
    "mega-drive": "Genesis",
    "saturn": "Saturn",
    "sega-saturn": "Saturn",
    "dreamcast": "Dreamcast",
    "sega-dreamcast": "Dreamcast",
    "xbox": "Xbox",
    "xbox-360": "Xbox 360",
    "xbox-one": "Xbox One",
    "atari-2600": "Atari 2600",
    "atari-7800": "Atari 7800",
    "neogeo": "Neo Geo",
    "neo-geo": "Neo Geo",
}


@register_adapter
class RomsFunAdapter:
    """romsfun.com source adapter."""

    id = "romsfun"
    display_name = "RomsFun"
    supported_media_types = {MediaType.GAME_ROM}
    requires_cf_bypass = True
    supports_member_key = False
    supports_authentication = False

    def __init__(self) -> None:
        rate_limiter.configure(self.id, "search", per_minute=15)
        # Each download boots a real Chromium for the countdown wait.
        # Cap tighter to avoid burning CPU under a Prowlarr burst.
        rate_limiter.configure(self.id, "download", per_minute=4)

    # ---- search --------------------------------------------------------

    async def search(
        self,
        query: str,
        media_type: MediaType,
        filters: SearchFilters,  # noqa: ARG002
        limit: int = 50,
    ) -> list[SearchResult]:
        from grabarr.bypass.service import fetch_html

        if media_type != MediaType.GAME_ROM:
            return []
        cleaned_q = (query or "").strip()
        if not cleaned_q:
            return []
        await rate_limiter.acquire(self.id, "search")
        url = f"{_RFUN_BASE}/?s={quote_plus(cleaned_q)}"
        try:
            html = await fetch_html(url, prefer_internal=True, timeout=45)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterBypassError(
                f"romsfun: fetch_html failed for {url}: {exc}"
            ) from exc
        return _parse_search_html(html, cleaned_q, self.id, limit)

    # ---- download ------------------------------------------------------

    async def get_download_info(
        self,
        external_id: str,
        media_type: MediaType,  # noqa: ARG002
        query_hint: str | None = None,  # noqa: ARG002
    ) -> DownloadInfo:
        from grabarr.bypass.click_driver import fetch_session
        from grabarr.bypass.service import fetch_html

        # external_id encodes "<console-slug>/<game-slug>".
        if "/" not in external_id:
            raise AdapterNotFound(
                f"romsfun: external_id {external_id!r} missing console/game split"
            )
        await rate_limiter.acquire(self.id, "download")
        detail_url = f"{_RFUN_BASE}/roms/{external_id}.html"

        # 1. Detail → expose /download/<slug>-<id>.
        try:
            detail_html = await fetch_html(
                detail_url, prefer_internal=True, timeout=45
            )
        except Exception as exc:
            raise AdapterBypassError(
                f"romsfun: fetch_html on {detail_url} failed: {exc}"
            ) from exc
        match = re.search(
            r'href="(https?://romsfun\.com/download/[a-z0-9-]+-\d+)"', detail_html
        )
        if not match:
            raise AdapterNotFound(
                f"romsfun: no /download/ link found on {detail_url}"
            )
        download_page_url = match.group(1)

        # 2. Lvl-1 landing → expose /download/<slug>-<id>/<n>.
        try:
            landing_html = await fetch_html(
                download_page_url, prefer_internal=True, timeout=45
            )
        except Exception as exc:
            raise AdapterBypassError(
                f"romsfun: fetch_html on {download_page_url} failed: {exc}"
            ) from exc
        file_link_match = re.search(
            r'<a[^>]+target="_blank"[^>]+href="('
            + re.escape(download_page_url)
            + r'/\d+)"',
            landing_html,
        )
        if not file_link_match:
            file_link_match = re.search(
                r'href="(https?://romsfun\.com/download/[a-z0-9-]+-\d+/\d+)"',
                landing_html,
            )
        if not file_link_match:
            raise AdapterNotFound(
                f"romsfun: no per-file anchor on {download_page_url}"
            )
        per_file_url = file_link_match.group(1)
        _log.info("romsfun: detail %s → %s", external_id, per_file_url)

        # 3. Lvl-2 page = the countdown page. fetch_session waits for the
        #    `#download-button` div to lose `hidden` (~7 s typical), at
        #    which point JS has rewritten `#download-link.href` with
        #    the real signed token (the in-HTML one is a placeholder).
        try:
            session = await asyncio.to_thread(
                fetch_session,
                per_file_url,
                settle_seconds=1.5,
                wait_until_visible="#download-button",
                wait_timeout=30,
                timeout=60,
            )
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterBypassError(
                f"romsfun: fetch_session on {per_file_url} failed: {exc}"
            ) from exc

        anchor = BeautifulSoup(session.html, "lxml").find("a", id="download-link")
        cdn_url = (anchor.get("href") if anchor else "") or ""
        if not cdn_url:
            raise AdapterNotFound(
                f"romsfun: no #download-link anchor on {per_file_url} "
                "(countdown didn't reveal — page layout may have changed)"
            )
        _log.info("romsfun: signed CDN URL → %s", cdn_url[:120])

        # The Sec-Fetch-* headers and a Referer matching the per-file
        # page are required by the CDN; cf_clearance from the bypass
        # session keeps Cloudflare happy on the romsfun.com side.
        headers: dict[str, str] = {
            "User-Agent": session.user_agent
            or (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": per_file_url,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-User": "?1",
        }
        if session.cookies:
            headers["Cookie"] = "; ".join(
                f"{k}={v}" for k, v in session.cookies.items()
            )

        return DownloadInfo(
            download_url=cdn_url,
            size_bytes=None,
            content_type=None,
            filename_hint=_filename_from_url(cdn_url),
            extra_headers=headers,
        )

    # ---- health + config ----------------------------------------------

    async def health_check(self) -> HealthStatus:
        # Don't waste a Chromium boot on a probe.
        return HealthStatus(
            status=AdapterHealth.HEALTHY,
            reason=None,
            message=None,
            checked_at=dt.datetime.now(dt.UTC),
        )

    def get_config_schema(self) -> ConfigSchema:
        from grabarr.adapters.base import ConfigField

        return ConfigSchema(
            fields=[
                ConfigField(
                    key="sources.romsfun.system_overrides",
                    label="Console label / size overrides (JSON)",
                    field_type="text",
                    options=None,
                    secret=False,
                    required=False,
                    help_text=(
                        'JSON object merged on top of the built-in '
                        'console-slug → label map, e.g. '
                        '{"my-new-slug": "Pretty Name"}. Same JSON also '
                        'overrides the per-system size estimate when an '
                        'integer value is provided. Leave empty to use '
                        'the built-in defaults only.'
                    ),
                ),
            ]
        )

    async def get_quota_status(self) -> QuotaStatus | None:
        return None


# --------------------------------------------------------------------------
# Parsers (module-level + pure for unit tests)
# --------------------------------------------------------------------------


def _filename_from_url(url: str) -> str:
    try:
        path = urlparse(url).path
    except ValueError:
        return "rom.bin"
    from urllib.parse import unquote

    return unquote(path.rsplit("/", 1)[-1] or "rom.bin")


def _parse_search_html(
    html: str, query: str, source_id: str, limit: int
) -> list[SearchResult]:
    """Extract result rows from RomsFun's ``?s=<q>`` HTML.

    Each card is a wrapper around two anchors pointing at
    ``/roms/<console>/<slug>.html`` (one wrapping the cover image, one
    wrapping the title text). We dedupe by external_id.
    """
    from grabarr.adapters._rom_helpers import settings_overlay

    label_map = settings_overlay("sources.romsfun.system_overrides", _SYSTEM_LABEL)
    size_map = settings_overlay("sources.romsfun.system_overrides", _TYPICAL_SIZE)
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    out: list[SearchResult] = []
    for a in soup.find_all("a", href=_DETAIL_RE):
        href = a.get("href", "") or ""
        m = _DETAIL_RE.match(href)
        if not m:
            continue
        console_slug, game_slug = m.group(1), m.group(2)
        external_id = f"{console_slug}/{game_slug}"
        if external_id in seen:
            continue
        title_text = a.get_text(strip=True)
        if not title_text:
            img = a.find("img")
            if img:
                title_text = (img.get("alt") or "").strip()
        if not title_text:
            continue
        seen.add(external_id)
        # Operator-overrideable label / size lookups.
        sys_label_value = label_map.get(console_slug)
        if isinstance(sys_label_value, str) and sys_label_value:
            sys_label = sys_label_value
        else:
            sys_label = console_slug.replace("-", " ").title()
        # Tag promotion from in-title parentheses.
        version_label: str | None = None
        for kw in ("Hack", "Pirate", "Beta", "Demo", "Proto", "Translation"):
            if kw.lower() in title_text.lower():
                version_label = kw
                break
        region_label: str | None = None
        for region in (
            "USA", "Japan", "Europe", "World", "Australia", "Korea",
            "China", "Asia",
        ):
            if region in title_text:
                region_label = region
                break
        clean_title = re.sub(r"\s*\([^)]*\)\s*", " ", title_text).strip()
        if not clean_title:
            clean_title = title_text
        from grabarr.adapters._rom_helpers import score_title_relevance

        score = 50.0 + score_title_relevance(title_text, query)
        if version_label in {"Hack", "Pirate"}:
            score -= 15.0
        out.append(
            SearchResult(
                external_id=external_id,
                title=clean_title,
                author=None,
                year=None,
                format="rom",
                language=None,
                size_bytes=(
                    size_map.get(console_slug)
                    if isinstance(size_map.get(console_slug), int)
                    else None
                ),
                quality_score=score,
                source_id=source_id,
                media_type=MediaType.GAME_ROM,
                metadata={
                    "romsfun_console": console_slug,
                    "romsfun_slug": game_slug,
                    "console_label": sys_label,
                    "region_label": region_label,
                    "version_label": version_label,
                    "size_is_estimate": True,
                },
            )
        )
    # Keep the highest-scoring `limit` entries — substring/exact-title
    # matches outrank fuzzy hits, so the top N are the most relevant.
    out.sort(key=lambda r: r.quality_score, reverse=True)
    return out[:limit]
