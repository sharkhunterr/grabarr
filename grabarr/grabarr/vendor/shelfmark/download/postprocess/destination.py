# Vendored from calibre-web-automated-book-downloader at v1.2.1 (019d36b27e3e8576eb4a4d6d76090ee442a05a44), 2026-04-23.
# Original path: shelfmark/download/postprocess/destination.py. Licensed MIT; see ATTRIBUTION.md.
# Import paths were rewritten per Constitution §III; no logic change.
from __future__ import annotations

import uuid
from pathlib import Path

from grabarr.core.logging import setup_logger
from grabarr.vendor.shelfmark.core.models import DownloadTask
from grabarr.vendor.shelfmark.core.utils import (
    get_destination,
    is_audiobook as check_audiobook,
)
from grabarr.vendor.shelfmark.download.fs import run_blocking_io
from grabarr.vendor.shelfmark.download.permissions_debug import log_path_permission_context
from grabarr.vendor.shelfmark.release_sources import get_source

logger = setup_logger("shelfmark.download.postprocess.pipeline")


def validate_destination(destination: Path, status_callback) -> bool:
    """Validate destination path is absolute, exists, and writable."""

    if not destination.is_absolute():
        logger.warning(f"Destination must be absolute: {destination}")
        status_callback("error", f"Destination must be absolute: {destination}")
        return False

    destination_exists = run_blocking_io(destination.exists)
    if destination_exists and not run_blocking_io(destination.is_dir):
        logger.warning(f"Destination is not a directory: {destination}")
        status_callback("error", f"Destination is not a directory: {destination}")
        return False

    if not destination_exists:
        try:
            run_blocking_io(destination.mkdir, parents=True, exist_ok=True)
        except (OSError, PermissionError) as exc:
            log_path_permission_context("destination_create", destination)
            logger.warning(f"Cannot create destination: {destination} ({exc})")
            status_callback("error", f"Cannot create destination: {destination} ({exc})")
            return False

    test_path = destination / f".shelfmark_write_test_{uuid.uuid4().hex}.tmp"

    try:
        test_content = (
            f"This file was created to verify if '{destination}' is writable. "
            "It should've been automatically deleted. Feel free to delete it.\n"
        )
        run_blocking_io(test_path.write_text, test_content)
        run_blocking_io(test_path.unlink, missing_ok=True)
    except Exception as exc:
        logger.debug("Destination write probe path: %s", test_path)
        log_path_permission_context("destination_write_probe", destination)
        logger.warning(f"Destination not writable: {destination} ({exc})")
        status_callback("error", f"Destination not writable: {destination} ({exc})")
        return False

    return True


def get_final_destination(task: DownloadTask) -> Path:
    """Get final destination directory, with content-type routing support."""

    is_audiobook = check_audiobook(task.content_type)

    try:
        override = get_source(task.source).get_destination_override(task)
    except ValueError:
        override = None

    if override:
        return override

    return get_destination(is_audiobook, user_id=task.user_id, username=task.username)
