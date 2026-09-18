"""forecast_job_quality_report

F16: persist the data-quality report a run was submitted with. Nullable with
no backfill — NULL means the job predates the report.

Revision ID: d4e1a7c9b203
Revises: 8f3c21d47e90
Create Date: 2026-09-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4e1a7c9b203'
down_revision: Union[str, Sequence[str], None] = '8f3c21d47e90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'forecast_jobs',
        sa.Column('quality_report', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('forecast_jobs', 'quality_report')
