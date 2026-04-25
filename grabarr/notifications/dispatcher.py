"""Notification dispatcher with flap suppression (spec FR-031, FR-031a)."""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select

from grabarr.core.enums import (
    NotificationDispatchStatus,
    NotificationEvent,
    NotificationSeverity,
)
from grabarr.core.logging import setup_logger
from grabarr.db.session import session_scope
from grabarr.notifications.encryption import decrypt
from grabarr.notifications.models import (
    AppriseUrl,
    NotificationLog,
    WebhookConfig,
)

_log = setup_logger(__name__)


@dataclass(frozen=True)
class NotificationPayload:
    event: NotificationEvent
    title: str
    body: str
    severity: NotificationSeverity = NotificationSeverity.INFO
    source_id: str | None = None
    metadata: dict[str, Any] | None = None


async def _should_suppress(
    event: NotificationEvent,
    source_id: str | None,
    cooldown_minutes: int,
) -> bool:
    """Return True if an identical event was already dispatched within the cooldown window.

    ``quota_exhausted`` uses an until-midnight-UTC window regardless of
    ``cooldown_minutes`` per spec FR-031a.
    """
    now = dt.datetime.now(dt.UTC)
    if event == NotificationEvent.QUOTA_EXHAUSTED:
        midnight = (now + dt.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        since = midnight - dt.timedelta(days=1)  # today-00:00 UTC
    else:
        since = now - dt.timedelta(minutes=cooldown_minutes)

    async with session_scope() as session:
        row = await session.execute(
            select(NotificationLog)
            .where(NotificationLog.event_type == event.value)
            .where(NotificationLog.source_id == source_id)
            .where(NotificationLog.dispatched_at >= since)
            .where(NotificationLog.dispatch_status == NotificationDispatchStatus.SENT.value)
            .order_by(desc(NotificationLog.dispatched_at))
            .limit(1)
        )
        return row.scalar_one_or_none() is not None


async def _deliver_apprise(payload: NotificationPayload) -> int:
    """Fan out to every Apprise URL subscribed to this event.

    Returns the number of URLs that received the event. Failures are
    logged but do NOT raise — Apprise is fire-and-forget.
    """
    try:
        import apprise
    except ImportError:
        _log.warning("apprise not installed; skipping dispatch")
        return 0

    async with session_scope() as session:
        rows = await session.execute(select(AppriseUrl).where(AppriseUrl.enabled.is_(True)))
        targets = list(rows.scalars().all())

    matching_urls: list[str] = []
    for target in targets:
        if payload.event.value not in (target.subscribed_events or []):
            continue
        try:
            matching_urls.append(decrypt(target.url_encrypted))
        except Exception as exc:  # noqa: BLE001
            _log.warning("failed to decrypt apprise url %s: %s", target.id, exc)

    if not matching_urls:
        return 0

    apobj = apprise.Apprise()
    for url in matching_urls:
        apobj.add(url)

    def _send() -> bool:
        return apobj.notify(
            title=payload.title,
            body=payload.body,
            notify_type={
                NotificationSeverity.INFO: apprise.NotifyType.INFO,
                NotificationSeverity.WARNING: apprise.NotifyType.WARNING,
                NotificationSeverity.ERROR: apprise.NotifyType.FAILURE,
            }[payload.severity],
        )

    for attempt in range(3):
        try:
            ok = await asyncio.to_thread(_send)
            if ok:
                return len(matching_urls)
        except Exception as exc:  # noqa: BLE001
            _log.warning("apprise attempt %d failed: %s", attempt + 1, exc)
        await asyncio.sleep(min(2 ** attempt, 5))
    return 0


async def _deliver_webhook(payload: NotificationPayload) -> bool:
    """Send to the generic webhook fallback if enabled + subscribed.

    Returns True if the webhook was invoked successfully.
    """
    async with session_scope() as session:
        row = await session.execute(select(WebhookConfig).where(WebhookConfig.id == 1))
        cfg = row.scalar_one_or_none()
    if cfg is None or not cfg.enabled or not cfg.url:
        return False
    if payload.event.value not in (cfg.subscribed_events or []):
        return False

    import httpx
    from jinja2 import Template

    try:
        tpl = Template(cfg.body_template or "{}")
        body = tpl.render(
            event=payload.event.value,
            title=payload.title,
            body=payload.body,
            severity=payload.severity.value,
            source_id=payload.source_id,
            metadata=payload.metadata or {},
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("webhook template render failed: %s", exc)
        return False

    headers = dict(cfg.headers or {})
    headers.setdefault("Content-Type", "application/json")

    async with httpx.AsyncClient(timeout=15.0) as client:
        for attempt in range(3):
            try:
                r = await client.post(cfg.url, content=body, headers=headers)
                if 200 <= r.status_code < 300:
                    return True
                _log.warning(
                    "webhook attempt %d returned %d", attempt + 1, r.status_code
                )
            except httpx.HTTPError as exc:
                _log.warning("webhook attempt %d failed: %s", attempt + 1, exc)
            await asyncio.sleep(min(2 ** attempt, 5))
    return False


async def dispatch(payload: NotificationPayload, cooldown_minutes: int = 10) -> None:
    """Dispatch a notification event, applying flap suppression.

    Records a NotificationLog row for every attempt (sent / failed /
    suppressed), which feeds the admin UI.
    """
    suppressed = await _should_suppress(payload.event, payload.source_id, cooldown_minutes)
    if suppressed:
        await _record_log(payload, NotificationDispatchStatus.SUPPRESSED)
        return

    apprise_count = await _deliver_apprise(payload)
    webhook_ok = await _deliver_webhook(payload)
    status = (
        NotificationDispatchStatus.SENT
        if (apprise_count > 0 or webhook_ok)
        else NotificationDispatchStatus.FAILED
    )
    await _record_log(payload, status)


async def _record_log(
    payload: NotificationPayload,
    status: NotificationDispatchStatus,
) -> None:
    async with session_scope() as session:
        session.add(
            NotificationLog(
                event_type=payload.event.value,
                source_id=payload.source_id,
                title=payload.title,
                body=payload.body,
                severity=payload.severity.value,
                metadata_json=payload.metadata or {},
                dispatched_at=dt.datetime.now(dt.UTC),
                coalesced=status == NotificationDispatchStatus.SUPPRESSED,
                dispatch_status=status.value,
            )
        )
