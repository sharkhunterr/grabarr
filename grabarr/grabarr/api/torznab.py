"""Torznab endpoint (spec FR-6, contracts/torznab-xml.md).

Per-profile endpoints at ``/torznab/{slug}/api`` supporting caps,
search, book, movie, music. Authentication is the profile's bcrypt
API key (``?apikey=<plaintext>``). Downloads hand off to the torrent
server via ``/torznab/{slug}/download/{token}.torrent`` — wired in a
later phase together with the download manager.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from email.utils import format_datetime
from typing import Any
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

from pathlib import Path

import aiofiles
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from grabarr.core.categories import NEWZNAB_CATEGORIES
from grabarr.core.logging import setup_logger
from grabarr.downloads.service import (
    DownloadNotFound,
    get_download_by_token,
    prepare_and_generate_torrent,
    register_result_token,
)
from grabarr.profiles.models import Profile
from grabarr.profiles.orchestrator import orchestrate_search
from grabarr.profiles.service import (
    ProfileNotFound,
    get_profile_by_slug,
    verify_api_key,
)

router = APIRouter(tags=["torznab"])
_log = setup_logger(__name__)


def _xml_response(body: str, status_code: int = 200) -> Response:
    return Response(
        content=body,
        media_type="application/xml; charset=utf-8",
        status_code=status_code,
    )


def _torznab_error(code: int, description: str, status_code: int = 200) -> Response:
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<error code="{code}" description="{xml_escape(description)}"/>'
    )
    return _xml_response(body, status_code=status_code)


# ---- caps response -------------------------------------------------------


def _build_caps_xml(profile: Profile, base_url: str) -> str:
    cats = profile.newznab_categories or []
    categories = "\n".join(
        f'    <category id="{c}" name="{xml_escape(NEWZNAB_CATEGORIES.get(c, ""))}"/>'
        for c in cats
    )

    def avail(media: str) -> str:
        match profile.media_type:
            case "ebook" | "comic" | "magazine" | "paper":
                return "yes" if media == "book" else "no"
            case "music" | "audiobook":
                return "yes" if media == "music" else "no"
            case "video" | "software" | "game_rom":
                return "yes" if media == "movie" else "no"
        return "no"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<caps>\n"
        f'  <server version="1.0" title="Grabarr ({xml_escape(profile.name)})"\n'
        f'          strapline="Grabarr Torznab — profile {xml_escape(profile.slug)}"\n'
        f'          url="{xml_escape(base_url)}"/>\n'
        '  <limits max="100" default="50"/>\n'
        "  <searching>\n"
        '    <search available="yes" supportedParams="q"/>\n'
        f'    <book-search available="{avail("book")}" supportedParams="q,author,title"/>\n'
        f'    <movie-search available="{avail("movie")}" supportedParams="q"/>\n'
        f'    <music-search available="{avail("music")}" supportedParams="q,artist,album"/>\n'
        '    <tv-search available="no"/>\n'
        "  </searching>\n"
        "  <categories>\n"
        f"{categories}\n"
        "  </categories>\n"
        "</caps>\n"
    )


# ---- search response -----------------------------------------------------


def _guid_for(profile_slug: str, external_id: str) -> str:
    return f"grabarr:{profile_slug}:{external_id}"


# ISO 639 2→3 / language-name → ISO 639-1 normalisation. Sources return
# "en", "eng", "en-US", "English", "français" — Bookshelf only accepts the
# two-letter code. We keep a short allowlist + fallback to the first two
# chars of anything else, which catches most non-English cases.
_LANG_ALIASES = {
    "en": "en", "eng": "en", "en-us": "en", "en-gb": "en", "english": "en",
    "fr": "fr", "fre": "fr", "fra": "fr", "french": "fr", "français": "fr", "francais": "fr",
    "de": "de", "ger": "de", "deu": "de", "german": "de", "deutsch": "de",
    "es": "es", "spa": "es", "spanish": "es", "español": "es", "espanol": "es",
    "it": "it", "ita": "it", "italian": "it", "italiano": "it",
    "pt": "pt", "por": "pt", "portuguese": "pt", "português": "pt",
    "ru": "ru", "rus": "ru", "russian": "ru",
    "zh": "zh", "chi": "zh", "zho": "zh", "chinese": "zh",
    "ja": "ja", "jpn": "ja", "japanese": "ja",
    "ko": "ko", "kor": "ko", "korean": "ko",
    "nl": "nl", "dut": "nl", "nld": "nl", "dutch": "nl", "nederlands": "nl",
    "pl": "pl", "pol": "pl", "polish": "pl",
    "sv": "sv", "swe": "sv", "swedish": "sv",
}


def _normalize_language(lang: str | None) -> str | None:
    """Collapse source-specific language strings to ISO 639-1 when possible."""
    if not lang:
        return None
    key = lang.strip().lower()
    if key in _LANG_ALIASES:
        return _LANG_ALIASES[key]
    # Fallback: take first two letters (covers "EN", "EN-US", etc.).
    first = key.split("-", 1)[0].split(";", 1)[0].strip()
    if len(first) == 2 and first.isalpha():
        return first
    return key[:2] if len(key) >= 2 else None


# Display labels for the [SOURCE] tag prepended to release titles.
# Spelled out rather than abbreviated so the operator sees the source
# at a glance without having to remember acronyms.
_SOURCE_LABEL: dict[str, str] = {
    "anna_archive": "Anna Archive",
    "libgen": "LibGen",
    "internet_archive": "Internet Archive",
    "zlibrary": "Z-Lib",
    "welib": "Welib",
}


def _build_release_title(r: Any) -> str:  # noqa: ANN401
    """Scene-style title so Bookshelf / Readarr parsers succeed.

    Format: ``[SOURCE] {Author} - {Title} ({year}) [FORMAT]`` with
    reasonable fallbacks for each missing field. The leading
    ``[SOURCE]`` tag lets the operator see at-a-glance which adapter
    served a given result (AA / LibGen / IA / Z-Lib / Welib) — useful
    to pick a release less likely to hit CF-bypass-only download paths.
    """
    source_label = _SOURCE_LABEL.get(r.source_id, r.source_id)
    parts: list[str] = []
    if r.author:
        parts.append(str(r.author).strip())
    parts.append(str(r.title).strip())
    out = " - ".join(parts)
    if r.year:
        out += f" ({r.year})"
    if r.format and r.format != "?":
        out += f" [{r.format.upper()}]"
    return f"[{source_label}] {out}"


def _pseudo_info_hash(profile_slug: str, source_id: str, external_id: str) -> str:
    """Stable 40-char hex derived from (profile, source, external_id).

    This is what we emit in the Torznab RSS ``infohash`` attr at search
    time — before the real ``.torrent`` has been generated. It lets
    Prowlarr dedup cross-indexer rows for the same item. The actual
    info_hash inside the bencoded ``.torrent`` (set at grab time) is
    different; Prowlarr doesn't verify the two match.
    """
    seed = f"{profile_slug}|{source_id}|{external_id}".encode()
    return hashlib.sha1(seed, usedforsecurity=False).hexdigest()


def _build_search_rss(
    profile: Profile,
    query: str,
    results_with_tokens: list[tuple],
    base_url: str,
) -> str:
    """Render RSS 2.0 + Torznab extension for a search result set.

    ``results_with_tokens`` is a list of ``(SearchResult, token_str)``
    pairs. Tokens are pre-registered in the ``downloads`` table so the
    *arr client can later resolve ``/download/{token}.torrent``.
    """
    primary_cat = (profile.newznab_categories or [0])[0]
    items_xml: list[str] = []

    for r, token in results_with_tokens:
        size = r.size_bytes or 0
        download_url = f"{base_url}/download/{quote(token)}.torrent"

        # pubDate drives "Age" column. Use the item's year when known
        # (Jan 1 UTC); fall back to "now".
        if r.year and 1000 <= r.year <= 9999:
            pub_date = format_datetime(
                dt.datetime(r.year, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
            )
        else:
            pub_date = format_datetime(dt.datetime.now(dt.UTC))

        # Build a scene-style release title so Bookshelf/Readarr's
        # parser can extract author/title/year/format cleanly.
        #   "{Author} - {Title} ({year}) [{FORMAT}]"
        release_title = _build_release_title(r)

        # Collect every optional torznab:attr into one list.
        extras: list[str] = []
        if r.author:
            extras.append(f'<torznab:attr name="author" value="{xml_escape(r.author)}"/>')
            extras.append(f'<torznab:attr name="artist" value="{xml_escape(r.author)}"/>')
        if r.year:
            extras.append(f'<torznab:attr name="year" value="{r.year}"/>')
            extras.append(f'<torznab:attr name="publishdate" value="{r.year}-01-01T00:00:00"/>')
        if r.language:
            norm_lang = _normalize_language(r.language)
            if norm_lang:
                extras.append(f'<torznab:attr name="language" value="{xml_escape(norm_lang)}"/>')
        # Book-specific attrs Bookshelf / Readarr look for.
        if r.title:
            extras.append(f'<torznab:attr name="booktitle" value="{xml_escape(r.title)}"/>')
            extras.append(f'<torznab:attr name="book" value="{xml_escape(r.title)}"/>')
        publisher = (r.metadata or {}).get("publisher")
        if publisher:
            extras.append(f'<torznab:attr name="publisher" value="{xml_escape(str(publisher))}"/>')
        isbn = (r.metadata or {}).get("isbn")
        if isbn:
            extras.append(f'<torznab:attr name="isbn" value="{xml_escape(str(isbn))}"/>')
        if r.format and r.format != "?":
            fmt = r.format.lower().lstrip(".")
            extras.append(f'<torznab:attr name="format" value="{xml_escape(fmt.upper())}"/>')
            extras.append(f'<torznab:attr name="codec" value="{xml_escape(fmt.upper())}"/>')
            # For audio: bitrate / quality are expected too; skipped for now.

        desc_bits: list[str] = []
        if r.format and r.format != "?":
            desc_bits.append(r.format.upper())
        desc_bits.append(f"via {r.source_id}")
        if r.language:
            desc_bits.append(f"lang:{_normalize_language(r.language) or r.language}")
        desc = " · ".join(desc_bits)

        items_xml.append(
            "    <item>\n"
            f"      <title>{xml_escape(release_title)}</title>\n"
            f"      <description>{xml_escape(desc)}</description>\n"
            f'      <guid isPermaLink="true">{xml_escape(download_url)}</guid>\n'
            f"      <pubDate>{pub_date}</pubDate>\n"
            f"      <size>{size}</size>\n"
            f"      <category>{primary_cat}</category>\n"
            f"      <link>{xml_escape(download_url)}</link>\n"
            f'      <enclosure url="{xml_escape(download_url)}" length="{size}" type="application/x-bittorrent"/>\n'
            f'      <torznab:attr name="category" value="{primary_cat}"/>\n'
            '      <torznab:attr name="seeders" value="1"/>\n'
            '      <torznab:attr name="peers" value="0"/>\n'
            '      <torznab:attr name="grabs" value="0"/>\n'
            '      <torznab:attr name="downloadvolumefactor" value="0"/>\n'
            '      <torznab:attr name="uploadvolumefactor" value="1"/>\n'
            f'      <torznab:attr name="infohash" value="{_pseudo_info_hash(profile.slug, r.source_id, r.external_id)}"/>\n'
            + "\n".join(f"      {x}" for x in extras)
            + ("\n" if extras else "")
            + "    </item>"
        )

    self_link = f"{base_url}/api?t=search&q={quote(query)}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"\n'
        '     xmlns:atom="http://www.w3.org/2005/Atom"\n'
        '     xmlns:torznab="http://torznab.com/schemas/2015/feed">\n'
        "  <channel>\n"
        f'    <atom:link href="{xml_escape(self_link)}" rel="self" type="application/rss+xml"/>\n'
        f"    <title>Grabarr :: {xml_escape(profile.name)}</title>\n"
        f"    <description>{xml_escape(profile.description or '')}</description>\n"
        f"    <link>{xml_escape(base_url)}/</link>\n"
        "    <language>en-us</language>\n"
        f"    <category>{primary_cat}</category>\n"
        + "\n".join(items_xml) + ("\n" if items_xml else "")
        + "  </channel>\n"
        "</rss>\n"
    )


# ---- route handler -------------------------------------------------------


# Ring buffer of recent torznab queries — for the debug dashboard.
# Each entry: {ts, client_ip, slug, t, q, author, title, cat, result_count,
# took_ms, http_status}. Capped at 200 so we don't grow unbounded.
from collections import deque as _deque

_TORZNAB_ACTIVITY: _deque = _deque(maxlen=200)


def recent_torznab_activity() -> list[dict]:
    """Snapshot of the recent torznab-query ring buffer (newest first)."""
    return list(reversed(_TORZNAB_ACTIVITY))


@router.get("/torznab/{slug}/api")
async def torznab_api(
    slug: str,
    request: Request,
    t: str = Query("caps", description="Torznab operation"),
    q: str = Query("", description="Search query"),
    apikey: str = Query("", description="Per-profile API key"),
    limit: int = Query(50, ge=1, le=100),
    # Torznab/Newznab supplementary query params the *arr apps may send;
    # we accept them gracefully and fold into the primary query.
    author: str = Query("", description="Book author"),
    title: str = Query("", description="Book title"),
    artist: str = Query("", description="Music artist"),
    album: str = Query("", description="Music album"),
    cat: str = Query("", description="Categories filter (comma-separated)"),
    offset: int = Query(0, ge=0),
) -> Response:
    """Main Torznab dispatch."""
    try:
        profile = await get_profile_by_slug(slug)
    except ProfileNotFound:
        return _torznab_error(200, f"unknown profile: {slug}", status_code=404)

    base_url = f"{request.url.scheme}://{request.url.netloc}/torznab/{slug}"

    if t == "caps":
        return _xml_response(_build_caps_xml(profile, base_url))

    # Everything else requires auth.
    if not apikey or not await verify_api_key(slug, apikey):
        body = '<?xml version="1.0" encoding="UTF-8"?><error code="100" description="Invalid API key"/>'
        return Response(
            content=body,
            media_type="application/xml",
            status_code=401,
            headers={"WWW-Authenticate": f'TorznabApiKey realm="grabarr:{slug}"'},
        )

    if t in {"search", "book", "movie", "music"}:
        # Fold supplementary fields into the search query.
        extra_terms = " ".join(x for x in (author, title, artist, album) if x)
        composite_q = " ".join(x for x in (q, extra_terms) if x).strip()
        # On empty query (Prowlarr's test + RSS feed probe), return a
        # representative sample per media type so clients see the feed
        # is alive. Bookshelf / Readarr always send a real query so
        # this path only affects Prowlarr's add-indexer test.
        if not composite_q:
            composite_q = {
                "ebook": "bestseller",
                "audiobook": "audiobook",
                "comic": "comic",
                "magazine": "magazine",
                "music": "album",
                "software": "software",
                "paper": "paper",
                "game_rom": "game",
                "video": "video",
            }.get(profile.media_type, "popular")
        import datetime as _dt
        import time as _time

        t0 = _time.monotonic()
        client = request.client.host if request.client else "?"
        try:
            results = await orchestrate_search(profile, composite_q, limit=limit)
        except Exception as exc:
            _log.warning("torznab: search crashed for %s q=%r: %s", slug, composite_q, exc)
            _TORZNAB_ACTIVITY.append({
                "ts": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
                "client_ip": client, "slug": slug, "t": t, "q": q,
                "author": author, "title": title, "cat": cat,
                "result_count": 0, "took_ms": int((_time.monotonic() - t0) * 1000),
                "http_status": 500, "error": f"{type(exc).__name__}: {exc}",
            })
            return _torznab_error(900, "search failed", status_code=500)

        # Register a pending Download row per result so the *arr client
        # can later resolve /download/{token}.torrent.
        results_with_tokens: list[tuple] = []
        for r in results:
            token = await register_result_token(profile=profile, result=r)
            results_with_tokens.append((r, token))

        _TORZNAB_ACTIVITY.append({
            "ts": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
            "client_ip": client, "slug": slug, "t": t, "q": q,
            "author": author, "title": title, "cat": cat,
            "result_count": len(results), "took_ms": int((_time.monotonic() - t0) * 1000),
            "http_status": 200,
        })

        return _xml_response(_build_search_rss(profile, composite_q, results_with_tokens, base_url))

    return _torznab_error(202, f"unsupported operation: {t}")


# ---- /download and /seed --------------------------------------------------


def _tracker_port() -> int:
    """Return the configured internal-tracker port.

    For now we pull from the env; future work will move this into
    ``settings.torrent.tracker_port`` and honour per-profile override.
    """
    import os

    return int(os.environ.get("GRABARR_TRACKER_PORT", "8999"))


@router.get("/torznab/{slug}/download/{token_ext}")
async def torznab_download(slug: str, token_ext: str, request: Request) -> Response:
    """Return the ``.torrent`` blob for ``token_ext`` (``{token}.torrent``)."""
    if not token_ext.endswith(".torrent"):
        raise HTTPException(status_code=404, detail="expected {token}.torrent")
    token = token_ext[: -len(".torrent")]
    host_base_url = f"{request.url.scheme}://{request.url.netloc}"
    try:
        blob = await prepare_and_generate_torrent(
            slug=slug,
            token=token,
            host_base_url=host_base_url,
            tracker_port=_tracker_port(),
        )
    except DownloadNotFound:
        raise HTTPException(status_code=404, detail="token not found or expired") from None
    return Response(
        content=blob.bencoded,
        media_type="application/x-bittorrent",
        headers={
            "Content-Disposition": f'attachment; filename="grabarr-{token[:10]}.torrent"',
            "X-Grabarr-Info-Hash": blob.info_hash,
            "X-Grabarr-Torrent-Mode": blob.mode.value,
            "X-Grabarr-Piece-Count": str(blob.piece_count),
            "X-Grabarr-Piece-Size": str(blob.piece_size),
        },
    )


@router.get("/torznab/{slug}/seed/{token}")
@router.head("/torznab/{slug}/seed/{token}")
async def torznab_seed(
    slug: str,
    token: str,
    range: str | None = Header(default=None),  # noqa: A002 (http header name)
) -> Response:
    """HTTP Range-aware file server (BEP-19 webseed)."""
    download = await get_download_by_token(token)
    if download is None or not download.file_path:
        raise HTTPException(status_code=404, detail="download not found or not ready")

    path = Path(download.file_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="file no longer on disk")

    file_size = path.stat().st_size
    content_type = download.content_type or "application/octet-stream"
    filename = path.name

    # Parse Range header (single-range only).
    start, end = 0, file_size - 1
    partial = False
    if range and range.lower().startswith("bytes="):
        try:
            spec = range.split("=", 1)[1].split(",", 1)[0]
            s, e = spec.split("-", 1)
            start = int(s) if s else 0
            end = int(e) if e else file_size - 1
            if 0 <= start <= end < file_size:
                partial = True
            else:
                raise ValueError
        except ValueError:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

    length = end - start + 1

    async def body() -> object:  # type: ignore[misc]
        async with aiofiles.open(path, "rb") as fh:
            await fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = await fh.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Content-Type": content_type,
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        return StreamingResponse(body(), status_code=206, headers=headers)
    return StreamingResponse(body(), status_code=200, headers=headers)
