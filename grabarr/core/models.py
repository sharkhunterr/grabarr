"""Transient dataclasses that flow between layers.

These are NOT SQLAlchemy ORM models — those live in each feature package's
``models.py`` (``grabarr/profiles/models.py``, etc.). The classes here are
the wire types adapters emit and the orchestrator / download manager
consume. They are frozen + slots-friendly and JSON-round-trippable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from grabarr.core.enums import AdapterHealth, MediaType, UnhealthyReason


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """User-supplied narrowing applied at search time.

    Mirrors the JSON shape persisted on ``profiles.filters``. An empty
    ``languages`` list means "any language"; an empty
    ``preferred_formats`` means "any format".
    """

    languages: list[str] = field(default_factory=list)
    preferred_formats: list[str] = field(default_factory=list)
    min_year: int | None = None
    max_year: int | None = None
    min_size_mb: float | None = None
    max_size_mb: float | None = None
    require_isbn: bool = False
    extra_query_terms: str = ""


@dataclass(frozen=True, slots=True)
class SourcePriorityEntry:
    """A single entry in ``profiles.sources``."""

    source_id: str
    weight: float = 1.0           # 0.1 ≤ weight ≤ 2.0 per spec invariants
    timeout_seconds: int = 60
    enabled: bool = True
    skip_if_member_required: bool = False
    # Per-source cap on how many items this adapter contributes to the
    # final result set. 0 means "no cap" — the profile-level `limit`
    # still applies after aggregation. 20 (default) is a sensible
    # upper bound so one source can't flood AA/LibGen/IA results.
    max_results: int = 20


@dataclass(frozen=True, slots=True)
class SearchResult:
    """What an adapter's ``search()`` returns.

    Ordering within a list of results is not significant here — the
    orchestrator sorts by (weight-adjusted) ``quality_score``.
    """

    external_id: str
    title: str
    author: str | None
    year: int | None
    format: str            # e.g. "epub", "mp3", "iso"
    language: str | None   # ISO 639-1 if known
    size_bytes: int | None
    quality_score: float   # 0–∞; see research §R-14
    source_id: str
    media_type: MediaType
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DownloadInfo:
    """What ``adapter.get_download_info()`` returns.

    Three mutually exclusive delivery modes:

    - **URL mode** (default): ``download_url`` is a plain HTTP(S) URL that
      Grabarr's ``sync_download`` / ``streaming_download`` will fetch with
      its own httpx client. ``extra_headers`` carries cookies / UA / auth
      the adapter wants applied to that fetch.
    - **Local-path mode**: ``local_path`` points at a file the adapter
      has already fully downloaded (e.g. via Shelfmark's vendored cascade,
      which handles CF bypass + mirror rotation + retries natively).
      When set, ``download_url`` should be a ``file://`` placeholder and
      ``sync_download`` copies the file instead of making an HTTP call.
    - **Magnet passthrough mode**: ``magnet_uri`` carries a complete
      ``magnet:?xt=urn:btih:…`` URI from a torrent-only source (e.g.
      AudioBookBay). The download manager skips HTTP fetch + .torrent
      generation entirely and the torznab download endpoint emits an
      HTTP 302 redirect to ``magnet_uri`` which Prowlarr / *arr / the
      torrent client follow natively. ``download_url`` is then ignored
      (callers may set it to the magnet for symmetry).
    """

    download_url: str
    size_bytes: int | None
    content_type: str | None
    filename_hint: str
    extra_headers: dict[str, str] = field(default_factory=dict)
    local_path: Path | None = None
    magnet_uri: str | None = None


@dataclass(frozen=True, slots=True)
class HealthStatus:
    """Return value of ``adapter.health_check()``."""

    status: AdapterHealth
    reason: UnhealthyReason | None
    message: str | None
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class QuotaStatus:
    """Return value of ``adapter.get_quota_status()`` for quota-bound
    sources. Adapters with no quota return ``None`` from that method.
    """

    used: int
    limit: int
    resets_at: datetime


# ---- Config schema rendered by the Sources UI -----------------------------

FieldType = Literal["text", "password", "int", "bool", "select"]


@dataclass(frozen=True, slots=True)
class ConfigField:
    """One input in an adapter's Settings pane."""

    key: str
    label: str
    field_type: FieldType
    options: list[str] | None = None
    secret: bool = False
    required: bool = False
    help_text: str | None = None
    default: Any = None


@dataclass(frozen=True, slots=True)
class ConfigSchema:
    """Describes an adapter's config to the UI."""

    fields: list[ConfigField] = field(default_factory=list)
