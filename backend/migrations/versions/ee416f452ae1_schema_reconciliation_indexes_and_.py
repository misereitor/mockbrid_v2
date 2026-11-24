"""schema_reconciliation_indexes_and_nullables

Revision ID: ee416f452ae1
Revises: e6f7a8b9c0d1
Create Date: 2026-11-24 18:58:55.191144
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'ee416f452ae1'
down_revision: Union[str, None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Reconciliação idempotente entre bancos legados (homologação inicial) e
    # bancos limpos criados a partir da migration inicial b8613a17ba2e.
    legacy_indexes = [
        "ix_ai_conv_org",
        "ix_ai_conv_proj",
        "ix_ai_conv_user",
        "ix_ai_messages_conv",
        "ix_mcp_keys_hash",
        "ix_mcp_keys_org",
        "ix_mcp_keys_proj",
        "ix_mcp_keys_user",
        "ix_org_invites_email",
        "ix_org_invites_org",
        "ix_org_invites_token",
        "ix_project_members_project",
        "ix_project_members_user",
        "ix_share_links_project",
    ]
    for idx in legacy_indexes:
        op.execute(f'DROP INDEX IF EXISTS "{idx}"')

    legacy_constraints = [
        ("auth_tokens", "auth_tokens_token_hash_key"),
        ("mcp_api_keys", "mcp_api_keys_key_hash_key"),
        ("organization_invites", "organization_invites_token_key"),
        ("share_links", "share_links_slug_key"),
    ]
    for table, constraint in legacy_constraints:
        op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{constraint}"')

    # Garante que ix_share_links_slug seja UNIQUE (caso tenha sido criado não-único em banco legado)
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_index i
                JOIN pg_class c ON c.oid = i.indexrelid
                WHERE c.relname = 'ix_share_links_slug' AND NOT i.indisunique
            ) THEN
                DROP INDEX "ix_share_links_slug";
            END IF;
        END $$;
        """
    )

    canonical_indexes = [
        ('ix_ai_conversations_organization_id', 'ai_conversations', 'organization_id', False),
        ('ix_ai_conversations_project_id', 'ai_conversations', 'project_id', False),
        ('ix_ai_conversations_screen_id', 'ai_conversations', 'screen_id', False),
        ('ix_ai_conversations_user_id', 'ai_conversations', 'user_id', False),
        ('ix_ai_messages_conversation_id', 'ai_messages', 'conversation_id', False),
        ('ix_mcp_api_keys_key_hash', 'mcp_api_keys', 'key_hash', True),
        ('ix_mcp_api_keys_organization_id', 'mcp_api_keys', 'organization_id', False),
        ('ix_mcp_api_keys_project_id', 'mcp_api_keys', 'project_id', False),
        ('ix_mcp_api_keys_user_id', 'mcp_api_keys', 'user_id', False),
        ('ix_organization_invites_email', 'organization_invites', 'email', False),
        ('ix_organization_invites_organization_id', 'organization_invites', 'organization_id', False),
        ('ix_organization_invites_token', 'organization_invites', 'token', True),
        ('ix_project_members_project_id', 'project_members', 'project_id', False),
        ('ix_project_members_user_id', 'project_members', 'user_id', False),
        ('ix_share_links_slug', 'share_links', 'slug', True),
        ('ix_share_links_project_id', 'share_links', 'project_id', False),
    ]
    for idx_name, table, col, is_unique in canonical_indexes:
        unique_sql = "UNIQUE " if is_unique else ""
        op.execute(f'CREATE {unique_sql}INDEX IF NOT EXISTS "{idx_name}" ON "{table}" ("{col}")')

    op.execute("UPDATE ai_providers SET base_url = '' WHERE base_url IS NULL")
    op.execute("UPDATE ai_providers SET custom_models = '[]'::jsonb WHERE custom_models IS NULL")
    op.alter_column(
        'ai_providers',
        'base_url',
        existing_type=sa.TEXT(),
        nullable=False,
        existing_server_default=sa.text("''::text"),
    )
    op.alter_column(
        'ai_providers',
        'custom_models',
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        existing_server_default=sa.text("'[]'::jsonb"),
    )


def downgrade() -> None:
    pass
