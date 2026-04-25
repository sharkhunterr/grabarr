"""Profile CRUD service + adapter instantiation.

Spec FR-011 + FR-4.3. The service layer wraps the ``profiles`` table
with the business-rule guards the API layer enforces (cannot delete a
default, API-key hashing, slug uniqueness).
"""

from __future__ import annotations

import secrets
from typing import Any

import bcrypt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from grabarr.adapters.base import SourceAdapter
from grabarr.adapters.internet_archive import InternetArchiveAdapter
from grabarr.core.logging import setup_logger
from grabarr.core.registry import get_adapter_by_id
from grabarr.db.session import session_scope
from grabarr.profiles.models import Profile

_log = setup_logger(__name__)


class ProfileNotFound(Exception):
    """Raised when no profile matches the given slug or id."""


class ProfileDefaultProtected(Exception):
    """Raised on attempted deletion of a default profile."""


class ProfileSlugConflict(Exception):
    """Raised when a slug collides with an existing profile."""


async def list_profiles() -> list[Profile]:
    async with session_scope() as session:
        rows = await session.execute(select(Profile).order_by(Profile.slug))
        return list(rows.scalars().all())


async def get_profile_by_slug(slug: str) -> Profile:
    async with session_scope() as session:
        row = await session.execute(select(Profile).where(Profile.slug == slug))
        obj = row.scalar_one_or_none()
        if obj is None:
            raise ProfileNotFound(slug)
        return obj


async def verify_api_key(slug: str, plaintext: str) -> bool:
    """Return True if ``plaintext`` matches the profile's hashed key."""
    try:
        profile = await get_profile_by_slug(slug)
    except ProfileNotFound:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode(), profile.api_key_hash.encode())
    except (ValueError, AttributeError):
        return False


async def regenerate_api_key(slug: str) -> str:
    """Mint a fresh API key. Invalidates the previous one immediately."""
    plaintext = secrets.token_urlsafe(32)
    digest = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=10)).decode()
    async with session_scope() as session:
        row = await session.execute(select(Profile).where(Profile.slug == slug))
        obj = row.scalar_one_or_none()
        if obj is None:
            raise ProfileNotFound(slug)
        obj.api_key_hash = digest
        obj.api_key_plain = plaintext
    return plaintext


async def get_or_mint_api_key(slug: str) -> str:
    """Return the current plaintext key, minting one only if missing.

    Unlike :func:`regenerate_api_key`, this NEVER rotates an existing
    key — it's safe to call on every page load.
    """
    async with session_scope() as session:
        row = await session.execute(select(Profile).where(Profile.slug == slug))
        obj = row.scalar_one_or_none()
        if obj is None:
            raise ProfileNotFound(slug)
        if obj.api_key_plain:
            return obj.api_key_plain
        # Migrated or legacy row without plaintext — mint one now.
        plaintext = secrets.token_urlsafe(32)
        digest = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=10)).decode()
        obj.api_key_hash = digest
        obj.api_key_plain = plaintext
        return plaintext


async def create_profile(payload: dict[str, Any]) -> tuple[Profile, str]:
    """Create a non-default profile; return ``(profile, api_key_plaintext)``."""
    plaintext = secrets.token_urlsafe(32)
    digest = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=10)).decode()
    async with session_scope() as session:
        profile = Profile(
            slug=payload["slug"],
            name=payload["name"],
            description=payload.get("description"),
            media_type=payload["media_type"],
            sources=payload.get("sources", []),
            filters=payload.get("filters", {}),
            mode=payload.get("mode", "first_match"),
            newznab_categories=payload.get("newznab_categories", []),
            download_mode_override=payload.get("download_mode_override"),
            torrent_mode_override=payload.get("torrent_mode_override"),
            enabled=payload.get("enabled", True),
            api_key_hash=digest,
            api_key_plain=plaintext,
            is_default=False,
        )
        session.add(profile)
        try:
            await session.flush()
        except IntegrityError as exc:
            raise ProfileSlugConflict(payload["slug"]) from exc
        return profile, plaintext


async def delete_profile(slug: str) -> None:
    async with session_scope() as session:
        row = await session.execute(select(Profile).where(Profile.slug == slug))
        obj = row.scalar_one_or_none()
        if obj is None:
            raise ProfileNotFound(slug)
        if obj.is_default:
            raise ProfileDefaultProtected(slug)
        await session.delete(obj)


