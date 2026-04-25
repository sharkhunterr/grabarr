"""drop unique on downloads info_hash

Revision ID: 068f4d43aff0
Revises: b8756945d4db
Create Date: 2026-04-24 10:15:03.109618
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '068f4d43aff0'
down_revision: Union[str, None] = 'b8756945d4db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # info_hash is unique-by-content, not unique-by-grab-request. The
    # same book grabbed twice (different tokens, different times) must
    # be allowed — otherwise the second grab crashes with
    # sqlite3.IntegrityError: UNIQUE constraint failed.
    # Replace the unique index with a plain lookup index. Raw SQL
    # because batch_alter_table's index manipulation is unreliable on
    # SQLite when the index already exists with a different unique flag.
    op.execute("DROP INDEX IF EXISTS ix_downloads_info_hash")
    op.execute("CREATE INDEX ix_downloads_info_hash ON downloads (info_hash)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_downloads_info_hash")
    op.execute("CREATE UNIQUE INDEX ix_downloads_info_hash ON downloads (info_hash)")
