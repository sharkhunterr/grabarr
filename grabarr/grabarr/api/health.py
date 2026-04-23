"""/healthz endpoint (spec FR-030).

Reports per-subsystem status. Overall 200 when core subsystems
(database, libtorrent_session, internal_tracker) are up; 503 otherwise.
Adapter-level failures do NOT flip overall status — the service is
still usable on the remaining sources (FR-036).
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Any

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from grabarr import __version__
from grabarr.adapters.health_model import AdapterHealthRow
from grabarr.core.logging import setup_logger
from grabarr.core.registry import get_registered_adapters
from grabarr.db.session import session_scope

router = APIRouter(tags=["health"])
_log = setup_logger(__name__)


async def _check_database() -> dict[str, Any]:
    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "error": str(exc)[:200]}


async def _check_flaresolverr() -> dict[str, Any]:
    url = os.environ.get("GRABARR_SHELFMARK_EXT_BYPASSER_URL", "")
    if not url:
        return {"status": "disabled"}
    probe_url = url.rstrip("/").replace("/v1", "")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(probe_url + "/")
        return {"status": "ok" if r.status_code < 500 else "degraded", "url": probe_url}
    except httpx.HTTPError as exc:
        return {"status": "fail", "url": probe_url, "error": str(exc)[:120]}


def _check_libtorrent_session() -> dict[str, Any]:
    try:
        from grabarr.torrents import active_seed

        srv = active_seed._server
        if srv is None:
            return {"status": "idle"}
        return {"status": "ok", "active_torrents": srv.active_count()}
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "error": str(exc)[:120]}


async def _check_internal_tracker() -> dict[str, Any]:
    # The tracker is mounted on the main app — if this endpoint is
    # reachable at all, so is /announce.
    return {"status": "ok"}


async def _check_adapters() -> dict[str, Any]:
    ids = list(get_registered_adapters().keys())
    out: dict[str, Any] = {}
    async with session_scope() as session:
        rows = await session.execute(select(AdapterHealthRow))
        by_id = {r.adapter_id: r for r in rows.scalars().all()}
    for aid in ids:
        r = by_id.get(aid)
        if r is None:
            out[aid] = {"status": "unknown"}
        else:
            out[aid] = {
                "status": r.status,
                "reason": r.reason,
                "last_check_at": r.last_check_at.isoformat() if r.last_check_at else None,
                "consecutive_failures": r.consecutive_failures,
            }
    return out


@router.get("/healthz")
async def healthz() -> JSONResponse:
    """Aggregate health report (spec FR-030 + contracts/admin-api.md)."""
    db = await _check_database()
    flaresolverr = await _check_flaresolverr()
    lts = _check_libtorrent_session()
    tracker = await _check_internal_tracker()
    adapters = await _check_adapters()

    core_ok = db.get("status") == "ok" and lts.get("status") in {"ok", "idle"}
    overall = 200 if core_ok else 503
    body = {
        "status": "ok" if overall == 200 else "degraded",
        "version": __version__,
        "checked_at": dt.datetime.now(dt.UTC).isoformat(),
        "subsystems": {
            "database": db,
            "flaresolverr": flaresolverr,
            "libtorrent_session": lts,
            "internal_tracker": tracker,
            "adapters": adapters,
        },
    }
    return JSONResponse(content=body, status_code=overall)
