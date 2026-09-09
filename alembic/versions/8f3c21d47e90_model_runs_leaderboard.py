"""model_runs_leaderboard

Adds the columns that turn model_runs from a champion-only table into a
full leaderboard: which row won, whether a scoreless row failed or was
skipped, and why.

Revision ID: 8f3c21d47e90
Revises: 2b1be7fe2805
Create Date: 2026-09-09 10:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8f3c21d47e90'
down_revision: Union[str, Sequence[str], None] = '2b1be7fe2805'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'model_runs',
        sa.Column('is_champion', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'model_runs',
        sa.Column('status', sa.String(length=20), nullable=False, server_default='completed'),
    )
    op.add_column('model_runs', sa.Column('error_message', sa.Text(), nullable=True))

    # Every pre-existing row was written by the old _save_model_runs_sync,
    # which inserted one row per metric using best_model — so all of them
    # are champions by construction. Without this backfill they would all
    # default to false and vanish from the job-history metric summaries,
    # which filter on is_champion.
    op.execute("UPDATE model_runs SET is_champion = true")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('model_runs', 'error_message')
    op.drop_column('model_runs', 'status')
    op.drop_column('model_runs', 'is_champion')
