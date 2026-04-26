"""Torrent-mode dispatcher.

Chooses between :mod:`grabarr.torrents.active_seed` and
:mod:`grabarr.torrents.webseed` based on ``settings.torrent.mode`` and
any per-profile ``torrent_mode_override``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from grabarr.core.enums import TorrentMode
from grabarr.core.logging import setup_logger
from grabarr.torrents.active_seed import ActiveSeedBlob, get_active_seed_server
from grabarr.torrents.webseed import TorrentBlob, build_webseed_torrent

_log = setup_logger(__name__)


@dataclass(frozen=True)
class GeneratedTorrent:
    """Uniform return type from :func:`generate_torrent` across modes.

    When ``magnet_uri`` is non-None the torrent comes from a magnet-only
    source (e.g. AudioBookBay): ``bencoded`` is empty bytes, ``mode`` is
    ``WEBSEED`` for accounting purposes, and the torznab download
    endpoint emits an HTTP 302 redirect to the magnet instead of
    serving torrent bytes. Most fields below are best-effort in that
    case (info_hash extracted from the magnet, piece_count = 0).
    """

    bencoded: bytes
    info_hash: str
    piece_count: int
    piece_size: int
    mode: TorrentMode
    magnet_uri: str | None = None


def generate_torrent(
    *,
    mode: TorrentMode,
    file_path: Path,
    announce_url: str,
    webseed_url: str,
    display_name: str | None = None,
) -> GeneratedTorrent:
    """Build a ``.torrent`` under ``mode``. Returns a uniform result."""
    if mode == TorrentMode.ACTIVE_SEED:
        server = get_active_seed_server()
        blob: ActiveSeedBlob = server.create_and_seed(
            file_path=file_path,
            announce_url=announce_url,
            display_name=display_name,
        )
        return GeneratedTorrent(
            bencoded=blob.bencoded,
            info_hash=blob.info_hash,
            piece_count=blob.piece_count,
            piece_size=blob.piece_size,
            mode=TorrentMode.ACTIVE_SEED,
        )

    # Default: webseed.
    webseed: TorrentBlob = build_webseed_torrent(
        file_path=file_path,
        announce_url=announce_url,
        webseed_url=webseed_url,
        display_name=display_name,
    )
    return GeneratedTorrent(
        bencoded=webseed.bencoded,
        info_hash=webseed.info_hash,
        piece_count=webseed.piece_count,
        piece_size=webseed.piece_size,
        mode=TorrentMode.WEBSEED,
    )
