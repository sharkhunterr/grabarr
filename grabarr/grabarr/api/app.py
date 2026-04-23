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
from grabarr.api.metrics import router as metrics_router
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
    """Translating `.get(key, default)` shim over the ``settings`` table.

    Shelfmark's vendored code reads upstream env-style keys
    (``EXT_BYPASSER_URL``, ``AA_DONATOR_KEY`` …). We translate those to
    Grabarr's own namespaced keys (``bypass.flaresolverr_url``, …) and
    look them up in the warm ``settings_service`` cache. Returning
    ``_MISSING`` lets the proxy fall through to its env/builtin layers
    when we don't have an opinion.
    """

    def get(self, key: str, default: object = None) -> object:
        """Return a Grabarr-backed value, or ``default`` to let the proxy
        cascade (env var → built-in). The caller passes its own
        sentinel as ``default`` to distinguish "no opinion" from "None"."""
        from grabarr.core.settings_service import get_sync

        if key == "EXT_BYPASSER_URL":
            raw = (get_sync("bypass.flaresolverr_url", "") or "").strip()
            if not raw:
                return default
            # Accept either "host:port" or "host:port/v1" → return host:port.
            v = raw.rstrip("/")
            if v.endswith("/v1"):
                v = v[:-3]
            return v
        if key == "EXT_BYPASSER_PATH":
            raw = (get_sync("bypass.flaresolverr_url", "") or "").strip()
            if not raw:
                return default
            return "/v1"
        if key == "USING_EXTERNAL_BYPASSER":
            return get_sync("bypass.mode", "external") == "external"
        if key == "AA_DONATOR_KEY":
            from grabarr.core.config import load_settings

            try:
                s = load_settings()
            except Exception:  # noqa: BLE001
                return default
            return s.sources.anna_archive.member_key or default
        return default


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shutdown wiring."""
    # 1. Load settings.
    settings = load_settings()
    # 2. Configure logging with requested level/format + on-disk rotation.
    log_file: Path | None
    raw = settings.logging.file
    if raw in (None, "", "none", "off"):
        log_file = None
    elif raw in ("auto",):
        log_file = Path(settings.server.data_dir) / "logs" / "grabarr.log"
    else:
        p = Path(raw)
        log_file = p if p.is_absolute() else Path(settings.server.data_dir) / p
    configure_root(
        level=settings.logging.level,
        fmt=settings.logging.format,
        file_path=log_file,
    )
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
    # 5. Warm the sync settings cache, then bridge Shelfmark vendored code.
    from grabarr.core.settings_service import load_cache as load_settings_cache

    await load_settings_cache()
    install_shelfmark_bridge(_SettingsBackend())

    # 6. Start adapter health monitor + cleanup sweeper in the background.
    from grabarr.adapters.health import start_monitor, stop_monitor
    from grabarr.downloads.cleanup import start_sweeper, stop_sweeper

    await start_monitor(period_seconds=60)
    await start_sweeper()

    _log.info("Grabarr %s ready", __version__)

    yield

    _log.info("Grabarr shutting down")
    await stop_monitor()
    await stop_sweeper()
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
    app.include_router(metrics_router)
    app.include_router(admin_router)
    app.include_router(torznab_router)
    app.include_router(tracker_router)
    app.include_router(web_router)
    mount_static(app)
    return app


#: The ASGI callable uvicorn imports.
app: FastAPI = create_app()
