"""Torznab endpoint (spec FR-6, contracts/torznab-xml.md).

Per-profile endpoints at ``/torznab/{slug}/api`` supporting caps,
search, book, movie, music. Authentication is the profile's bcrypt
API key (``?apikey=<plaintext>``). Downloads hand off to the torrent
server via ``/torznab/{slug}/download/{token}.torrent`` — wired in a
later phase together with the download manager.
"""

from __future__ import annotations

import datetime as dt
from email.utils import format_datetime
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from grabarr.core.categories import NEWZNAB_CATEGORIES
from grabarr.core.logging import setup_logger
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


def _build_search_rss(
    profile: Profile,
    query: str,
    results: list,
    base_url: str,
) -> str:
    """Render RSS 2.0 + Torznab extension for a search result set."""
    primary_cat = (profile.newznab_categories or [0])[0]
    items_xml: list[str] = []

    for r in results:
        size = r.size_bytes or 0
        # The token-based download URL won't work until the download
        # manager lands; emit the resolvable token stub anyway so Prowlarr
        # can parse the feed and the smoke test can verify shape.
        token = f"{profile.slug}--{xml_escape(str(r.external_id))[:60]}"
        download_url = f"{base_url}/download/{quote(token)}.torrent"

        pub_date = format_datetime(dt.datetime.now(dt.UTC))

        extras: list[str] = []
        if r.author:
            extras.append(f'<torznab:attr name="author" value="{xml_escape(r.author)}"/>')
        if r.year:
            extras.append(f'<torznab:attr name="year" value="{r.year}"/>')
        if r.language:
            extras.append(f'<torznab:attr name="language" value="{xml_escape(r.language)}"/>')

        desc = f"{r.format.upper()} via {r.source_id}"

        items_xml.append(
            "    <item>\n"
            f"      <title>{xml_escape(r.title)}</title>\n"
            f"      <description>{xml_escape(desc)}</description>\n"
            f'      <guid isPermaLink="true">{xml_escape(_guid_for(profile.slug, r.external_id))}</guid>\n'
            f"      <pubDate>{pub_date}</pubDate>\n"
            f"      <size>{size}</size>\n"
            f"      <category>{primary_cat}</category>\n"
            f"      <link>{xml_escape(download_url)}</link>\n"
            f'      <enclosure url="{xml_escape(download_url)}" length="{size}" type="application/x-bittorrent"/>\n'
            f'      <torznab:attr name="category" value="{primary_cat}"/>\n'
            '      <torznab:attr name="seeders" value="1"/>\n'
            '      <torznab:attr name="peers" value="0"/>\n'
            '      <torznab:attr name="downloadvolumefactor" value="0"/>\n'
            '      <torznab:attr name="uploadvolumefactor" value="1"/>\n'
            # Placeholder infohash — real one arrives with the torrent server.
            f'      <torznab:attr name="infohash" value="{"0" * 40}"/>\n'
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
        if not composite_q:
            return _xml_response(_build_search_rss(profile, "", [], base_url))
        try:
            results = await orchestrate_search(profile, composite_q, limit=limit)
        except Exception as exc:
            _log.warning("torznab: search crashed for %s q=%r: %s", slug, composite_q, exc)
            return _torznab_error(900, "search failed", status_code=500)
        return _xml_response(_build_search_rss(profile, composite_q, results, base_url))

    return _torznab_error(202, f"unsupported operation: {t}")
