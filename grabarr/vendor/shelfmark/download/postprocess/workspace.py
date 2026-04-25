# Vendored from calibre-web-automated-book-downloader at v1.2.1 (019d36b27e3e8576eb4a4d6d76090ee442a05a44), 2026-04-23.
# Original path: shelfmark/download/postprocess/workspace.py. Licensed MIT; see ATTRIBUTION.md.
# Import paths were rewritten per Constitution §III; no logic change.
from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

from grabarr.vendor.shelfmark.config import env as env_config
from grabarr.core.logging import setup_logger
from grabarr.vendor.shelfmark.core.models import DownloadTask
from grabarr.vendor.shelfmark.download.fs import run_blocking_io
from grabarr.vendor.shelfmark.download.staging import STAGE_NONE

from .types import OutputPlan

logger = setup_logger("shelfmark.download.postprocess.pipeline")


def _tmp_dir() -> Path:
    return env_config.TMP_DIR


def is_within_tmp_dir(path: Path) -> bool:
    """Legacy helper: True if path is inside TMP_DIR."""

    # Fast path: avoid `resolve()` (can block on NFS) for obviously-non-TMP paths.
    # This is a *negative* check only; for potential TMP paths we still resolve to
    # prevent symlink escapes from being treated as managed.
    tmp_dir = _tmp_dir()
    try:
        if path.is_absolute() and tmp_dir.is_absolute():
            if path != tmp_dir and tmp_dir not in path.parents:
                return False
    except Exception:
        # Fall back to the slower resolve-based check below.
        pass

    try:
        run_blocking_io(path.resolve).relative_to(run_blocking_io(tmp_dir.resolve))
        return True
    except (OSError, ValueError):
        return False


def is_managed_workspace_path(path: Path) -> bool:
    """True if Shelfmark should treat this path as mutable.

    The managed workspace is `TMP_DIR`. Anything outside it should be treated as
    read-only for safety (e.g. torrent seeding directories).
    """

    return is_within_tmp_dir(path)


def _is_original_download(path: Optional[Path], task: DownloadTask) -> bool:
    if not path or not task.original_download_path:
        return False
    try:
        original = Path(task.original_download_path)
        return run_blocking_io(path.resolve) == run_blocking_io(original.resolve)
    except (OSError, ValueError):
        return False


def safe_cleanup_path(path: Optional[Path], task: DownloadTask) -> None:
    """Remove a temp path only if it is safe and in our managed workspace."""

    if not path or _is_original_download(path, task):
        return

    if not is_managed_workspace_path(path):
        logger.debug("Skip cleanup (outside TMP_DIR) for task %s: %s", task.task_id, path)
        return

    try:
        if path.is_dir():
            run_blocking_io(shutil.rmtree, path, ignore_errors=True)
        elif path.exists():
            path.unlink(missing_ok=True)
    except (OSError, PermissionError) as exc:
        logger.warning("Cleanup failed for task %s (%s): %s", task.task_id, path, exc)


def cleanup_output_staging(
    output_plan: OutputPlan,
    working_path: Path,
    task: DownloadTask,
    cleanup_paths: Optional[List[Path]] = None,
) -> None:
    if output_plan.stage_action != STAGE_NONE:
        cleanup_target = output_plan.staging_dir
        if output_plan.staging_dir == _tmp_dir():
            cleanup_target = working_path
        safe_cleanup_path(cleanup_target, task)

    if cleanup_paths:
        for path in cleanup_paths:
            safe_cleanup_path(path, task)
