"""ORM model for the ``settings`` key-value table (research R-8)."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from grabarr.db.base import Base


class Setting(Base):
    """One row per UI-mutable setting key (allowlisted at service layer)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[object] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.UTC)
    )
