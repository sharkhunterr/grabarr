"""Adapter health monitor + circuit breaker (spec FR-036).

Periodic health probes run every 60 seconds. Each probe updates the
``adapter_health`` row. On 5 consecutive failures the adapter is
flipped to ``unhealthy`` and skipped by the orchestrator; a
``source_unhealthy`` notification fires (subject to flap suppression).
When a subsequent probe succeeds the adapter flips back to healthy and
a ``source_recovered`` event is dispatched.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import select

from grabarr.adapters.health_model import AdapterHealthRow
from grabarr.core.enums import (
    AdapterHealth,
    NotificationEvent,
    NotificationSeverity,
    UnhealthyReason,
)
from grabarr.core.logging import setup_logger
from grabarr.core.registry import get_registered_adapters
from grabarr.db.session import session_scope
from grabarr.notifications.dispatcher import NotificationPayload, dispatch

if TYPE_CHECKING:
    from grabarr.adapters.base import SourceAdapter  # noqa: F401


def _get_adapter_instance(adapter_id: str):
    from grabarr.profiles.service import get_adapter_instance

    return get_adapter_instance(adapter_id)

_log = setup_logger(__name__)

# Constitution + FR-036 constants.
_FAILURE_THRESHOLD = 5
_RECHECK_AFTER_SECONDS = 60


async def probe_once(adapter_id: str) -> None:
    """Probe ``adapter_id`` once and update its health row in place."""
    adapter = _get_adapter_instance(adapter_id)
    if adapter is None:
        return
    try:
        status = await adapter.health_check()
    except Exception as exc:  # noqa: BLE001
        status = type(
            "HS",
            (),
            {
                "status": AdapterHealth.UNHEALTHY,
                "reason": UnhealthyReason.CONNECTIVITY,
                "message": str(exc)[:200],
                "checked_at": dt.datetime.now(dt.UTC),
            },
        )()

    now = dt.datetime.now(dt.UTC)
    async with session_scope() as session:
        row_result = await session.execute(
            select(AdapterHealthRow).where(AdapterHealthRow.adapter_id == adapter_id)
        )
        row = row_result.scalar_one_or_none()
        previous_status: str | None = None
        previous_reason: str | None = None
        if row is None:
            row = AdapterHealthRow(
                adapter_id=adapter_id,
                status=status.status.value,
                reason=status.reason.value if status.reason else None,
                last_check_at=now,
                next_recheck_at=now + dt.timedelta(seconds=_RECHECK_AFTER_SECONDS),
                consecutive_failures=0
                if status.status == AdapterHealth.HEALTHY
                else 1,
                last_success_at=now if status.status == AdapterHealth.HEALTHY else None,
                last_error_message=status.message,
            )
            session.add(row)
        else:
            previous_status = row.status
            previous_reason = row.reason
            row.last_check_at = now
            row.next_recheck_at = now + dt.timedelta(seconds=_RECHECK_AFTER_SECONDS)
            row.last_error_message = status.message
            if status.status == AdapterHealth.HEALTHY:
                row.consecutive_failures = 0
                row.last_success_at = now
                row.status = AdapterHealth.HEALTHY.value
                row.reason = None
            else:
                row.consecutive_failures += 1
                if row.consecutive_failures >= _FAILURE_THRESHOLD:
                    row.status = AdapterHealth.UNHEALTHY.value
                    row.reason = status.reason.value if status.reason else None
                else:
                    row.status = AdapterHealth.DEGRADED.value
                    row.reason = status.reason.value if status.reason else None

        new_status = row.status
        new_reason = row.reason

    # Fire notifications on transition.
    if previous_status == AdapterHealth.UNHEALTHY.value and new_status == AdapterHealth.HEALTHY.value:
        await dispatch(
            NotificationPayload(
                event=NotificationEvent.SOURCE_RECOVERED,
                title=f"Source recovered: {adapter_id}",
                body=f"{adapter_id} is healthy again.",
                severity=NotificationSeverity.INFO,
                source_id=adapter_id,
            )
        )
    elif previous_status != AdapterHealth.UNHEALTHY.value and new_status == AdapterHealth.UNHEALTHY.value:
        event = NotificationEvent.SOURCE_UNHEALTHY
        if new_reason == UnhealthyReason.COOKIE_EXPIRED.value:
            event = NotificationEvent.COOKIE_EXPIRED
        elif new_reason == UnhealthyReason.QUOTA_EXHAUSTED.value:
            event = NotificationEvent.QUOTA_EXHAUSTED
        elif new_reason in (
            UnhealthyReason.BYPASS_FAILED.value,
            UnhealthyReason.FLARESOLVERR_DOWN.value,
        ):
            event = NotificationEvent.BYPASS_FAILED
        await dispatch(
            NotificationPayload(
                event=event,
                title=f"Source unhealthy: {adapter_id}",
                body=f"{adapter_id} is unhealthy (reason: {new_reason or 'unknown'}).",
                severity=NotificationSeverity.WARNING,
                source_id=adapter_id,
                metadata={"reason": new_reason},
            )
        )


async def probe_all() -> None:
    """Probe every registered adapter in parallel."""
    ids = list(get_registered_adapters().keys())
    await asyncio.gather(*(probe_once(aid) for aid in ids), return_exceptions=True)


async def is_adapter_healthy(adapter_id: str) -> bool:
    """Orchestrator-side check — returns False when the circuit is tripped."""
    async with session_scope() as session:
        row = await session.execute(
            select(AdapterHealthRow).where(AdapterHealthRow.adapter_id == adapter_id)
        )
        obj = row.scalar_one_or_none()
        if obj is None:
            return True  # never probed → optimistic
        return obj.status != AdapterHealth.UNHEALTHY.value


_monitor_task: asyncio.Task | None = None


async def start_monitor(period_seconds: int = 60) -> None:
    """Start the periodic probe loop as an asyncio background task."""
    global _monitor_task
    if _monitor_task is not None and not _monitor_task.done():
        return

    async def _loop() -> None:
        # Delay the first tick so startup doesn't stall on adapter probes.
        await asyncio.sleep(5)
        while True:
            try:
                await probe_all()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                _log.warning("health probe loop error: %s", exc)
            await asyncio.sleep(period_seconds)

    _monitor_task = asyncio.create_task(_loop(), name="grabarr-health-monitor")


async def stop_monitor() -> None:
    global _monitor_task
    if _monitor_task is None:
        return
    _monitor_task.cancel()
    try:
        await _monitor_task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    _monitor_task = None
