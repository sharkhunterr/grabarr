"""CDRomance source adapter — search + click-driven AJAX download.

cdromance.org sits behind Cloudflare. Each ROM detail page hosts a
``<button class="acf-get-content-button">Show Links</button>`` that
fires an AJAX call into ``#acf-content-wrapper`` populating
``<a id="dl-btn-N" href="https://dl1c.cdromance.org/download.php?file=…&id=…&platform=…&key=…">``.
The CDN at ``dl1c.cdromance.org`` accepts a plain httpx GET as long
as we forward the WordPress session cookie (``PHPSESSID``), the click-
set tracking cookie (``downloaded-<post-id>``), the cf_clearance from
the bypass, and a ``Referer: <detail-url>`` header.

Search:    GET https://cdromance.org/?s=<q>          (CF JS challenge)
Detail:    GET https://cdromance.org/<console>/<slug>/
                  → click Show Links → AJAX populates wrapper
Download:  https://dl1c.cdromance.org/download.php?...&key=...

The ``key`` is server-generated per request and tied to PHPSESSID +
the click-tracking cookie. Both come back from `fetch_session`.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from urllib.parse import urlparse

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

_CDR_BASE = "https://cdromance.org"
# Detail page URL pattern: https://cdromance.org/<console-slug>/<game-slug>/
_DETAIL_RE = re.compile(
    r"^https?://cdromance\.org/([a-z0-9_-]+)/([a-z0-9_-]+)/?$"
)
# Skip non-ROM paths.
_SKIP_PATH_HINTS: frozenset[str] = frozenset(
    {"guides", "platforms", "browse-all-roms", "tag", "author", "category"}
)
# Pretty per-console label.
_SYSTEM_LABEL: dict[str, str] = {
    "snes-rom": "SNES",
    "nes-roms": "NES",
    "n64-roms": "N64",
    "gamecube": "GameCube",
    "wii": "Wii",
    "wii-u": "Wii U",
    "gameboy-roms": "GB",
    "gameboy-color-roms": "GBC",
    "gba-roms": "GBA",
    "nds-roms": "NDS",
    "3ds-roms": "3DS",
    "psp": "PSP",
    "ps1-roms": "PS1",
    "ps2-roms": "PS2",
    "ps3-roms": "PS3",
    "psv-roms": "PSVita",
    "famicom_disk_system": "Famicom DS",
    "windows": "Windows",
    "dreamcast": "Dreamcast",
    "saturn": "Saturn",
    "genesis": "Genesis",
}


@register_adapter
class CDRomanceAdapter:
    """cdromance.org source adapter."""

    id = "cdromance"
    display_name = "CDRomance"
    supported_media_types = {MediaType.GAME_ROM}
    requires_cf_bypass = True
    supports_member_key = False
    supports_authentication = False

    def __init__(self) -> None:
        rate_limiter.configure(self.id, "search", per_minute=15)
        # Each download boots a real Chromium → cap tighter.
        rate_limiter.configure(self.id, "download", per_minute=4)

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
        url = f"{_CDR_BASE}/?s={cleaned_q.replace(' ', '+')}"
        try:
            html = await fetch_html(url, prefer_internal=True, timeout=45)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterBypassError(
                f"cdromance: fetch_html failed for {url}: {exc}"
            ) from exc
        return _parse_search_html(html, cleaned_q, self.id, limit)

    async def get_download_info(
        self,
        external_id: str,
        media_type: MediaType,  # noqa: ARG002
        query_hint: str | None = None,  # noqa: ARG002
    ) -> DownloadInfo:
        from grabarr.bypass.click_driver import fetch_session

        if "/" not in external_id:
            raise AdapterNotFound(
                f"cdromance: external_id {external_id!r} missing console/game split"
            )
        await rate_limiter.acquire(self.id, "download")
        detail_url = f"{_CDR_BASE}/{external_id}/"

        # The detail page hosts a "Show Links" button. Click it via JS;
        # poll until #acf-content-wrapper has at least one dl-btn anchor.
        try:
            session = await asyncio.to_thread(
                fetch_session,
                detail_url,
                settle_seconds=2.0,
                pre_action_js=(
                    "document.querySelector('.acf-get-content-button')?.click()"
                ),
                wait_until_ready_js=(
                    "document.querySelectorAll('#acf-content-wrapper "
                    "a[id^=\"dl-btn\"]').length > 0"
                ),
                wait_timeout=15,
                timeout=60,
            )
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterBypassError(
                f"cdromance: fetch_session on {detail_url} failed: {exc}"
            ) from exc

        soup = BeautifulSoup(session.html, "lxml")
        anchor = soup.select_one("#acf-content-wrapper a[id^=dl-btn-]")
        cdn_url = (anchor.get("href") if anchor else "") or ""
        if not cdn_url:
            raise AdapterNotFound(
                f"cdromance: no #acf-content-wrapper anchors on {detail_url} "
                "(Show Links AJAX did not populate)"
            )
        cdn_url = cdn_url.replace("&amp;", "&")
        _log.info("cdromance: signed CDN URL → %s", cdn_url[:120])

        headers: dict[str, str] = {
            "User-Agent": session.user_agent
            or (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Referer": detail_url,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-site",
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
            filename_hint=_filename_from_cdn(cdn_url, anchor),
            extra_headers=headers,
        )

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            status=AdapterHealth.HEALTHY,
            reason=None,
            message=None,
            checked_at=dt.datetime.now(dt.UTC),
        )

    def get_config_schema(self) -> ConfigSchema:
        return ConfigSchema(fields=[])

    async def get_quota_status(self) -> QuotaStatus | None:
        return None


def _filename_from_cdn(url: str, anchor: object) -> str:
    """Pull the filename from the CDN URL's ``file=…`` query param.

    Falls back to the anchor text or the URL path tail.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        parsed = None
    if parsed and parsed.query:
        from urllib.parse import parse_qs, unquote

        qs = parse_qs(parsed.query)
        if "file" in qs and qs["file"]:
            return unquote(qs["file"][0])
    if anchor:
        text = getattr(anchor, "text", "")
        if isinstance(text, str) and text.strip():
            return text.strip()
    if parsed:
        from urllib.parse import unquote

        tail = parsed.path.rsplit("/", 1)[-1]
        if tail:
            return unquote(tail)
    return "rom.bin"


