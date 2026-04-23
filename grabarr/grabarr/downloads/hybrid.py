"""Hybrid download strategy (spec FR-017 / FR-7.4).

Probes ``Content-Length`` via HTTP HEAD. If the source advertises size
below the configured threshold (default 50 MB) — or refuses HEAD — we
fall through to :func:`grabarr.downloads.sync.sync_download`. For
known-large files we dispatch to
:func:`grabarr.downloads.async_streaming.async_streaming_download`.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from grabarr.core.logging import setup_logger
from grabarr.core.models import DownloadInfo
from grabarr.downloads.async_streaming import async_streaming_download
from grabarr.downloads.sync import sync_download
from grabarr.downloads.verification import VerificationReport

_log = setup_logger(__name__)


async def _probe_size(info: DownloadInfo) -> int | None:
    """Return the source's advertised ``Content-Length`` or ``None``."""
    if info.size_bytes is not None and info.size_bytes > 0:
        return info.size_bytes
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=10.0, write=10.0, pool=10.0),
            headers=dict(info.extra_headers or {}),
            follow_redirects=True,
        ) as client:
            r = await client.head(info.download_url)
        raw = r.headers.get("content-length")
        return int(raw) if raw and raw.isdigit() else None
    except httpx.HTTPError as exc:
        _log.debug("HEAD probe failed for %s: %s", info.download_url, exc)
        return None


async def hybrid_download(
    *,
    info: DownloadInfo,
    token: str,
    downloads_root: Path,
    expected_format: str | None,
    threshold_bytes: int = 50 * 1024 * 1024,
    timeout_seconds: int = 1800,
    max_size_bytes: int = 5 * 1024 * 1024 * 1024,
) -> tuple[Path, int, str | None, VerificationReport]:
    """Pick sync or async based on probed size."""
    probed = await _probe_size(info)
    if probed is not None and probed < threshold_bytes:
        _log.info(
            "hybrid → sync (size=%d, threshold=%d)", probed, threshold_bytes
        )
        return await sync_download(
            info=info,
            token=token,
            downloads_root=downloads_root,
            expected_format=expected_format,
            timeout_seconds=timeout_seconds,
            max_size_bytes=max_size_bytes,
        )
    _log.info(
        "hybrid → async_streaming (size=%s, threshold=%d)",
        "unknown" if probed is None else str(probed),
        threshold_bytes,
    )
    return await async_streaming_download(
        info=info,
        token=token,
        downloads_root=downloads_root,
        expected_format=expected_format,
        timeout_seconds=timeout_seconds,
        max_size_bytes=max_size_bytes,
    )
