# Vendored from calibre-web-automated-book-downloader at v1.2.1 (019d36b27e3e8576eb4a4d6d76090ee442a05a44), 2026-04-23.
# Original path: shelfmark/core/__init__.py. Licensed MIT; see ATTRIBUTION.md.
# Import paths were rewritten per Constitution §III; no logic change.
"""Core module - shared models, queue, and utilities."""

from grabarr.vendor.shelfmark.core.models import QueueItem, SearchFilters, QueueStatus
from grabarr.vendor.shelfmark.core.queue import BookQueue, book_queue
from grabarr.core.logging import setup_logger
