"""Synchronous download strategy (spec FR-018, T073).

Streams the source file to ``/downloads/incoming/{token}/``, runs the
verification gates, and moves the file to ``/downloads/ready/{token}/``
on success. Returns ``(path, size_bytes, content_type)``.
"""

from __future__ import annotations

import re
from pathlib import Path

import aiofiles
import httpx

from grabarr.core.logging import setup_logger
from grabarr.core.models import DownloadInfo
from grabarr.downloads.verification import VerificationReport, verify_file

_log = setup_logger(__name__)

# Safe filename charset: letters, digits, dot, dash, underscore, space.
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._\- ]")


class SyncDownloadFailed(Exception):
    """Raised when the sync download cannot produce a verified file."""

    def __init__(self, message: str, report: VerificationReport | None = None) -> None:
        super().__init__(message)
        self.report = report


def _sanitize_filename(name: str) -> str:
    """Produce a safe filename — no path separators, limited charset."""
    # Take the basename first (avoid absorbing directories from adapter hints).
    name = Path(name).name or "download"
    name = _UNSAFE_CHARS.sub("_", name).strip()
    return name[:250] or "download"


async def sync_download(
    *,
    info: DownloadInfo,
    token: str,
    downloads_root: Path,
    expected_format: str | None,
    timeout_seconds: int = 300,
    max_size_bytes: int = 5 * 1024 * 1024 * 1024,
    chunk_size: int = 64 * 1024,
) -> tuple[Path, int, str | None, VerificationReport]:
    """Fetch ``info.download_url`` synchronously end-to-end.

    Returns ``(final_path, size_bytes, content_type, verification_report)``.
    Raises :class:`SyncDownloadFailed` on verification failure or excessive size.
    """
    incoming = downloads_root / "incoming" / token
    incoming.mkdir(parents=True, exist_ok=True)
    ready = downloads_root / "ready" / token
    ready.mkdir(parents=True, exist_ok=True)

    filename = _sanitize_filename(info.filename_hint)
    incoming_path = incoming / filename
    ready_path = ready / filename

    size_so_far = 0
    content_type: str | None = None

    timeout = httpx.Timeout(connect=30.0, read=float(timeout_seconds), write=30.0, pool=30.0)
    headers = dict(info.extra_headers or {})
    # Preserve adapter-supplied UA; default to httpx's otherwise.
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        async with client.stream("GET", info.download_url) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type")
            async with aiofiles.open(incoming_path, "wb") as out:
                async for chunk in response.aiter_bytes(chunk_size):
                    size_so_far += len(chunk)
                    if size_so_far > max_size_bytes:
                        raise SyncDownloadFailed(
                            f"source exceeded max_size_bytes={max_size_bytes}"
                        )
                    await out.write(chunk)

    report = verify_file(
        incoming_path,
        expected_format=expected_format,
        content_type=content_type,
        min_size_bytes=1,
        max_size_bytes=max_size_bytes,
    )
    if not report.passed:
        _log.warning(
            "sync download verification failed for %s: %s",
            incoming_path,
            report.reason,
        )
        raise SyncDownloadFailed(
            f"verification failed: {report.reason}", report=report
        )

    # Move incoming → ready only when verification passes.
    ready_path.write_bytes(incoming_path.read_bytes())
    incoming_path.unlink(missing_ok=True)

    return ready_path, size_so_far, content_type, report
