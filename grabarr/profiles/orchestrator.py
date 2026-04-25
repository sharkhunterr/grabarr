"""Search Orchestrator (spec FR-013).

Iterates ``profile.sources`` in order, applies filters + weight
multiplier, and merges according to the profile's ``mode``
(``first_match`` vs ``aggregate_all``). This first-pass
implementation ships ``first_match``; ``aggregate_all`` lands in the
US3 phase.
"""

from __future__ import annotations

import asyncio
import datetime as dt

from grabarr.adapters.base import AdapterError
from grabarr.core.enums import MediaType, ProfileMode
from grabarr.core.logging import setup_logger
from grabarr.core.models import SearchFilters, SearchResult, SourcePriorityEntry
from grabarr.profiles.models import Profile
from grabarr.profiles.service import get_adapter_instance

_log = setup_logger(__name__)


def _filters_from_profile(profile: Profile) -> SearchFilters:
    data = profile.filters or {}
    return SearchFilters(
        languages=list(data.get("languages") or []),
        preferred_formats=list(data.get("preferred_formats") or []),
        min_year=data.get("min_year"),
        max_year=data.get("max_year"),
        min_size_mb=data.get("min_size_mb"),
        max_size_mb=data.get("max_size_mb"),
        require_isbn=bool(data.get("require_isbn", False)),
        extra_query_terms=str(data.get("extra_query_terms") or ""),
    )


def _sources_from_profile(profile: Profile) -> list[SourcePriorityEntry]:
    entries: list[SourcePriorityEntry] = []
    for raw in profile.sources or []:
        entries.append(
            SourcePriorityEntry(
                source_id=raw["source_id"],
                weight=float(raw.get("weight", 1.0)),
                timeout_seconds=int(raw.get("timeout_seconds", 60)),
                enabled=bool(raw.get("enabled", True)),
                skip_if_member_required=bool(raw.get("skip_if_member_required", False)),
                max_results=int(raw.get("max_results", 20)),
            )
        )
    return entries


