"""add query column to search_tokens and downloads

Revision ID: ed92c7f86c84
Revises: 0378792f14f7
Create Date: 2026-04-25 10:35:14.545584
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ed92c7f86c84'
down_revision: Union[str, None] = '0378792f14f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Persist the user's torznab query so prepare_and_generate_torrent
    # can pass it as `query_hint` to adapter.get_download_info(). The IA
    # adapter uses this to filename-match inside multi-file ROM romsets
    # (e.g. nointro.snes contains 3000+ ZIPs; without the query the
    # ladder picks any one of them).
    op.add_column("search_tokens", sa.Column("query", sa.Text(), nullable=True))
    op.add_column("downloads", sa.Column("query", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("downloads") as batch:
        batch.drop_column("query")
    with op.batch_alter_table("search_tokens") as batch:
        batch.drop_column("query")
