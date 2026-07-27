"""add_forecast_job_name

Revision ID: 229f48553646
Revises: c77f55b15f7a
Create Date: 2026-07-27 12:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '229f48553646'
down_revision: Union[str, Sequence[str], None] = 'c77f55b15f7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('forecast_jobs', sa.Column('name', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('forecast_jobs', 'name')
