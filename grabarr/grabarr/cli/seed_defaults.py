"""Idempotent default-profile seeder (spec FR-012, task T052).

Usage:

.. code-block:: bash

    uv run python -m grabarr.cli.seed_defaults

Also exposed as the ``grabarr-seed-defaults`` console script.
Safe to invoke multiple times: rows whose ``slug`` already exists are
left untouched.
"""

from __future__ import annotations

import asyncio
import secrets

import bcrypt
from sqlalchemy import select

from grabarr.core.logging import setup_logger
from grabarr.db.session import session_scope
from grabarr.profiles.defaults import DEFAULT_PROFILES
from grabarr.profiles.models import Profile

_log = setup_logger(__name__)


def _fresh_api_key_hash() -> tuple[str, str]:
    """Return ``(plaintext, bcrypt_hash)`` pair for a new API key."""
    plaintext = secrets.token_urlsafe(32)
    digest = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=10)).decode()
    return plaintext, digest


async def seed_defaults() -> list[str]:
    """Insert any missing default profiles. Return the list of slugs inserted."""
    inserted: list[str] = []
    async with session_scope() as session:
        for row in DEFAULT_PROFILES:
            existing = await session.execute(
                select(Profile.id).where(Profile.slug == row["slug"])
            )
            if existing.scalar_one_or_none() is not None:
                continue
            plaintext, digest = _fresh_api_key_hash()
            session.add(
                Profile(
                    slug=row["slug"],
                    name=row["name"],
                    description=row.get("description"),
                    media_type=row["media_type"],
                    sources=row["sources"],
                    filters=row["filters"],
                    mode=row["mode"],
                    newznab_categories=row["newznab_categories"],
                    download_mode_override=None,
                    torrent_mode_override=None,
                    enabled=True,
                    api_key_hash=digest,
                    api_key_plain=plaintext,
                    is_default=True,
                )
            )
            inserted.append(row["slug"])
            # API key is NOT logged. Operators reveal it via the Copy
            # Prowlarr Config UI action or POST /api/profiles/{slug}/
            # regenerate-key (Constitution Article XIII: no secrets in logs).
            _log.info("seeded default profile slug=%s", row["slug"])
    return inserted


def main() -> None:
    slugs = asyncio.run(seed_defaults())
    if slugs:
        print(f"seeded {len(slugs)} default profiles: {', '.join(slugs)}")
    else:
        print("no new default profiles to seed (all already present)")


if __name__ == "__main__":
    main()
