"""forecast_evaluations

F17: realized-accuracy checks of a forecast against later actuals. A new
table, so nothing to backfill; model_runs (backtest) is untouched.

Revision ID: e7b3c9d15a42
Revises: d4e1a7c9b203
Create Date: 2026-10-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e7b3c9d15a42'
down_revision: Union[str, Sequence[str], None] = 'd4e1a7c9b203'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'forecast_evaluations',
        sa.Column('id', postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column('job_id', postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column('upload_id', postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column('upload_file_name', sa.String(length=500), nullable=False),
        sa.Column('sheet_name', sa.String(length=255), nullable=False),
        sa.Column('metric_name', sa.String(length=255), nullable=False),
        sa.Column('forecast_points', sa.Integer(), nullable=False),
        sa.Column('matched_points', sa.Integer(), nullable=False),
        sa.Column('wmape', sa.Float(), nullable=True),
        sa.Column('mae', sa.Float(), nullable=True),
        sa.Column('bias', sa.Float(), nullable=True),
        sa.Column('actual_total', sa.Float(), nullable=False),
        sa.Column('forecast_total', sa.Float(), nullable=False),
        sa.Column('actuals_last_date', sa.Date(), nullable=True),
        sa.Column('points', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['forecast_jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['upload_id'], ['uploads.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'job_id', 'upload_id', 'sheet_name', 'metric_name',
            name='uq_forecast_evaluations_job_upload_sheet_metric',
        ),
    )
    op.create_index('ix_forecast_evaluations_job_id', 'forecast_evaluations', ['job_id'])
    op.create_index(
        'ix_forecast_evaluations_user_created', 'forecast_evaluations', ['user_id', 'created_at']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_forecast_evaluations_user_created', table_name='forecast_evaluations')
    op.drop_index('ix_forecast_evaluations_job_id', table_name='forecast_evaluations')
    op.drop_table('forecast_evaluations')
