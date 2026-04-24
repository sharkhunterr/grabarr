"""add search_tokens + purge queued downloads

Revision ID: 0378792f14f7
Revises: 068f4d43aff0
Create Date: 2026-04-24 12:31:03.769460
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0378792f14f7'
down_revision: Union[str, None] = '068f4d43aff0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "search_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("profile_slug", sa.String(128), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(256), nullable=False),
        sa.Column("media_type", sa.String(32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_search_tokens_created_at", "search_tokens", ["created_at"])

    # Purge legacy queued rows — they're search artifacts, not real grabs.
    op.execute("DELETE FROM downloads WHERE status = 'queued'")


def downgrade() -> None:
    op.drop_index("ix_search_tokens_created_at", table_name="search_tokens")
    op.drop_table("search_tokens")
