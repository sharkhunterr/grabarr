"""Transient dataclasses that flow between layers.

These are NOT SQLAlchemy ORM models — those live in each feature package's
``models.py`` (``grabarr/profiles/models.py``, etc.). The classes here are
the wire types adapters emit and the orchestrator / download manager
consume. They are frozen + slots-friendly and JSON-round-trippable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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

    ``download_url`` is the resolved HTTP URL to fetch. For the AA cascade
    this is populated only after Shelfmark's vendored cascade completes.
    ``extra_headers`` carries cookies / auth / UA overrides the adapter
    wants applied to the download request.
    """

    download_url: str
    size_bytes: int | None
    content_type: str | None
    filename_hint: str
    extra_headers: dict[str, str] = field(default_factory=dict)


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
