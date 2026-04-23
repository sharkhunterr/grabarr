"""Bridge between vendored Shelfmark code and Grabarr's own config + logger.

Shelfmark's business code expects:
  - `from shelfmark.core.config import config`  where `config` supports both
    `config.get(key, default)` and `config.ATTR_NAME` attribute access.
  - `from shelfmark.core.logger import setup_logger`  which returns a stdlib
    `logging.Logger`.

Per Constitution Article III clause 3, vendored files' imports of these two
modules are rewritten to this adapter so that we do NOT vendor Shelfmark's
actual config/logger (those are tightly coupled to Shelfmark's Flask app
and user-settings system, which Grabarr doesn't use).

This file is the ONLY piece of hand-authored code inside `grabarr/vendor/`.
Everything else is verbatim upstream.
"""

from __future__ import annotations

import os
from typing import Any


class ShelfmarkConfigProxy:
    """Dict-like + attribute-access config that Shelfmark vendored code reads.

    Reads are served in order:

    1. Grabarr ``settings`` table (injected at runtime by
       :func:`set_settings_backend`), which is the source of truth for every
       UI-mutable setting per research R-8.
    2. Environment variables (`GRABARR_SHELFMARK_<KEY>` or plain `<KEY>`),
       allowing operators to force a Shelfmark-specific value without
       routing it through the UI.
    3. A set of safe built-in fallbacks that keep Shelfmark code importable
       and usable even before Grabarr has finished booting (e.g. during
       Alembic migrations or in unit tests).

    Writes are intentionally silent (the vendored code rarely writes,
    and when it does we do NOT want those writes leaking back into
    Grabarr's canonical settings table).
    """

    # Conservative defaults that keep Shelfmark's cascade functional.
    # These mirror Shelfmark's own defaults; override them at runtime via
    # Grabarr's settings table rather than editing this file.
    _BUILTIN_DEFAULTS: dict[str, Any] = {
        # Anna's Archive
        "AA_DONATOR_KEY": "",
        "USE_CF_BYPASS": True,
        "CUSTOM_SCRIPT": "",
        # URL templates — Shelfmark builds these from mirrors at runtime
        # unless overridden.
        "AA_BASE_URL": "https://annas-archive.org",
        # Formats Grabarr cares about. Shelfmark uses this to sort results
        # and pick which file to grab; matches the union of per-MediaType
        # ladders in grabarr.adapters.internet_archive.
        "SUPPORTED_FORMATS": [
            "epub", "mobi", "azw3", "pdf", "djvu", "cbz", "cbr",
            "mp3", "m4a", "m4b", "flac", "ogg", "opus", "wav",
            "zip", "iso", "7z", "rar",
        ],
        # Slow-source priority — Shelfmark honours this ordering within
        # the AA cascade. Matches Constitution Article VII.
        "SOURCE_PRIORITY": [
            "welib", "aa-slow-nowait", "aa-slow-wait", "aa-slow",
            "libgen", "zlib", "ipfs",
        ],
        "FAST_SOURCES_DISPLAY": ["aa-fast"],
        # File naming
        "FILE_ORGANIZATION": "rename",
        # Legacy Shelfmark settings we do not use but that vendored code
        # may touch in conditional branches.
        "USE_BOOKLORE": False,
        "ENABLE_EMAIL_OUTPUT": False,
    }

    def __init__(self) -> None:
        self._backend: Any | None = None

    # ---- backend wiring -------------------------------------------------

    def _bind_backend(self, backend: Any) -> None:
        """Inject Grabarr's settings backend.

        Called once at application startup by
        :func:`grabarr.core.config.install_shelfmark_bridge`. Must expose
        ``get(key, default)``.
        """
        self._backend = backend

    # ---- read paths -----------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-style access — the primary API Shelfmark's code uses."""
        if self._backend is not None:
            value = self._backend.get(key, _MISSING)
            if value is not _MISSING:
                return value
        env_key = f"GRABARR_SHELFMARK_{key}"
        if env_key in os.environ:
            return os.environ[env_key]
        if key in os.environ:
            return os.environ[key]
        if key in self._BUILTIN_DEFAULTS:
            return self._BUILTIN_DEFAULTS[key]
        return default

    def __getattr__(self, name: str) -> Any:
        """Attribute-style access — Shelfmark uses both styles."""
        if name.startswith("_"):
            raise AttributeError(name)
        value = self.get(name, _MISSING)
        if value is _MISSING:
            raise AttributeError(
                f"ShelfmarkConfigProxy has no value for {name!r}; "
                "seed a default in _BUILTIN_DEFAULTS or set the key in "
                "Grabarr's settings table."
            )
        return value

    # ---- write path -----------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        """Intentionally silent. Vendored code rarely writes; when it does
        we do NOT want those writes leaking into Grabarr's canonical
        settings table."""


class _Missing:
    """Sentinel for "lookup returned nothing"."""

    def __repr__(self) -> str:
        return "<MISSING>"


_MISSING = _Missing()


# -------- module-level singletons imported by vendored code --------------

#: The proxy object imported as ``config`` by vendored files whose original
#: import was ``from shelfmark.core.config import config``.
shelfmark_config_proxy: ShelfmarkConfigProxy = ShelfmarkConfigProxy()
