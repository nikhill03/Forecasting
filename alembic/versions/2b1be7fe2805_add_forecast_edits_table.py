"""add_forecast_edits_table

Revision ID: 2b1be7fe2805
Revises: 229f48553646
Create Date: 2026-07-27 12:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2b1be7fe2805'
down_revision: Union[str, Sequence[str], None] = '229f48553646'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('forecast_edits',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('job_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.UUID(as_uuid=False), nullable=True),
    sa.Column('sheet_name', sa.String(length=255), nullable=False),
    sa.Column('metric_name', sa.String(length=255), nullable=False),
    sa.Column('sequence_no', sa.Integer(), nullable=False),
    sa.Column('instruction_text', sa.Text(), nullable=False),
    sa.Column('operation_type', sa.String(length=50), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('affected_points_before', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['forecast_jobs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_forecast_edits_job_id'), 'forecast_edits', ['job_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_forecast_edits_job_id'), table_name='forecast_edits')
    op.drop_table('forecast_edits')
