"""Alembic environment — async SQLAlchemy + aiosqlite.

Imports every ORM model module at import time so
``Base.metadata`` reflects the full schema for autogenerate.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from grabarr.db.base import Base

# Import every module that defines ORM models so Base.metadata is populated.
from grabarr.profiles.models import Profile  # noqa: F401
from grabarr.profiles.search_cache_model import SearchCacheEntry  # noqa: F401
from grabarr.downloads.models import Download  # noqa: F401
from grabarr.torrents.models import Torrent, TrackerPeer  # noqa: F401
from grabarr.bypass.models import BypassSession  # noqa: F401
from grabarr.notifications.models import (  # noqa: F401
    AppriseUrl,
    WebhookConfig,
    NotificationLog,
)
from grabarr.core.settings_model import Setting  # noqa: F401
from grabarr.adapters.health_model import AdapterHealthRow, ZLibraryQuota  # noqa: F401


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Honour GRABARR_* env vars so tests + Docker can override data_dir without
# editing alembic.ini. The alembic.ini value is the fallback.
from grabarr.core.config import get_settings  # noqa: E402
from pathlib import Path  # noqa: E402

_settings = get_settings()
_data_dir = Path(_settings.server.data_dir)
_data_dir.mkdir(parents=True, exist_ok=True)
config.set_main_option(
    "sqlalchemy.url",
    f"sqlite+aiosqlite:///{_data_dir}/grabarr.db",
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Offline (SQL-emitting) mode."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite ALTER TABLE workaround
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Online (connected) mode with aiosqlite."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=None,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
