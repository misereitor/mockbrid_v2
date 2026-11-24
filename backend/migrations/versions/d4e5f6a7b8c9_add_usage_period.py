"""Add monthly usage period markers."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c7e4b2a1f930"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("usage_period", sa.String(length=7), nullable=True))
    op.add_column("ai_providers", sa.Column("usage_period", sa.String(length=7), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_providers", "usage_period")
    op.drop_column("users", "usage_period")
