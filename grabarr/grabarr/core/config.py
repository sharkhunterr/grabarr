"""Pydantic-settings config loader.

Per research R-8, ``config.yaml`` and environment variables are the
**boot-time only** source of:

- credentials (AA member key, Z-Library cookies, master secret),
- server wiring (host, port, data_dir, downloads_dir),
- initial seed values for the UI-mutable ``settings`` table.

Once the database is initialized, every UI-mutable setting lives in the
``settings`` table and is edited through the admin UI. This file never
writes back to ``config.yaml``.

The vendored Shelfmark code reads its own config through
``grabarr.vendor.shelfmark._grabarr_adapter.shelfmark_config_proxy``; we
call :func:`install_shelfmark_bridge` at application startup to point that
proxy at our live settings backend.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---- Config sections ------------------------------------------------------


class LoggingConfig(BaseModel):
    """Logging section of config.yaml."""

    level: str = "INFO"
    format: str = "text"                   # "text" | "json"
    modules: dict[str, str] = Field(default_factory=dict)


class ServerConfig(BaseModel):
    """Server section — boot-time wiring that cannot change at runtime.

    Defaults point at paths relative to the process's CWD so local
    development works without root. Docker deployments override these
    via ``config.yaml`` or ``GRABARR_SERVER__DATA_DIR`` env var.
    """

    host: str = "0.0.0.0"
    port: int = 8080
    data_dir: Path = Path("data")
    downloads_dir: Path = Path("downloads")


class AnnaArchiveConfig(BaseModel):
    """Anna's Archive credentials."""

    member_key: str = ""


class ZLibraryConfig(BaseModel):
    """Z-Library cookie credentials."""

    remix_userid: str = ""
    remix_userkey: str = ""


class SourceCredentialsConfig(BaseModel):
    """All source-side credentials."""

    anna_archive: AnnaArchiveConfig = Field(default_factory=AnnaArchiveConfig)
    zlibrary: ZLibraryConfig = Field(default_factory=ZLibraryConfig)


# ---- Top-level Settings ---------------------------------------------------


class Settings(BaseSettings):
    """Grabarr's boot-time configuration.

    Precedence (pydantic-settings default): env var > init kwargs > config
    file. Env-var keys use ``GRABARR_`` prefix + double-underscore
    delimiter, e.g. ``GRABARR_SOURCES__ANNA_ARCHIVE__MEMBER_KEY``.
    """

    model_config = SettingsConfigDict(
        env_prefix="GRABARR_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    sources: SourceCredentialsConfig = Field(default_factory=SourceCredentialsConfig)
    master_secret: str = ""
    initial_settings: dict[str, Any] = Field(default_factory=dict)


# ---- Loader ---------------------------------------------------------------


_settings_singleton: Settings | None = None


def load_settings(config_path: Path | str | None = None) -> Settings:
    """Load and cache the boot-time settings.

    Search order for the config file:

    1. Explicit argument.
    2. ``GRABARR_CONFIG_PATH`` env var.
    3. ``./config.yaml`` in the current working dir.
    4. ``/config/grabarr.yaml`` (Docker convention).

    If no file is found, defaults apply.
    """
    global _settings_singleton

    import os

    if config_path is None:
        config_path = os.environ.get("GRABARR_CONFIG_PATH")
    if config_path is None:
        for candidate in (Path("config.yaml"), Path("/config/grabarr.yaml")):
            if candidate.exists():
                config_path = candidate
                break

    data: dict[str, Any] = {}
    if config_path and Path(config_path).exists():
        with Path(config_path).open() as fh:
            data = yaml.safe_load(fh) or {}

    _settings_singleton = Settings(**data)
    return _settings_singleton


def get_settings() -> Settings:
    """Return the cached :class:`Settings`, loading on first call."""
    if _settings_singleton is None:
        return load_settings()
    return _settings_singleton


# ---- Shelfmark bridge wiring ---------------------------------------------


class _SettingsBackendProtocol:
    """What :func:`install_shelfmark_bridge` expects as its backend.

    Concrete implementation is in ``grabarr/profiles/service.py`` wrapped
    around the ``settings`` DB table. We accept anything with a
    dict-compatible ``get(key, default)``.
    """

    def get(self, key: str, default: Any = None) -> Any:  # pragma: no cover
        raise NotImplementedError


def install_shelfmark_bridge(backend: _SettingsBackendProtocol) -> None:
    """Wire the live settings backend into the vendored Shelfmark proxy.

    Call this once during app startup, AFTER the database is initialized.
    Before this call, the proxy falls back to env vars + built-in
    defaults (which is enough to get migrations and seeding to run).
    """
    from grabarr.vendor.shelfmark._grabarr_adapter import shelfmark_config_proxy

    shelfmark_config_proxy._bind_backend(backend)
