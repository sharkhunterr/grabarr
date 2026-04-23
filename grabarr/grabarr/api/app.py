"""FastAPI factory + lifespan.

The lifespan runs, in order:

1. Load settings from ``config.yaml`` / env.
2. Configure logging (level + format).
3. Run pending Alembic migrations (idempotent).
4. Seed default profiles if the ``profiles`` table is empty.
5. Install the Shelfmark config bridge so vendored code sees Grabarr's
   settings table.

At shutdown it disposes the SQLAlchemy engine. Torrent-session
persistence + scheduler shutdown will be added in US1/US4 work.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import select

from grabarr import __version__
from grabarr.api.admin import router as admin_router
from grabarr.api.health import router as health_router
from grabarr.api.torznab import router as torznab_router
from grabarr.torrents.tracker import router as tracker_router
from grabarr.web.routes import mount_static, router as web_router
from grabarr.core.config import install_shelfmark_bridge, load_settings
from grabarr.core.logging import configure_root, setup_logger
from grabarr.db.session import close_engine, session_scope
from grabarr.profiles.models import Profile

_log = setup_logger(__name__)


def _repo_root() -> Path:
    """Return the repo root (directory containing ``alembic.ini``)."""
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "alembic.ini").exists():
            return candidate
    return here.parents[2]


async def _run_migrations() -> None:
    """Run ``alembic upgrade head`` in a subprocess.

    Alembic's own env.py calls ``asyncio.run()`` at import time, which
    cannot be nested inside our already-running event loop. Shelling out
    sidesteps the loop-already-running issue and keeps Alembic's own
    async-engine bootstrap intact.
    """
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "-c",
        str(_repo_root() / "alembic.ini"),
        "upgrade",
        "head",
        cwd=str(_repo_root()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head failed (exit {proc.returncode}): "
            f"{stderr.decode(errors='replace')}"
        )


class _SettingsBackend:
    """Minimal `.get(key, default)` shim over the ``settings`` table.

    Used to wire the Shelfmark config proxy at startup. A proper
    service-layer cache + invalidation will land when the admin UI's
    ``PATCH /api/settings`` endpoint does.
    """

    async def _fetch(self, key: str) -> object | None:
        from grabarr.core.settings_model import Setting  # lazy to avoid cycles

        async with session_scope() as session:
            row = await session.execute(select(Setting.value).where(Setting.key == key))
            return row.scalar_one_or_none()

    def get(self, key: str, default: object = None) -> object:
        """Synchronous fallback — returns the built-in default.

        Shelfmark's vendored code calls ``config.get()`` synchronously
        from lots of code paths; a proper implementation would cache
        settings into a plain dict at startup. This minimal version
        defers that optimisation and always falls through to the proxy's
        env-var + built-in-defaults layers, which is safe for v1.0.
        """
        return default


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shutdown wiring."""
    # 1. Load settings.
    settings = load_settings()
    # 2. Configure logging with requested level/format.
    configure_root(level=settings.logging.level, fmt=settings.logging.format)
    _log.info("Grabarr %s starting", __version__)
    # 3. Run migrations.
    _log.info("running Alembic migrations")
    await _run_migrations()
    # 4. Seed defaults if empty.
    async with session_scope() as session:
        existing = await session.execute(select(Profile.slug).limit(1))
        if existing.scalar_one_or_none() is None:
            from grabarr.cli.seed_defaults import seed_defaults

            slugs = await seed_defaults()
            _log.info("seeded %d default profiles", len(slugs))
    # 5. Bridge Shelfmark vendored code to the settings backend.
    install_shelfmark_bridge(_SettingsBackend())
    _log.info("Grabarr %s ready", __version__)

    yield

    _log.info("Grabarr shutting down")
    # Persist libtorrent session state if the active-seed server was booted.
    try:
        from grabarr.torrents.active_seed import shutdown_active_seed_server

        shutdown_active_seed_server()
    except Exception as exc:  # noqa: BLE001
        _log.warning("libtorrent shutdown failed: %s", exc)
    await close_engine()


def create_app() -> FastAPI:
    """Construct the FastAPI app.

    Import this as the uvicorn target: ``uvicorn grabarr.api.app:app``.
    """
    app = FastAPI(
        title="Grabarr",
        description=(
            "Multi-source media indexer and download bridge for the *arr "
            "ecosystem."
        ),
        version=__version__,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(admin_router)
    app.include_router(torznab_router)
    app.include_router(tracker_router)
    app.include_router(web_router)
    mount_static(app)
    return app


#: The ASGI callable uvicorn imports.
app: FastAPI = create_app()