def _parse_search_html(
    html: str, query: str, source_id: str, limit: int
) -> list[SearchResult]:
    """Parse a CDRomance search-results HTML into SearchResults.

    Each card has the shape:

        <div class="game-container">
          <div class="top-section">
            <a class="cover-link" href=".../console-slug/game-slug/">
              <img alt="Title" />
              <div class="console <slug>" title="Console">SNES</div>
            </a>
          </div>
          <div class="bottom-section">
            <a href=".../console-slug/game-slug/">
              <div class="game-title">Title</div>
            </a>
            <div class="lang">Hack, RPG</div>
            <div class="lang">English</div>
            <div class="region" title="Region <Name>">…</div>
          </div>
        </div>

    We anchor on ``div.game-container`` and walk inside.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    out: list[SearchResult] = []

    # Per-system rough size estimate (uncompressed cartridge / disc).
    typical_size: dict[str, int] = {
        "nes-roms": 256 * 1024,
        "snes-rom": 1 * 1024 ** 2,
        "n64-roms": 16 * 1024 ** 2,
        "gameboy-roms": 256 * 1024,
        "gameboy-color-roms": 512 * 1024,
        "gba-roms": 16 * 1024 ** 2,
        "nds-roms": 64 * 1024 ** 2,
        "3ds-roms": 1 * 1024 ** 3,
        "gamecube": 1400 * 1024 ** 2,
        "wii": 4400 * 1024 ** 2,
        "ps1-roms": 600 * 1024 ** 2,
        "ps2-roms": 4400 * 1024 ** 2,
        "ps3-roms": 25 * 1024 ** 3,
        "psp": 1700 * 1024 ** 2,
        "psv-roms": 4 * 1024 ** 3,
        "famicom_disk_system": 128 * 1024,
        "windows": 10 * 1024 ** 2,
        "dreamcast": 1024 * 1024 ** 2,
        "saturn": 600 * 1024 ** 2,
        "genesis": 1 * 1024 ** 2,
    }

    for card in soup.select("div.game-container"):
        cover = card.select_one("a.cover-link")
        if not cover:
            continue
        href = cover.get("href", "") or ""
        m = _DETAIL_RE.match(href)
        if not m:
            continue
        console_slug, game_slug = m.group(1), m.group(2)
        if console_slug in _SKIP_PATH_HINTS:
            continue
        external_id = f"{console_slug}/{game_slug}"
        if external_id in seen:
            continue
        # Title: prefer .game-title, fallback to <img alt>.
        title_el = card.select_one(".game-title")
        title_text = title_el.get_text(strip=True) if title_el else ""
        if not title_text:
            img = cover.find("img")
            if img:
                title_text = (img.get("alt") or "").strip()
        if not title_text:
            continue
        # Language: any .lang div whose text matches a known language.
        _LANG_MAP = {
            "english": "en", "japanese": "ja", "french": "fr",
            "german": "de", "spanish": "es", "italian": "it",
            "portuguese": "pt", "russian": "ru", "chinese": "zh",
            "korean": "ko",
        }
        language: str | None = None
        for lang_div in card.select(".lang"):
            t = (lang_div.get_text(strip=True) or "").lower()
            if t in _LANG_MAP:
                language = _LANG_MAP[t]
                break
        # Region: <div class="region" title="Region <Name>"> with an
        # SVG flag inside; the region name lives in the title attr OR
        # on the <use href="#<region-slug>"> child.
        region_label: str | None = None
        region_div = card.select_one(".region")
        if region_div:
            tt = (region_div.get("title") or "").strip()
            if tt.lower().startswith("region "):
                region_label = tt[7:].strip()
            else:
                use = region_div.find("use")
                if use is not None:
                    href = (
                        use.get("href") or use.get("xlink:href") or ""
                    ).lstrip("#")
                    region_label = (
                        href.replace("-", " ").title() if href else None
                    )
        # Version tag from .bannertag class or in-title keyword.
        version_label: str | None = None
        bt = card.select_one(".bannertag")
        if bt is not None:
            classes = bt.get("class") or []
            for c in classes:
                if c not in ("bannertag", "region"):
                    version_label = c.title()
                    break
        if not version_label:
            for kw in ("Hack", "Pirate", "Beta", "Demo", "Proto", "Translation"):
                if kw.lower() in title_text.lower():
                    version_label = kw
                    break
        seen.add(external_id)
        sys_label = _SYSTEM_LABEL.get(
            console_slug, console_slug.replace("-", " ").title()
        )
        from grabarr.adapters._rom_helpers import score_title_relevance

        score = 50.0 + score_title_relevance(title_text, query)
        if version_label in {"Hack", "Pirate"}:
            score -= 15.0
        out.append(
            SearchResult(
                external_id=external_id,
                title=title_text,
                author=None,
                year=None,
                format="rom",
                language=language,
                size_bytes=typical_size.get(console_slug),
                quality_score=score,
                source_id=source_id,
                media_type=MediaType.GAME_ROM,
                metadata={
                    "cdromance_console": console_slug,
                    "cdromance_slug": game_slug,
                    "console_label": sys_label,
                    "region_label": region_label,
                    "version_label": version_label,
                    "size_is_estimate": True,
                },
            )
        )
    out.sort(key=lambda r: r.quality_score, reverse=True)
    return out[:limit]
