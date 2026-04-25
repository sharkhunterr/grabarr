# Vendored from calibre-web-automated-book-downloader at v1.2.1 (019d36b27e3e8576eb4a4d6d76090ee442a05a44), 2026-04-23.
# Original path: shelfmark/download/postprocess/types.py. Licensed MIT; see ATTRIBUTION.md.
# Import paths were rewritten per Constitution §III; no logic change.
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from grabarr.vendor.shelfmark.download.staging import StageAction


@dataclass(frozen=True)
class TransferPlan:
    source_path: Path
    use_hardlink: bool
    allow_archive_extraction: bool
    hardlink_enabled: bool


@dataclass(frozen=True)
class OutputPlan:
    mode: str
    stage_action: StageAction
    staging_dir: Path
    allow_archive_extraction: bool
    transfer_plan: Optional[TransferPlan] = None


@dataclass(frozen=True)
class PreparedFiles:
    output_plan: OutputPlan
    working_path: Path
    files: List[Path]
    rejected_files: List[Path]
    cleanup_paths: List[Path]


@dataclass(frozen=True)
class PlanStep:
    name: str
    details: Dict[str, Any]
