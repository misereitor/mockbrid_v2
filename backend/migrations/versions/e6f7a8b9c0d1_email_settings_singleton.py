"""Make email settings a singleton row."""

from typing import Sequence, Union

from alembic import op


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep the newest configuration, then give it the fixed primary key.
    op.execute(
        """
        WITH newest AS (
            SELECT id FROM email_settings
            ORDER BY updated_at DESC, id DESC LIMIT 1
        )
        DELETE FROM email_settings
        WHERE id <> COALESCE((SELECT id FROM newest), '')
        """
    )
    op.execute(
        """
        UPDATE email_settings
        SET id = 'singleton'
        WHERE id IN (SELECT id FROM email_settings LIMIT 1)
          AND id <> 'singleton'
        """
    )


def downgrade() -> None:
    pass