async def update_profile(slug: str, patch: dict[str, Any]) -> Profile:
    """Apply a partial update. Returns the updated row.

    ``patch`` may contain any subset of: name, description, sources,
    filters, mode, newznab_categories, download_mode_override,
    torrent_mode_override, enabled. ``slug`` cannot be changed via
    PATCH — rename via duplicate+delete instead.
    """
    import datetime as dt

    mutable = {
        "name",
        "description",
        "sources",
        "filters",
        "mode",
        "newznab_categories",
        "download_mode_override",
        "torrent_mode_override",
        "enabled",
    }
    async with session_scope() as session:
        row = await session.execute(select(Profile).where(Profile.slug == slug))
        obj = row.scalar_one_or_none()
        if obj is None:
            raise ProfileNotFound(slug)
        for key, value in patch.items():
            if key not in mutable:
                continue
            setattr(obj, key, value)
        obj.updated_at = dt.datetime.now(dt.UTC)
        return obj


async def duplicate_profile(slug: str, new_slug: str) -> tuple[Profile, str]:
    """Clone a profile under ``new_slug`` with a fresh API key.

    The copy is never marked ``is_default=True`` — even if the source
    was a default, the duplicate is user-owned and deletable.
    """
    plaintext = secrets.token_urlsafe(32)
    digest = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=10)).decode()
    async with session_scope() as session:
        row = await session.execute(select(Profile).where(Profile.slug == slug))
        src = row.scalar_one_or_none()
        if src is None:
            raise ProfileNotFound(slug)
        copy = Profile(
            slug=new_slug,
            name=f"{src.name} (copy)",
            description=src.description,
            media_type=src.media_type,
            sources=list(src.sources or []),
            filters=dict(src.filters or {}),
            mode=src.mode,
            newznab_categories=list(src.newznab_categories or []),
            download_mode_override=src.download_mode_override,
            torrent_mode_override=src.torrent_mode_override,
            enabled=True,
            api_key_hash=digest,
            api_key_plain=plaintext,
            is_default=False,
        )
        session.add(copy)
        try:
            await session.flush()
        except IntegrityError as exc:
            raise ProfileSlugConflict(new_slug) from exc
        return copy, plaintext


# ---- Adapter instantiation per profile -----------------------------------

# Process-wide adapter cache. Instances are keyed by source_id so we
# re-use token buckets and cached state across requests.
_ADAPTER_INSTANCES: dict[str, SourceAdapter] = {}


def get_adapter_instance(source_id: str) -> SourceAdapter | None:
    """Return a singleton adapter instance for ``source_id``.

    Returns ``None`` if the id is not registered (unknown plugin).
    Construction uses the adapter's default constructor; settings are
    applied lazily via ``shelfmark_config_proxy`` for vendored adapters
    and via env/config for the native IA adapter.
    """
    existing = _ADAPTER_INSTANCES.get(source_id)
    if existing is not None:
        return existing
    cls = get_adapter_by_id(source_id)
    if cls is None:
        return None

    # IA adapter wants constructor args; others default.
    if cls is InternetArchiveAdapter:
        import os

        from grabarr.core.settings_service import get_sync

        contact = os.environ.get("GRABARR_IA_CONTACT_EMAIL", "") or (
            get_sync("sources.internet_archive.contact_email", "") or ""
        )
        suffix = os.environ.get("GRABARR_IA_UA_SUFFIX", "") or (
            get_sync("sources.internet_archive.user_agent_suffix", "") or ""
        )
        # Optional account login: env var > settings table > empty.
        login_email = os.environ.get("GRABARR_IA_LOGIN_EMAIL", "") or (
            get_sync("sources.internet_archive.login_email", "") or ""
        )
        login_password = os.environ.get("GRABARR_IA_LOGIN_PASSWORD", "") or (
            get_sync("sources.internet_archive.login_password", "") or ""
        )
        instance = cls(  # type: ignore[call-arg]
            contact_email=contact,
            user_agent_suffix=suffix,
            login_email=login_email,
            login_password=login_password,
        )
    else:
        try:
            instance = cls()  # type: ignore[call-arg]
        except TypeError:
            # Adapter requires constructor args but we have no config;
            # return None so the orchestrator skips it cleanly.
            return None

    _ADAPTER_INSTANCES[source_id] = instance
    return instance
