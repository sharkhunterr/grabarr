# Vendored from calibre-web-automated-book-downloader at v1.2.1 (019d36b27e3e8576eb4a4d6d76090ee442a05a44), 2026-04-23.
# Original path: shelfmark/download/postprocess/steps.py. Licensed MIT; see ATTRIBUTION.md.
# Import paths were rewritten per Constitution §III; no logic change.
from __future__ import annotations

from typing import Any, List

from grabarr.core.logging import setup_logger

from .types import PlanStep

logger = setup_logger("shelfmark.download.postprocess.pipeline")


def record_step(steps: List[PlanStep], name: str, **details: Any) -> None:
    steps.append(PlanStep(name=name, details=details))


def log_plan_steps(task_id: str, steps: List[PlanStep]) -> None:
    if not steps:
        return
    summary = " -> ".join(step.name for step in steps)
    logger.debug("Processing plan for %s: %s", task_id, summary)
