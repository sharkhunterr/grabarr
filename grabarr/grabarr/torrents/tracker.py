"""Minimal internal HTTP tracker (spec FR-8.1).

Always returns an empty peer list in bencoded form. For the webseed-
only MVP we don't need real peer coordination — BitTorrent clients
fetch pieces directly from the webseed URL and use the tracker only
as a liveness ping.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response

from grabarr.torrents.bencode import encode

router = APIRouter(tags=["tracker"])


@router.get("/announce")
async def announce(
    info_hash: bytes = Query(..., description="20-byte torrent info hash"),
    peer_id: bytes = Query(..., description="20-byte peer id"),
    port: int = Query(0, ge=0, le=65535),
    uploaded: int = Query(0, ge=0),
    downloaded: int = Query(0, ge=0),
    left: int = Query(0, ge=0),
    compact: int = Query(1, ge=0, le=1),
    event: str = Query("", description="optional: started|completed|stopped"),
    numwant: int = Query(50, ge=0, le=200),
) -> Response:
    """Return a bencoded 'no peers' response with a 30-minute interval.

    In the webseed-only MVP, every torrent has the webseed as its source
    of bytes; we don't coordinate peers. Clients that consume this
    torrent use the webseed URL directly per BEP-19.
    """
    body = {
        "interval": 1800,
        "min interval": 1800,
        "complete": 0,
        "incomplete": 0,
        "peers": b"" if compact == 1 else [],
    }
    return Response(content=encode(body), media_type="text/plain")
