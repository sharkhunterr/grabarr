# Vendored from calibre-web-automated-book-downloader at v1.2.1 (019d36b27e3e8576eb4a4d6d76090ee442a05a44), 2026-04-23.
# Original path: shelfmark/download/postprocess/router.py. Licensed MIT; see ATTRIBUTION.md.
# Import paths were rewritten per Constitution §III; no logic change.
"""Output routing for post-download processing.

This module selects the appropriate output handler and invokes it.

Keeping this separate from `pipeline.py` avoids circular imports:

- output handlers depend on `pipeline`
- router depends on the output registry
"""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Optional

from grabarr.core.logging import setup_logger
from grabarr.vendor.shelfmark.core.models import DownloadTask, SearchMode
from grabarr.vendor.shelfmark.download.outputs import resolve_output_handler

logger = setup_logger(__name__)


def post_process_download(
    temp_file: Path,
    task: DownloadTask,
    cancel_flag: Event,
    status_callback,
    preserve_source_on_failure: bool = False,
) -> Optional[str]:
    """Post-process download using the selected output handler."""

    if task.search_mode is None:
        logger.warning(
            "Task %s: missing search_mode; defaulting to Direct mode behavior",
            task.task_id,
        )
    elif task.search_mode not in (SearchMode.DIRECT, SearchMode.UNIVERSAL):
        logger.warning(
            "Task %s: invalid search_mode=%s; defaulting to Direct mode behavior",
            task.task_id,
            task.search_mode,
        )

    output_handler = resolve_output_handler(task)
    if output_handler:
        logger.info("Task %s: using output mode %s", task.task_id, output_handler.mode)
        return output_handler.handler(
            temp_file,
            task,
            cancel_flag,
            status_callback,
            preserve_source_on_failure,
        )

    from grabarr.vendor.shelfmark.download.outputs.folder import process_folder_output

    logger.info("Task %s: using output mode folder", task.task_id)
    return process_folder_output(
        temp_file,
        task,
        cancel_flag,
        status_callback,
        preserve_source_on_failure,
    )
