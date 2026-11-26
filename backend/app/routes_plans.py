"""Planos de IA da organização: catálogo, assinatura e uso consolidado."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.database import get_db
from app.models import AIPlan, AIProvider, Organization, User
from app.quotas import get_org_plan, user_token_limit
from app.routes_auth import get_current_user, require_admin

router = APIRouter(tags=["ai-plans"])


class AIPlanOut(BaseModel):
    id: str
    slug: str
    name: str
    description: str
    monthly_token_limit: int
    price_cents: int
    features: list
    sort_order: int

    class Config:
        from_attributes = True


class PlanAssign(BaseModel):
    plan_slug: str


class ProviderUsageOut(BaseModel):
    provider_type: str
    tokens_used_month: int
    monthly_token_limit: int


class AIUsageOut(BaseModel):
    organization_id: str
    # Ambiente de execução (exibido em Configurações). Fica aqui, atrás de
    # autenticação, e não em /api/health, que é anônimo.
    environment: str
    plan: Optional[AIPlanOut]
    tokens_used_month: int
    monthly_token_limit: int
    providers: List[ProviderUsageOut]


@router.get("/api/ai/plans", response_model=List[AIPlanOut])
async def list_plans(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(AIPlan)
        .where(AIPlan.is_active == True)  # noqa: E712
        .order_by(AIPlan.sort_order.asc(), AIPlan.monthly_token_limit.asc())
    )
    return res.scalars().all()


@router.get("/api/org/ai-usage", response_model=AIUsageOut)
async def get_ai_usage(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan = await get_org_plan(db, current_user.organization_id)
    used_res = await db.execute(
        select(func.coalesce(func.sum(User.tokens_used_month), 0)).where(
            User.organization_id == current_user.organization_id
        )
    )
    used = int(used_res.scalar() or 0)

    providers_res = await db.execute(
        select(AIProvider).where(AIProvider.organization_id == current_user.organization_id)
    )
    providers = [
        ProviderUsageOut(
            provider_type=p.provider_type,
            tokens_used_month=int(p.tokens_used_month or 0),
            monthly_token_limit=int(p.monthly_token_limit or 0),
        )
        for p in providers_res.scalars().all()
    ]

    return AIUsageOut(
        organization_id=current_user.organization_id,
        environment=settings.ENVIRONMENT,
        plan=AIPlanOut.model_validate(plan) if plan else None,
        tokens_used_month=used,
        monthly_token_limit=user_token_limit(current_user, plan),
        providers=providers,
    )


@router.put("/api/org/plan", response_model=AIUsageOut)
async def assign_plan(
    payload: PlanAssign,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Troca o plano da organização. Apenas o owner pode mexer em cobrança."""
    if current_user.role != "owner":
        raise HTTPException(status_code=403, detail="Apenas o owner da organização pode alterar o plano")

    plan_res = await db.execute(
        select(AIPlan).where(AIPlan.slug == payload.plan_slug, AIPlan.is_active == True)  # noqa: E712
    )
    plan = plan_res.scalars().first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plano não encontrado")

    org_res = await db.execute(select(Organization).where(Organization.id == current_user.organization_id))
    org = org_res.scalars().first()
    if not org:
        raise HTTPException(status_code=404, detail="Organização não encontrada")
    org.ai_plan_id = plan.id
    await db.commit()

    return await get_ai_usage(current_user=current_user, db=db)
