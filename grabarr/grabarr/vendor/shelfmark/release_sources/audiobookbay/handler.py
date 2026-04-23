# Vendored from calibre-web-automated-book-downloader at v1.2.1 (019d36b27e3e8576eb4a4d6d76090ee442a05a44), 2026-04-23.
# Original path: shelfmark/release_sources/audiobookbay/handler.py. Licensed MIT; see ATTRIBUTION.md.
# Import paths were rewritten per Constitution §III; no logic change.
"""AudiobookBay download handler - resolves magnet links and uses shared client lifecycle."""

from typing import Callable, Optional
from urllib.parse import urlparse

from grabarr.vendor.shelfmark._grabarr_adapter import shelfmark_config_proxy as config
from grabarr.core.logging import setup_logger
from grabarr.vendor.shelfmark.core.models import DownloadTask
from grabarr.vendor.shelfmark.download.clients import DownloadClient, get_client, list_configured_clients
from grabarr.vendor.shelfmark.download.clients.base_handler import DownloadRequest, ExternalClientHandler
from grabarr.vendor.shelfmark.release_sources import register_handler
from grabarr.vendor.shelfmark.release_sources.audiobookbay import scraper
from grabarr.vendor.shelfmark.release_sources.audiobookbay.utils import normalize_hostname

logger = setup_logger(__name__)


@register_handler("audiobookbay")
class AudiobookBayHandler(ExternalClientHandler):
    """Handler for AudiobookBay downloads via configured torrent client."""

    @staticmethod
    def _resolve_detail_url(task: DownloadTask) -> Optional[str]:
        """Resolve ABB detail URL from queued task metadata."""
        source_url = (task.source_url or "").strip()
        if source_url:
            return source_url

        # Backward-compat: older tests and some legacy flows used task_id as URL.
        task_id = (task.task_id or "").strip()
        if task_id.startswith(("http://", "https://")):
            return task_id
        return None

    def _get_client(self, protocol: str) -> Optional[DownloadClient]:
        """Compatibility shim so module-level patching still works in tests."""
        return get_client(protocol)

    def _list_configured_clients(self) -> list[str]:
        """Compatibility shim so module-level patching still works in tests."""
        return list_configured_clients()

    def _resolve_download(
        self,
        task: DownloadTask,
        status_callback: Callable[[str, Optional[str]], None],
    ) -> Optional[DownloadRequest]:
        """Resolve ABB detail page into a magnet-link download request."""
        detail_url = self._resolve_detail_url(task)
        if not detail_url:
            status_callback("error", "Missing AudiobookBay details URL")
            logger.warning(f"Missing details URL for AudiobookBay task: {task.task_id}")
            return None

        hostname = normalize_hostname(config.get("ABB_HOSTNAME", ""))
        if not hostname:
            hostname = normalize_hostname(urlparse(detail_url).hostname)

        status_callback("resolving", "Extracting magnet link")
        magnet_link = scraper.extract_magnet_link(detail_url, hostname)

        if not magnet_link:
            status_callback("error", "Failed to extract magnet link from detail page")
            return None

        logger.info(f"Extracted magnet link for task {task.task_id}")

        return DownloadRequest(
            url=magnet_link,
            protocol="torrent",
            release_name=task.title or "Unknown",
            expected_hash=None,
        )

    def cancel(self, task_id: str) -> bool:
        """Cancel an in-progress download.

        Shelfmark can stop waiting via the queue cancel flag, but once a magnet has
        been sent to the torrent client we do not remove it client-side. Users must
        cancel/remove it in their torrent client UI.
        """
        logger.debug(f"Cancel requested for AudiobookBay task: {task_id}")
        return False
