"""CLI entry point (``grabarr`` console script).

Starts uvicorn with the app factory. First-run setup (auto-generating
``config.yaml`` from ``config.example.yaml`` if missing) also happens
here.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import uvicorn


def _bootstrap_config(repo_root: Path) -> None:
    """If ``config.yaml`` is missing and ``config.example.yaml`` exists, copy it."""
    cfg = repo_root / "config.yaml"
    example = repo_root / "config.example.yaml"
    if cfg.exists() or not example.exists():
        return
    shutil.copy2(example, cfg)
    print(f"[grabarr] created {cfg} from config.example.yaml — review before next start", file=sys.stderr)


def main() -> None:
    """Entry point for the ``grabarr`` console script."""
    repo_root = Path.cwd()
    _bootstrap_config(repo_root)

    host = os.environ.get("GRABARR_HOST", "0.0.0.0")
    port = int(os.environ.get("GRABARR_PORT", "8080"))
    reload = os.environ.get("GRABARR_RELOAD", "").lower() in {"1", "true", "yes"}

    uvicorn.run(
        "grabarr.api.app:app",
        host=host,
        port=port,
        reload=reload,
        log_config=None,  # we configure logging ourselves in the lifespan
    )


if __name__ == "__main__":
    main()
