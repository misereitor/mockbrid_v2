"""add_project_ids_to_mcp_api_keys

Revision ID: f1a2b3c4d5e6
Revises: ee416f452ae1
Create Date: 2026-11-24 20:15:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'ee416f452ae1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE "mcp_api_keys" ADD COLUMN IF NOT EXISTS "project_ids" JSONB DEFAULT \'[]\'::jsonb')
    # Se houver registros legados com project_id preenchido, migra para project_ids
    op.execute('''
        UPDATE "mcp_api_keys" 
        SET "project_ids" = jsonb_build_array("project_id") 
        WHERE "project_id" IS NOT NULL AND ("project_ids" IS NULL OR "project_ids" = '[]'::jsonb)
    ''')


def downgrade() -> None:
    op.execute('ALTER TABLE "mcp_api_keys" DROP COLUMN IF EXISTS "project_ids"')