def _dedup(results: list[SearchResult]) -> list[SearchResult]:
    """De-duplicate by (source_id, normalized_title, author, year, format).

    Including source_id means the same md5 surfaced by two adapters
    shows up as TWO rows — one per source, with its own [SOURCE] tag
    visible to Prowlarr / Bookshelf. The operator picks the one they
    trust (LibGen first for speed, AA as fallback, etc.). First
    occurrence within a source wins.
    """
    seen: set[tuple[str, str, str | None, int | None, str]] = set()
    out: list[SearchResult] = []
    for r in results:
        key = (
            r.source_id,
            r.title.strip().lower(),
            (r.author or "").strip().lower() or None,
            r.year,
            r.format.lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


async def _search_one(
    adapter,
    entry: SourcePriorityEntry,
    query: str,
    media_type: MediaType,
    filters: SearchFilters,
    limit: int,
) -> list[SearchResult]:
    """Call a single adapter with timeout + graceful failure.

    Returns an empty list on any adapter-side error; the orchestrator
    treats an empty list as "skip this source" and moves on.
    """
    # Per-source cap: ask the adapter for at most `max_results` items
    # (0 = no cap, fall back to the profile limit).
    per_source_limit = entry.max_results if entry.max_results > 0 else limit
    adapter_limit = min(limit, per_source_limit)
    try:
        results = await asyncio.wait_for(
            adapter.search(query, media_type, filters, adapter_limit),
            timeout=entry.timeout_seconds,
        )
    except TimeoutError:
        _log.info(
            "orchestrator: %s timed out after %ds",
            entry.source_id,
            entry.timeout_seconds,
        )
        return []
    except AdapterError as exc:
        _log.info(
            "orchestrator: %s raised %s: %s",
            entry.source_id,
            type(exc).__name__,
            exc,
        )
        return []
    except Exception as exc:  # noqa: BLE001
        _log.warning("orchestrator: %s crashed: %s", entry.source_id, exc)
        return []

    return [
        SearchResult(
            external_id=r.external_id,
            title=r.title,
            author=r.author,
            year=r.year,
            format=r.format,
            language=r.language,
            size_bytes=r.size_bytes,
            quality_score=r.quality_score * entry.weight,
            source_id=r.source_id,
            media_type=r.media_type,
            metadata=r.metadata,
        )
        for r in results
    ]


async def orchestrate_search(
    profile: Profile,
    query: str,
    limit: int = 50,
) -> list[SearchResult]:
    """Run a search across ``profile.sources`` respecting its mode.

    ``first_match``: iterate sources in order, stop on the first source
    that returns any results (the fast path for "just give me something").

    ``aggregate_all``: run every enabled source in parallel (bounded by
    the per-adapter rate-limit buckets), concatenate, dedupe, sort.
    """
    if not profile.enabled:
        return []

    media_type = MediaType(profile.media_type)
    filters = _filters_from_profile(profile)
    sources = _sources_from_profile(profile)
    mode = profile.mode

    from grabarr.adapters.health import is_adapter_healthy

    # Filter to adapters that are registered + compatible + authorised + healthy.
    eligible: list[tuple[object, SourcePriorityEntry]] = []
    for entry in sources:
        if not entry.enabled:
            continue
        adapter = get_adapter_instance(entry.source_id)
        if adapter is None:
            _log.debug(
                "orchestrator: adapter %s not registered — skipping",
                entry.source_id,
            )
            continue
        if media_type not in adapter.supported_media_types:
            continue
        if (
            entry.skip_if_member_required
            and getattr(adapter, "supports_member_key", False)
            and not getattr(adapter, "_member_key", None)
        ):
            continue
        if not await is_adapter_healthy(entry.source_id):
            _log.info("orchestrator: %s circuit-broken — skipping", entry.source_id)
            continue
        eligible.append((adapter, entry))

    all_results: list[SearchResult] = []

    if mode == ProfileMode.AGGREGATE_ALL.value:
        # Run every eligible source in parallel.
        tasks = [
            asyncio.create_task(
                _search_one(adapter, entry, query, media_type, filters, limit)
            )
            for adapter, entry in eligible
        ]
        for coro in asyncio.as_completed(tasks):
            all_results.extend(await coro)
    else:
        # first_match: sequential, stop on first non-empty.
        for adapter, entry in eligible:
            weighted = await _search_one(
                adapter, entry, query, media_type, filters, limit
            )
            all_results.extend(weighted)
            if weighted:
                break

    all_results = _dedup(all_results)
    all_results.sort(key=lambda r: r.quality_score, reverse=True)
    # Round-robin by source_id so no single source (e.g. AA with its
    # weight=1.2 advantage) crowds the others out of the [:limit] slice.
    # Each pass picks the highest-quality remaining item per source,
    # cycling until `limit` is reached.
    by_source: dict[str, list[SearchResult]] = {}
    for r in all_results:
        by_source.setdefault(r.source_id, []).append(r)
    interleaved: list[SearchResult] = []
    while len(interleaved) < limit:
        progress = False
        for sid in list(by_source):
            if not by_source[sid]:
                continue
            interleaved.append(by_source[sid].pop(0))
            progress = True
            if len(interleaved) >= limit:
                break
        if not progress:
            break
    return interleaved


async def test_profile(profile: Profile, query: str, limit: int = 10) -> dict:
    """Exercise the orchestrator for the UI's Test Profile action (FR-4.3)."""
    start = dt.datetime.now(dt.UTC)
    results = await orchestrate_search(profile, query, limit=limit)
    elapsed_ms = int((dt.datetime.now(dt.UTC) - start).total_seconds() * 1000)
    return {
        "took_ms": elapsed_ms,
        "results": [
            {
                "title": r.title,
                "author": r.author,
                "year": r.year,
                "format": r.format,
                "size_bytes": r.size_bytes,
                "quality_score": round(r.quality_score, 2),
                "source_id": r.source_id,
            }
            for r in results
        ],
    }
