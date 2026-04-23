"""ORM models for the Apprise URLs, webhook config, and notifications log."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from grabarr.db.base import Base, UUIDColumn, _new_uuidv7


class AppriseUrl(Base):
    """Operator-managed Apprise target (URL stored encrypted at rest)."""

    __tablename__ = "apprise_urls"

    id: Mapped[str] = mapped_column(UUIDColumn, primary_key=True, default=_new_uuidv7)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    url_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    subscribed_events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.UTC)
    )


class WebhookConfig(Base):
    """Singleton generic-webhook fallback (``id = 1`` enforced)."""

    __tablename__ = "webhook_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    headers: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    body_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    subscribed_events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (CheckConstraint("id = 1", name="webhook_config_singleton"),)


class NotificationLog(Base):
    """Per-dispatch record feeding the admin UI + flap-suppression checks."""

    __tablename__ = "notifications_log"

    id: Mapped[str] = mapped_column(UUIDColumn, primary_key=True, default=_new_uuidv7)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    dispatched_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.UTC)
    )
    coalesced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dispatch_status: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'warning', 'error')",
            name="notifications_log_severity_valid",
        ),
        CheckConstraint(
            "dispatch_status IN ('sent', 'failed', 'suppressed')",
            name="notifications_log_dispatch_status_valid",
        ),
        Index("ix_notifications_log_dispatched_at", "dispatched_at"),
        Index(
            "ix_notifications_log_event_source_ts",
            "event_type",
            "source_id",
            "dispatched_at",
        ),
    )
