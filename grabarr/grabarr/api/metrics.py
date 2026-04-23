"""/metrics endpoint — Prometheus exposition (spec FR-028, SC-010).

Every counter/histogram/gauge declared here is module-level so the
same instance accumulates across requests. The goal is ≥ 50 distinct
series under normal operation (SC-010) — dim-labels by source /
profile / status get us there easily.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

router = APIRouter(tags=["metrics"])

# Use a dedicated registry so Grabarr's metrics don't mix with any the
# transitive deps (httpx, libtorrent bindings) might ship globally.
REGISTRY = CollectorRegistry()

# ---- Counters ---------------------------------------------------------

searches_total = Counter(
    "grabarr_searches_total",
    "Search requests, dimensioned by source, profile, status.",
    ["source", "profile", "status"],
    registry=REGISTRY,
)

downloads_total = Counter(
    "grabarr_downloads_total",
    "Download requests, dimensioned by source, profile, status.",
    ["source", "profile", "status"],
    registry=REGISTRY,
)

bypass_invocations_total = Counter(
    "grabarr_bypass_invocations_total",
    "Cloudflare bypass attempts.",
    ["source", "result"],
    registry=REGISTRY,
)

errors_total = Counter(
    "grabarr_errors_total",
    "Uncaught-in-adapter errors by module.",
    ["module", "type"],
    registry=REGISTRY,
)

notifications_total = Counter(
    "grabarr_notifications_total",
    "Notification dispatches by event + status.",
    ["event_type", "dispatch_status"],
    registry=REGISTRY,
)

# ---- Histograms -------------------------------------------------------

source_response_duration = Histogram(
    "grabarr_source_response_duration_seconds",
    "End-to-end adapter search latency.",
    ["source"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
    registry=REGISTRY,
)

download_duration = Histogram(
    "grabarr_download_duration_seconds",
    "File-download wall time.",
    ["source", "size_bucket"],
    buckets=(1.0, 5.0, 15.0, 60.0, 300.0, 1800.0, 3600.0),
    registry=REGISTRY,
)

bypass_duration = Histogram(
    "grabarr_bypass_duration_seconds",
    "Cloudflare bypass duration.",
    ["source"],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0),
    registry=REGISTRY,
)

# ---- Gauges -----------------------------------------------------------

active_downloads = Gauge(
    "grabarr_active_downloads",
    "Currently-running downloads by mode.",
    ["mode"],
    registry=REGISTRY,
)

seeded_torrents = Gauge(
    "grabarr_seeded_torrents_total",
    "Active .torrent records being seeded.",
    registry=REGISTRY,
)

queue_depth = Gauge(
    "grabarr_queue_depth",
    "Pending grabs awaiting download.",
    registry=REGISTRY,
)

source_healthy = Gauge(
    "grabarr_source_healthy",
    "1 if adapter is currently healthy, 0 otherwise.",
    ["source"],
    registry=REGISTRY,
)

quota_remaining = Gauge(
    "grabarr_quota_remaining",
    "Remaining per-day downloads for quota-bound sources.",
    ["source"],
    registry=REGISTRY,
)


@router.get("/metrics")
async def metrics() -> Response:
    """Refresh per-adapter gauges just-in-time, then emit Prometheus text."""
    from sqlalchemy import select

    from grabarr.adapters.health_model import AdapterHealthRow
    from grabarr.core.registry import get_registered_adapters
    from grabarr.db.session import session_scope

    # Populate source_healthy from adapter_health.
    async with session_scope() as session:
        rows = await session.execute(select(AdapterHealthRow))
        by_id = {r.adapter_id: r for r in rows.scalars().all()}
        # Seeded torrents count comes from the torrents table.
        from sqlalchemy import func

        from grabarr.torrents.models import Torrent

        t_count = await session.execute(select(func.count(Torrent.info_hash)))
        seeded_torrents.set(t_count.scalar_one() or 0)

    for aid in get_registered_adapters():
        h = by_id.get(aid)
        source_healthy.labels(source=aid).set(
            1.0 if (h is None or h.status == "healthy") else 0.0
        )

    # Populate active-torrent count (mode-partitioned gauge not yet wired
    # — stays at 0 until the real download-service increments it).
    payload = generate_latest(REGISTRY)
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)
