"""ai plans, assets e colaboracao

Revision ID: 496f421dfe60
Revises: b8613a17ba2e
Create Date: 2026-11-10 15:40:44.387642
"""
import uuid
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "496f421dfe60"
down_revision: Union[str, None] = "b8613a17ba2e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PLANS = [
    ("free", "Free", "Para experimentar com um projeto por vez.", 200_000, 0, ["Projetos ilimitados", "1 membro"], 0),
    ("pro", "Pro", "Para squads que prototipam todos os dias.", 2_000_000, 9_900, ["Até 10 membros", "Share links com senha", "Histórico completo"], 1),
    ("enterprise", "Enterprise", "Para organizações com governança e SSO.", 20_000_000, 49_900, ["Membros ilimitados", "Auditoria de IA", "Suporte dedicado"], 2),
]


def upgrade() -> None:
    op.create_table(
        "ai_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("monthly_token_limit", sa.BigInteger(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_plans_slug"), "ai_plans", ["slug"], unique=True)

    plans_table = sa.table(
        "ai_plans",
        sa.column("id", sa.String),
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("monthly_token_limit", sa.BigInteger),
        sa.column("price_cents", sa.Integer),
        sa.column("features", postgresql.JSONB),
        sa.column("is_active", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        sa.column("created_at", sa.DateTime),
    )
    op.bulk_insert(
        plans_table,
        [
            {
                "id": str(uuid.uuid4()),
                "slug": slug,
                "name": name,
                "description": description,
                "monthly_token_limit": limit,
                "price_cents": price,
                "features": features,
                "is_active": True,
                "sort_order": order,
                "created_at": datetime.utcnow(),
            }
            for slug, name, description, limit, price, features, order in PLANS
        ],
    )

    op.create_table(
        "assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("uploaded_by", sa.String(length=36), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "filename", name="uq_asset_project_filename"),
    )
    op.create_index(op.f("ix_assets_project_id"), "assets", ["project_id"], unique=False)

    op.add_column("organizations", sa.Column("ai_plan_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_organizations_ai_plan_id",
        "organizations",
        "ai_plans",
        ["ai_plan_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_organizations_ai_plan_id", "organizations", type_="foreignkey")
    op.drop_column("organizations", "ai_plan_id")
    op.drop_index(op.f("ix_assets_project_id"), table_name="assets")
    op.drop_table("assets")
    op.drop_index(op.f("ix_ai_plans_slug"), table_name="ai_plans")
    op.drop_table("ai_plans")
