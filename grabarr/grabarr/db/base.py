"""SQLAlchemy declarative base + shared column types.

Every ORM module (``grabarr/profiles/models.py``,
``grabarr/downloads/models.py``, etc.) imports ``Base`` from here so
Alembic's autogenerate can see the full schema.

UUID primary keys use UUIDv7 (time-ordered, B-tree-friendly) generated
by the ``uuid_utils`` package; stored as TEXT in SQLite because SQLite
has no native UUID type.
"""

from __future__ import annotations

import datetime as dt
import uuid as stdlib_uuid
from typing import Annotated, Any

import uuid_utils
from sqlalchemy import CheckConstraint, DateTime, String, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, mapped_column

__all__ = [
    "Base",
    "uuidv7_pk",
    "UUIDColumn",
    "TIMESTAMPTZ",
    "JSON_TYPE",
    "check_length",
]


# ---- Base -----------------------------------------------------------------


class Base(DeclarativeBase):
    """Shared SQLAlchemy declarative base."""

    type_annotation_map = {
        dt.datetime: DateTime(timezone=True),
    }


# ---- UUID column ---------------------------------------------------------


class UUIDColumn(TypeDecorator[str]):
    """UUID stored as TEXT (SQLite-native)."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, stdlib_uuid.UUID):
            return str(value)
        if isinstance(value, uuid_utils.UUID):
            return str(value)
        return str(value)

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        return value


def _new_uuidv7() -> str:
    """Time-ordered UUID default. Importable from Alembic migrations."""
    return str(uuid_utils.uuid7())


uuidv7_pk = mapped_column(
    UUIDColumn,
    primary_key=True,
    default=_new_uuidv7,
)


# ---- Shared typing aliases ------------------------------------------------

TIMESTAMPTZ = Annotated[dt.datetime, mapped_column(DateTime(timezone=True))]
JSON_TYPE = Annotated[Any, mapped_column()]


# ---- CHECK constraint helper ---------------------------------------------


def check_length(column: str, min_len: int | None = None, max_len: int | None = None) -> CheckConstraint:
    """Produce a ``CheckConstraint`` enforcing length bounds on a column."""
    clauses = []
    if min_len is not None:
        clauses.append(f"length({column}) >= {min_len}")
    if max_len is not None:
        clauses.append(f"length({column}) <= {max_len}")
    return CheckConstraint(
        " AND ".join(clauses),
        name=f"{column}_length_check",
    )
