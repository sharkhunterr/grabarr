"""Settings read/write service backed by the ``settings`` KV table."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select

from grabarr.core.logging import setup_logger
from grabarr.core.settings_model import Setting
from grabarr.db.session import session_scope

_log = setup_logger(__name__)


# Allowlist of keys editable via /api/settings (spec FR-011 + research R-8).
_ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "download.mode",
        "download.hybrid_threshold_mb",
        "download.timeout_seconds",
        "download.max_size_gb",
        "torrent.mode",
        "torrent.tracker_port",
        "torrent.listen_port_min",
        "torrent.listen_port_max",
        "torrent.seed_retention_hours",
        "torrent.max_concurrent_seeds",
        "bypass.mode",
        "bypass.flaresolverr_url",
        "bypass.flaresolverr_timeout_ms",
        "bypass.session_cache_ttl_min",
        "rate_limit.anna_archive.search_per_min",
        "rate_limit.anna_archive.parallel_downloads",
        "rate_limit.libgen.requests_per_min",
        "rate_limit.zlibrary.requests_per_min",
        "rate_limit.zlibrary.daily_quota",
        "rate_limit.internet_archive.requests_per_min",
        "metadata.ia_contact_email",
        "metadata.user_agent_suffix",
        "notifications.flap_cooldown_minutes",
    }
)


_DEFAULTS: dict[str, Any] = {
    "download.mode": "sync",
    "download.hybrid_threshold_mb": 50,
    "download.timeout_seconds": 300,
    "download.max_size_gb": 5.0,
    "torrent.mode": "active_seed",
    "torrent.tracker_port": 8999,
    "torrent.listen_port_min": 45000,
    "torrent.listen_port_max": 45100,
    "torrent.seed_retention_hours": 24,
    "torrent.max_concurrent_seeds": 100,
    "bypass.mode": "external",
    "bypass.flaresolverr_url": "http://flaresolverr:8191/v1",
    "bypass.flaresolverr_timeout_ms": 120000,
    "bypass.session_cache_ttl_min": 30,
    "rate_limit.anna_archive.search_per_min": 30,
    "rate_limit.anna_archive.parallel_downloads": 2,
    "rate_limit.libgen.requests_per_min": 60,
    "rate_limit.zlibrary.requests_per_min": 10,
    "rate_limit.zlibrary.daily_quota": 10,
    "rate_limit.internet_archive.requests_per_min": 30,
    "metadata.ia_contact_email": "",
    "metadata.user_agent_suffix": "",
    "notifications.flap_cooldown_minutes": 10,
}


# ---- Synchronous cache --------------------------------------------------
#
# The Shelfmark bridge (``_SettingsBackend.get`` in app.py) and other
# adapters read settings from plain synchronous code paths — vendored
# Shelfmark's cascade, rate-limiter setup, etc. To avoid spinning an
# event loop from inside sync code, we warm an in-memory cache at
# startup and refresh it on every mutation.
_cache: dict[str, Any] = dict(_DEFAULTS)


def get_sync(key: str, default: Any = None) -> Any:
    """Synchronous lookup in the warm cache (falls back to ``default``)."""
    return _cache.get(key, default)


async def load_cache() -> None:
    """Warm the sync cache from the DB. Call once at startup."""
    _cache.clear()
    _cache.update(_DEFAULTS)
    async with session_scope() as session:
        rows = await session.execute(select(Setting))
        for r in rows.scalars().all():
            _cache[r.key] = r.value


async def get_all() -> dict[str, Any]:
    """Return every setting as a flat dict (DB value > default)."""
    async with session_scope() as session:
        rows = await session.execute(select(Setting))
        overrides = {r.key: r.value for r in rows.scalars().all()}
    out = dict(_DEFAULTS)
    out.update(overrides)
    # Keep the sync cache fresh with whatever we just read.
    _cache.clear()
    _cache.update(out)
    return out


async def update_many(patch: dict[str, Any]) -> dict[str, Any]:
    """Upsert every key in ``patch`` whose name is allowlisted.

    Silently ignores unknown keys (matches how pydantic-settings treats
    ``extra='ignore'``). Returns the new full settings snapshot.
    """
    accepted = {k: v for k, v in patch.items() if k in _ALLOWED_KEYS}
    rejected = set(patch) - set(accepted)
    if rejected:
        _log.info("ignored unknown settings keys: %s", sorted(rejected))
    if not accepted:
        return await get_all()
    now = dt.datetime.now(dt.UTC)
    async with session_scope() as session:
        rows = await session.execute(select(Setting).where(Setting.key.in_(accepted.keys())))
        existing = {r.key: r for r in rows.scalars().all()}
        for key, value in accepted.items():
            if key in existing:
                existing[key].value = value
                existing[key].updated_at = now
            else:
                session.add(Setting(key=key, value=value, updated_at=now))
    return await get_all()


async def get_one(key: str, default: Any = None) -> Any:
    """Return a single key (DB > default > explicit fallback)."""
    if key not in _ALLOWED_KEYS:
        return default
    async with session_scope() as session:
        row = await session.execute(select(Setting).where(Setting.key == key))
        obj = row.scalar_one_or_none()
        if obj is not None:
            return obj.value
    return _DEFAULTS.get(key, default)
