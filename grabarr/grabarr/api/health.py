"""/healthz endpoint (spec FR-030).

Initial implementation is minimal — always returns ``200 OK`` with a
``status: ok`` body plus the app version. The US4 phase expands this to
per-subsystem status (database, flaresolverr, libtorrent_session,
internal_tracker, each adapter).
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter

from grabarr import __version__

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, object]:
    """Return a liveness+readiness snapshot."""
    return {
        "status": "ok",
        "version": __version__,
        "checked_at": dt.datetime.now(dt.UTC).isoformat(),
    }
