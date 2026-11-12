"""email settings, verificacao de email e admin do sistema

Revision ID: a1c9f2d7e4b3
Revises: 496f421dfe60
Create Date: 2026-11-10 19:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1c9f2d7e4b3"
down_revision: Union[str, None] = "496f421dfe60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_system_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))

    op.create_table(
        "email_settings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False, server_default="disabled"),
        sa.Column("from_email", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("from_name", sa.String(length=120), nullable=False, server_default="Mockbird"),
        sa.Column("reply_to", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("app_base_url", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("require_verification", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("smtp_host", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("smtp_username", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("encrypted_smtp_password", sa.Text(), nullable=False, server_default=""),
        sa.Column("smtp_security", sa.String(length=20), nullable=False, server_default="starttls"),
        sa.Column("encrypted_resend_api_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])
    op.create_index("ix_auth_tokens_kind", "auth_tokens", ["kind"])
    op.create_index("ix_auth_tokens_token_hash", "auth_tokens", ["token_hash"], unique=True)

    # Garante que a instância já existente tenha um administrador do sistema:
    # o usuário mais antigo assume a configuração de e-mail.
    op.execute(
        """
        UPDATE users SET is_system_admin = true
        WHERE id = (SELECT id FROM users ORDER BY created_at ASC LIMIT 1)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_auth_tokens_token_hash", table_name="auth_tokens")
    op.drop_index("ix_auth_tokens_kind", table_name="auth_tokens")
    op.drop_index("ix_auth_tokens_user_id", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_table("email_settings")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "is_system_admin")
