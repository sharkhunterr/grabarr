"""Fernet-based encryption for stored Apprise URLs (spec FR-031 / data-model)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet

from grabarr.core.config import get_settings
from grabarr.core.logging import setup_logger

_log = setup_logger(__name__)

_KEY_FILENAME = ".fernet_key"


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Resolve the master key from config → env → generated-and-persisted."""
    settings = get_settings()
    key_material = settings.master_secret or os.environ.get("GRABARR_MASTER_SECRET", "")
    if not key_material:
        key_path = Path(settings.server.data_dir) / _KEY_FILENAME
        if key_path.exists():
            key_material = key_path.read_text().strip()
        else:
            key_material = Fernet.generate_key().decode()
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key_path.write_text(key_material)
            key_path.chmod(0o600)
            _log.info("generated new master secret at %s", key_path)
    # Fernet keys are 32 bytes url-safe-base64 encoded. If the operator
    # supplied arbitrary text, hash-stretch to 32 bytes.
    key = key_material.encode()
    if len(key) < 44 or not key.endswith(b"="):
        import base64
        import hashlib

        key = base64.urlsafe_b64encode(hashlib.sha256(key).digest())
    return Fernet(key)


def encrypt(value: str) -> bytes:
    return _get_fernet().encrypt(value.encode())


def decrypt(blob: bytes) -> str:
    return _get_fernet().decrypt(blob).decode()


def mask(url: str) -> str:
    """Return a UI-safe masked preview of an Apprise URL."""
    if "://" not in url:
        return "***"
    scheme, rest = url.split("://", 1)
    # Keep scheme + first/last token; blank middle.
    parts = rest.split("/", 2)
    head = parts[0][:3] + "***" if parts[0] else "***"
    tail = parts[-1][-3:] if parts[-1] else ""
    return f"{scheme}://{head}/.../{tail}" if tail else f"{scheme}://{head}/..."
