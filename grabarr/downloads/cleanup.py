"""Retention + cleanup sweeper (spec FR-039, FR-039a).

Runs every 5 minutes, removing:
  - physical files whose seed-retention window elapsed
    (default 24 h from torrent generation, clarified default);
  - Downloads rows older than 30 days (FR-039);
  - bypass_sessions rows whose expires_at elapsed;
  - search_cache rows past TTL;
  - notifications_log rows older than 30 days;
  - tracker_peers rows whose last_seen_at elapsed (30 min).

The libtorrent session's own sweep of expired torrents goes via
:meth:`ActiveSeedServer.remove` in the same pass.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

from sqlalchemy import delete, select

from grabarr.bypass.models import BypassSession
from grabarr.core.logging import setup_logger
from grabarr.db.session import session_scope
from grabarr.downloads.models import Download
from grabarr.notifications.models import NotificationLog
from grabarr.profiles.search_cache_model import SearchCacheEntry
from grabarr.torrents.models import Torrent, TrackerPeer

_log = setup_logger(__name__)

_SWEEP_INTERVAL_SECONDS = 300
_PEER_TTL_SECONDS = 1800
_DOWNLOADS_HISTORY_DAYS = 30
_NOTIFICATIONS_RETENTION_DAYS = 30


async def sweep_once() -> dict[str, int]:
    """Run one sweep pass. Returns per-category delete counts."""
    now = dt.datetime.now(dt.UTC)
    stats: dict[str, int] = {}

    # 1. Expired torrents → remove from libtorrent session + drop file + DB row.
    async with session_scope() as session:
        rows = await session.execute(
            select(Torrent).where(Torrent.expires_at < now)
        )
        expired = list(rows.scalars().all())

    if expired:
        try:
            from grabarr.torrents import active_seed

            srv = active_seed._server
        except Exception:  # noqa: BLE001
            srv = None

        for t in expired:
            if srv is not None:
                srv.remove(t.info_hash)

        async with session_scope() as session:
            # Remove the files on disk + clear file_path on the Download.
            ids = [t.info_hash for t in expired]
            dl_rows = await session.execute(
                select(Download).where(Download.info_hash.in_(ids))
            )
            for dl in dl_rows.scalars().all():
                if dl.file_path:
                    try:
                        Path(dl.file_path).unlink(missing_ok=True)
                    except OSError as exc:  # noqa: BLE001
                        _log.warning("failed to unlink %s: %s", dl.file_path, exc)
                dl.file_path = None
                dl.file_removed_at = now
            await session.execute(
                delete(Torrent).where(Torrent.info_hash.in_(ids))
            )
    stats["torrents_expired"] = len(expired)

    # 2. Downloads history retention.
    cutoff = now - dt.timedelta(days=_DOWNLOADS_HISTORY_DAYS)
    async with session_scope() as session:
        r = await session.execute(
            delete(Download).where(Download.started_at < cutoff)
        )
        stats["downloads_rows"] = r.rowcount or 0

    # 3. Bypass session cache expiry.
    async with session_scope() as session:
        r = await session.execute(
            delete(BypassSession).where(BypassSession.expires_at < now)
        )
        stats["bypass_sessions"] = r.rowcount or 0

    # 4. Search cache TTL.
    async with session_scope() as session:
        r = await session.execute(
            delete(SearchCacheEntry).where(SearchCacheEntry.expires_at < now)
        )
        stats["search_cache"] = r.rowcount or 0

    # 5. Notifications log retention.
    n_cutoff = now - dt.timedelta(days=_NOTIFICATIONS_RETENTION_DAYS)
    async with session_scope() as session:
        r = await session.execute(
            delete(NotificationLog).where(NotificationLog.dispatched_at < n_cutoff)
        )
        stats["notifications_log"] = r.rowcount or 0

    # 6. Tracker peer TTL (30 min).
    peer_cutoff = now - dt.timedelta(seconds=_PEER_TTL_SECONDS)
    async with session_scope() as session:
        r = await session.execute(
            delete(TrackerPeer).where(TrackerPeer.last_seen_at < peer_cutoff)
        )
        stats["tracker_peers"] = r.rowcount or 0

    total = sum(stats.values())
    if total:
        _log.info("cleanup sweep: %s", stats)
    return stats


_sweeper_task: asyncio.Task | None = None


async def start_sweeper() -> None:
    """Register the background sweep loop."""
    global _sweeper_task
    if _sweeper_task is not None and not _sweeper_task.done():
        return

    async def _loop() -> None:
        # Stagger the first tick by 30 s so startup isn't busy.
        await asyncio.sleep(30)
        while True:
            try:
                await sweep_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                _log.warning("cleanup sweep failed: %s", exc)
            await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)

    _sweeper_task = asyncio.create_task(_loop(), name="grabarr-cleanup-sweeper")


async def stop_sweeper() -> None:
    global _sweeper_task
    if _sweeper_task is None:
        return
    _sweeper_task.cancel()
    try:
        await _sweeper_task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    _sweeper_task = None
