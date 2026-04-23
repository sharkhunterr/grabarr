"""High-level download service — ties search results to the .torrent flow.

When the Torznab endpoint renders a search result, it calls
:func:`register_result_token` to stash the ``(profile, adapter, external_id,
media_type)`` tuple keyed by a random token. Later the *arr client hits
``/torznab/{slug}/download/{token}.torrent`` and the handler invokes
:func:`prepare_and_generate_torrent` to:

  1. Load the pending :class:`Download` row.
  2. Call the adapter's ``get_download_info``.
  3. Run the sync downloader.
  4. Build a webseed ``.torrent`` via :mod:`grabarr.torrents.webseed`.
  5. Persist the :class:`Torrent` row + update the Download status.
  6. Return the bencoded blob.
"""

from __future__ import annotations

import datetime as dt
import secrets
from pathlib import Path

from sqlalchemy import select

from grabarr.adapters.base import AdapterError
from grabarr.core.config import get_settings
from grabarr.core.enums import DownloadMode, DownloadStatus, MediaType, TorrentMode
from grabarr.core.logging import setup_logger
from grabarr.core.models import SearchResult
from grabarr.db.session import session_scope
from grabarr.downloads.models import Download
from grabarr.downloads.sync import SyncDownloadFailed, sync_download
from grabarr.profiles.models import Profile
from grabarr.profiles.service import get_adapter_instance
from grabarr.torrents.models import Torrent
from grabarr.torrents.webseed import TorrentBlob, build_webseed_torrent

_log = setup_logger(__name__)


class DownloadNotFound(Exception):
    """Raised when a token does not match any pending download."""


def _downloads_root() -> Path:
    return Path(get_settings().server.downloads_dir).resolve()


async def register_result_token(
    *,
    profile: Profile,
    result: SearchResult,
) -> str:
    """Insert a pending ``downloads`` row and return its URL-safe token.

    Called by the Torznab endpoint for every ``<item>`` it renders. The
    token is the one the *arr client will later request as
    ``/torznab/{slug}/download/{token}.torrent``.

    Returns the token.
    """
    token = secrets.token_urlsafe(24)
    async with session_scope() as session:
        session.add(
            Download(
                token=token,
                profile_id=profile.id,
                source_id=result.source_id,
                external_id=result.external_id,
                media_type=result.media_type.value,
                download_mode=DownloadMode.SYNC.value,
                torrent_mode=TorrentMode.WEBSEED.value,  # MVP default
                title=result.title,
                author=result.author,
                year=result.year,
                filename=result.title,  # replaced post-download
                size_bytes=result.size_bytes,
                content_type=None,
                magic_verified=False,
                file_path=None,
                info_hash=None,
                status=DownloadStatus.QUEUED.value,
            )
        )
    return token


