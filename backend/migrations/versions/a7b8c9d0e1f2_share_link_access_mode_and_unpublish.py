"""share_link_access_mode_and_unpublish

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-11-25 18:00:00.000000

Fecha a exposição do link de apresentação:
- despublica todos os projetos (o slug do projeto era curto e adivinhável);
- share links ganham `access_mode` ('anyone' | 'org') e um rótulo opcional.

A coluna `projects.is_published` continua existindo por enquanto (nada mais a lê);
ela será removida em uma migração posterior, depois de um ciclo de deploy.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        'ALTER TABLE "share_links" '
        "ADD COLUMN IF NOT EXISTS \"access_mode\" VARCHAR(20) NOT NULL DEFAULT 'anyone'"
    )
    op.execute(
        'ALTER TABLE "share_links" ADD COLUMN IF NOT EXISTS "label" VARCHAR(120)'
    )
    # Despublica tudo: os links antigos (slug do projeto) deixam de funcionar e o
    # dono recria o que quiser pelo painel Compartilhar.
    op.execute('UPDATE "projects" SET "is_published" = false WHERE "is_published" = true')


def downgrade() -> None:
    # Não republica projetos: reabrir links públicos automaticamente seria inseguro.
    op.execute('ALTER TABLE "share_links" DROP COLUMN IF EXISTS "label"')
    op.execute('ALTER TABLE "share_links" DROP COLUMN IF EXISTS "access_mode"')
