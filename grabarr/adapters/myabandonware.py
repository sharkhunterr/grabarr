"""MyAbandonware source adapter — search + click-driven CDN download.

myabandonware.com hosts old PC / abandonware games (DOS, Windows 9x,
Mac, Amiga, etc.). Search returns ``/game/<slug>`` detail pages. Each
detail page has a ``<a class="button download">`` element that, when
clicked, makes JS reveal a signed CDN URL on
``d<n>.xp.myabandonware.com/t/<uuid>/<filename>`` inside the DOM.

Search:    GET https://www.myabandonware.com/search/q/<query>
Detail:    GET https://www.myabandonware.com/game/<slug>
                  → click .button.download, JS reveals archive anchor
Download:  https://d1.xp.myabandonware.com/t/<uuid>/<filename>.zip

The CDN accepts httpx GETs once we forward the standard browser
headers (Referer, Sec-Fetch-*) plus the session cookies (PHPSESSID,
CookieScriptConsent, etc.) captured during the click.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from urllib.parse import unquote, urlparse

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

# bypass.* imports deferred to runtime to avoid the package-discovery cycle.

_log = setup_logger(__name__)

_MAW_BASE = "https://www.myabandonware.com"
_GAME_HREF_RE = re.compile(r"^/game/([a-z0-9-]+)$")
_ARCHIVE_RE = re.compile(
    r'https?://[^"\s]+\.(?:zip|rar|7z|exe|tar\.gz|tgz|cue|iso)\b',
    re.IGNORECASE,
)


@register_adapter
class MyAbandonwareAdapter:
    """myabandonware.com source adapter."""

    id = "myabandonware"
    display_name = "MyAbandonware"
    supported_media_types = {MediaType.GAME_ROM}
    requires_cf_bypass = False  # No CF challenge — site is static-friendly
    supports_member_key = False
    supports_authentication = False

    def __init__(self) -> None:
        rate_limiter.configure(self.id, "search", per_minute=20)
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
        url = f"{_MAW_BASE}/search/q/{cleaned_q.replace(' ', '+')}"
        try:
            html = await fetch_html(url, prefer_internal=True, timeout=30)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterBypassError(
                f"myabandonware: fetch_html failed for {url}: {exc}"
            ) from exc
        return _parse_search_html(html, cleaned_q, self.id, limit)

    async def get_download_info(
        self,
        external_id: str,
        media_type: MediaType,  # noqa: ARG002
        query_hint: str | None = None,  # noqa: ARG002
    ) -> DownloadInfo:
        from grabarr.bypass.click_driver import fetch_session

        await rate_limiter.acquire(self.id, "download")
        # external_id is the game slug.
        game_url = f"{_MAW_BASE}/game/{external_id}"

        # Click ``.button.download`` on the /game/ page; JS reveals an
        # archive anchor (URL ending in .zip/.rar/.7z/.exe). Poll the
        # DOM until any such anchor appears.
        try:
            session = await asyncio.to_thread(
                fetch_session,
                game_url,
                settle_seconds=2.0,
                pre_action_js=(
                    "document.querySelector('a.button.download')?.click()"
                ),
                wait_until_ready_js=(
                    "Array.from(document.querySelectorAll('a')).some("
                    "a => /\\.(zip|rar|7z|exe|tgz|tar\\.gz|cue|iso)/i.test(a.href))"
                ),
                wait_timeout=15,
                timeout=60,
            )
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterBypassError(
                f"myabandonware: fetch_session on {game_url} failed: {exc}"
            ) from exc

        archive_match = _ARCHIVE_RE.search(session.html)
        if not archive_match:
            raise AdapterNotFound(
                f"myabandonware: no archive URL revealed on {game_url} "
                "(click on .button.download didn't surface a download link)"
            )
        cdn_url = archive_match.group(0)
        _log.info("myabandonware: signed CDN URL → %s", cdn_url[:120])

        headers: dict[str, str] = {
            "User-Agent": session.user_agent
            or (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Referer": game_url,
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


def _filename_from_url(url: str) -> str:
    try:
        path = urlparse(url).path
    except ValueError:
        return "rom.bin"
    return unquote(path.rsplit("/", 1)[-1] or "rom.bin")


def _parse_search_html(
    html: str, query: str, source_id: str, limit: int
) -> list[SearchResult]:
    """Extract result rows from MyAbandonware ``/search/q/<q>`` HTML.

    Card structure (Tailwind-style):

        <a class="name c-item-game__name" href="/game/<slug>">Title</a>
        <span class="c-item-game__platforms">DOS</span>
        <span class="c-item-game__year">2001</span>

    We pick the ``c-item-game__name`` anchor as the canonical row +
    walk siblings for the platform + year spans.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    out: list[SearchResult] = []
    # Use the .c-item-game__name anchors so we have one row per game.
    for a in soup.select("a.c-item-game__name"):
        href = a.get("href", "") or ""
        m = _GAME_HREF_RE.match(href)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen:
            continue
        title_text = a.get_text(strip=True)
        if not title_text or len(title_text) < 2:
            continue
        # Platform + year are sibling spans of the anchor.
        platform = ""
        year: int | None = None
        # Look forward in the parent for the spans (they appear after
        # the anchor inside the same card div).
        parent = a.parent
        if parent is not None:
            plat_span = parent.select_one("span.c-item-game__platforms")
            year_span = parent.select_one("span.c-item-game__year")
            if plat_span:
                platform = plat_span.get_text(strip=True)
            if year_span:
                yt = year_span.get_text(strip=True)
                if yt.isdigit() and 1970 <= int(yt) <= 2099:
                    year = int(yt)
        seen.add(slug)
        from grabarr.adapters._rom_helpers import score_title_relevance

        score = 50.0 + score_title_relevance(title_text, query)
        # Approximate size: most abandonware archives are 100 KB – 50 MB,
        # median ~5 MB. Stops Prowlarr / Bookshelf rendering "0 B".
        out.append(
            SearchResult(
                external_id=slug,
                title=title_text,  # bare; torznab adds [Console] tag
                author=None,
                year=year,
                format="zip",
                language=None,
                size_bytes=5 * 1024 * 1024,
                quality_score=score,
                source_id=source_id,
                media_type=MediaType.GAME_ROM,
                metadata={
                    "myabandonware_slug": slug,
                    "myabandonware_platform": platform or None,
                    "console_label": platform or "Abandonware",
                    "size_is_estimate": True,
                },
            )
        )
    out.sort(key=lambda r: r.quality_score, reverse=True)
    return out[:limit]
