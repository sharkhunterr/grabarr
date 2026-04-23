"""Download-mode dispatcher (spec FR-017)."""

from __future__ import annotations

from pathlib import Path

from grabarr.core.enums import DownloadMode
from grabarr.core.logging import setup_logger
from grabarr.core.models import DownloadInfo
from grabarr.downloads.async_streaming import async_streaming_download
from grabarr.downloads.hybrid import hybrid_download
from grabarr.downloads.sync import sync_download
from grabarr.downloads.verification import VerificationReport

_log = setup_logger(__name__)


async def run_download(
    *,
    mode: DownloadMode,
    info: DownloadInfo,
    token: str,
    downloads_root: Path,
    expected_format: str | None,
    sync_timeout_seconds: int = 300,
    async_timeout_seconds: int = 1800,
    hybrid_threshold_bytes: int = 50 * 1024 * 1024,
    max_size_bytes: int = 5 * 1024 * 1024 * 1024,
) -> tuple[Path, int, str | None, VerificationReport]:
    """Run the HTTP download according to ``mode``.

    All three modes return the same tuple shape:
    ``(path, size_bytes, content_type, verification_report)``.
    """
    if mode == DownloadMode.SYNC:
        return await sync_download(
            info=info,
            token=token,
            downloads_root=downloads_root,
            expected_format=expected_format,
            timeout_seconds=sync_timeout_seconds,
            max_size_bytes=max_size_bytes,
        )
    if mode == DownloadMode.ASYNC_STREAMING:
        return await async_streaming_download(
            info=info,
            token=token,
            downloads_root=downloads_root,
            expected_format=expected_format,
            timeout_seconds=async_timeout_seconds,
            max_size_bytes=max_size_bytes,
        )
    # default: hybrid
    return await hybrid_download(
        info=info,
        token=token,
        downloads_root=downloads_root,
        expected_format=expected_format,
        threshold_bytes=hybrid_threshold_bytes,
        timeout_seconds=async_timeout_seconds,
        max_size_bytes=max_size_bytes,
    )
