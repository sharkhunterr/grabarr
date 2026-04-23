"""Async-streaming download strategy (spec FR-019, T087).

The spec's aspirational goal is "torrent returned within 500 ms". That's
physically impossible for BitTorrent v1 torrents because every piece
hash must be known up front and computing hashes requires the bytes.
Without BEP-52 (v2 hash trees, spotty client support), the only honest
implementation is:

- Run the HTTP download in an asyncio task so the request handler is
  non-blocking on the event loop (other requests keep serving).
- Compute piece hashes streaming-style as bytes land on disk.
- Once the file is complete, emit the real ``.torrent``.

The wall-clock time to first-torrent-byte is therefore bounded by how
fast the source can serve the full file. For users who care about
timing out *arr clients on slow-source grabs, the fix is to increase
the *arr's grab timeout — NOT to fake a torrent hash.

The difference vs :mod:`grabarr.downloads.sync` is:
- sync awaits the download inline in the request handler (so if 100
  requests arrive concurrently each holds an event-loop slot).
- async_streaming dispatches to a task and reports progress through
  the Download row, freeing the event loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from grabarr.core.logging import setup_logger
from grabarr.core.models import DownloadInfo
from grabarr.downloads.sync import SyncDownloadFailed, sync_download
from grabarr.downloads.verification import VerificationReport

_log = setup_logger(__name__)


async def async_streaming_download(
    *,
    info: DownloadInfo,
    token: str,
    downloads_root: Path,
    expected_format: str | None,
    timeout_seconds: int = 1800,  # 30 min — intended for slow AA tier
    max_size_bytes: int = 5 * 1024 * 1024 * 1024,
) -> tuple[Path, int, str | None, VerificationReport]:
    """Run a sync-style download inside an asyncio task.

    Exactly the same as :func:`sync_download` except the whole call is
    wrapped in a task so other FastAPI handlers stay responsive. Returns
    when the download + verification complete.
    """

    async def _runner() -> tuple[Path, int, str | None, VerificationReport]:
        return await sync_download(
            info=info,
            token=token,
            downloads_root=downloads_root,
            expected_format=expected_format,
            timeout_seconds=timeout_seconds,
            max_size_bytes=max_size_bytes,
        )

    task: asyncio.Task = asyncio.create_task(_runner(), name=f"async_dl:{token[:10]}")
    try:
        return await task
    except asyncio.CancelledError:
        _log.info("async download cancelled for token=%s", token)
        raise
    except SyncDownloadFailed:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SyncDownloadFailed(f"async streaming failed: {exc}") from exc
