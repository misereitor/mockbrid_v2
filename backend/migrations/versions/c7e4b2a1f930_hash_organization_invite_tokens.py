"""Hash organization invite tokens and normalize invite roles.

Downgrade cannot restore plaintext tokens; it generates new random token values,
so existing invite links are intentionally invalidated on downgrade.
"""
import hashlib
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c7e4b2a1f930"
down_revision: Union[str, None] = "a1c9f2d7e4b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, token FROM organization_invites")).fetchall()
    for row in rows:
        conn.execute(
            sa.text("UPDATE organization_invites SET token = :token, role = CASE WHEN role = 'owner' THEN 'admin' ELSE role END WHERE id = :id"),
            {"id": row.id, "token": hashlib.sha256(row.token.encode("utf-8")).hexdigest()},
        )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM organization_invites")).fetchall()
    for row in rows:
        conn.execute(
            sa.text("UPDATE organization_invites SET token = :token WHERE id = :id"),
            {"id": row.id, "token": secrets.token_urlsafe(32)},
        )