async def prepare_and_generate_torrent(
    *,
    slug: str,
    token: str,
    host_base_url: str,
    tracker_port: int,
) -> TorrentBlob:
    """Main flow invoked from ``/torznab/{slug}/download/{token}.torrent``.

    ``host_base_url`` is like ``http://1.2.3.4:8080`` and is used to
    construct the webseed URL the .torrent references. ``tracker_port``
    is the internal tracker's port (default 8999) for the announce URL.
    """
    # 1. Load the pending row.
    async with session_scope() as session:
        row = await session.execute(select(Download).where(Download.token == token))
        dl = row.scalar_one_or_none()
        if dl is None:
            raise DownloadNotFound(token)
        if dl.status == DownloadStatus.SEEDING.value and dl.info_hash and dl.file_path:
            # Already prepared — regenerate the torrent blob for re-serving.
            return _rebuild_blob(dl, host_base_url, tracker_port)
        media_type = MediaType(dl.media_type)
        external_id = dl.external_id
        source_id = dl.source_id
        profile_slug = slug

    adapter = get_adapter_instance(source_id)
    if adapter is None:
        await _mark_failed(token, f"adapter {source_id!r} is not registered")
        raise DownloadNotFound(f"adapter {source_id} unavailable")

    # 2. Mark resolving, call adapter.get_download_info.
    await _set_status(token, DownloadStatus.RESOLVING)
    try:
        info = await adapter.get_download_info(external_id, media_type)
    except AdapterError as exc:
        await _mark_failed(token, f"adapter error: {exc}")
        raise
    await _annotate_resolve(token, size=info.size_bytes, content_type=info.content_type)

    # 3. Sync download + verify.
    await _set_status(token, DownloadStatus.DOWNLOADING)
    expected_format = _format_from_filename_hint(info.filename_hint) or None
    try:
        final_path, size_bytes, content_type, report = await sync_download(
            info=info,
            token=token,
            downloads_root=_downloads_root(),
            expected_format=expected_format,
        )
    except SyncDownloadFailed as exc:
        await _mark_failed(token, f"download failed: {exc}")
        raise

    # 4. Build webseed torrent.
    await _set_status(token, DownloadStatus.VERIFYING)
    webseed_url = f"{host_base_url}/torznab/{profile_slug}/seed/{token}"
    # Tracker shares the main HTTP server for the MVP; in a Docker
    # deployment it will move to its own port.
    announce_url = f"{host_base_url}/announce"
    blob = build_webseed_torrent(
        file_path=final_path,
        announce_url=announce_url,
        webseed_url=webseed_url,
        display_name=final_path.name,
    )

    # 5. Persist state.
    now = dt.datetime.now(dt.UTC)
    async with session_scope() as session:
        row = await session.execute(select(Download).where(Download.token == token))
        dl = row.scalar_one()
        dl.filename = final_path.name
        dl.size_bytes = size_bytes
        dl.content_type = content_type
        dl.magic_verified = report.passed
        dl.file_path = str(final_path)
        dl.info_hash = blob.info_hash
        dl.status = DownloadStatus.SEEDING.value
        dl.resolved_at = now
        dl.ready_at = now
        dl.seeded_at = now

        session.add(
            Torrent(
                info_hash=blob.info_hash,
                download_id=dl.id,
                mode=TorrentMode.WEBSEED.value,
                total_size_bytes=size_bytes,
                piece_size_bytes=blob.piece_size,
                piece_count=blob.piece_count,
                webseed_url=webseed_url,
                generated_at=now,
                expires_at=now + dt.timedelta(hours=24),
            )
        )
    return blob


async def get_download_by_token(token: str) -> Download | None:
    async with session_scope() as session:
        row = await session.execute(select(Download).where(Download.token == token))
        return row.scalar_one_or_none()


# --- helpers -------------------------------------------------------------


def _format_from_filename_hint(hint: str | None) -> str | None:
    if not hint:
        return None
    name = Path(hint).name
    if "." not in name:
        return None
    ext = name.rsplit(".", 1)[-1].lower()
    return ext or None


def _host(base_url: str) -> str:
    """Strip ``:port`` from ``base_url`` so we can substitute ``tracker_port``."""
    # Drop any trailing /path and ensure no trailing slash.
    clean = base_url.rstrip("/")
    # Split off the port if present.
    if "://" in clean:
        scheme, rest = clean.split("://", 1)
        host = rest.split("/", 1)[0].split(":", 1)[0]
        return f"{scheme}://{host}"
    return clean


def _rebuild_blob(dl: Download, host_base_url: str, tracker_port: int) -> TorrentBlob:
    """Re-emit the torrent blob for an already-prepared download."""
    path = Path(dl.file_path) if dl.file_path else None
    if path is None or not path.exists():
        raise DownloadNotFound(f"file no longer on disk for token {dl.token}")
    webseed_url = f"{host_base_url}/torznab/{dl.profile_id}/seed/{dl.token}"  # slug not known here; close enough
    announce_url = f"{_host(host_base_url)}:{tracker_port}/announce"
    return build_webseed_torrent(
        file_path=path,
        announce_url=announce_url,
        webseed_url=webseed_url,
        display_name=path.name,
    )


async def _set_status(token: str, status: DownloadStatus) -> None:
    async with session_scope() as session:
        row = await session.execute(select(Download).where(Download.token == token))
        dl = row.scalar_one_or_none()
        if dl is None:
            return
        dl.status = status.value


async def _annotate_resolve(token: str, size: int | None, content_type: str | None) -> None:
    async with session_scope() as session:
        row = await session.execute(select(Download).where(Download.token == token))
        dl = row.scalar_one_or_none()
        if dl is None:
            return
        if size is not None:
            dl.size_bytes = size
        if content_type is not None:
            dl.content_type = content_type
        dl.resolved_at = dt.datetime.now(dt.UTC)


async def _mark_failed(token: str, reason: str) -> None:
    async with session_scope() as session:
        row = await session.execute(select(Download).where(Download.token == token))
        dl = row.scalar_one_or_none()
        if dl is None:
            return
        dl.status = DownloadStatus.FAILED.value
        dl.failure_reason = reason[:500]
