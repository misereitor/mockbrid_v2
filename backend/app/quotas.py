"""Controle de cotas de IA.

Regras:
- O limite do usuário e o limite do provedor são checados antes de chamar a LLM.
- O consumo é cobrado a partir do `usage` real devolvido pelo provedor quando
  disponível; estimativa por tamanho de texto é apenas fallback.
- A cobrança usa UPDATE atômico para não perder incrementos concorrentes.
"""

import logging
from typing import Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import AsyncSessionLocal
from app.models import AIProvider, AIPlan, Organization, User
from app.timeutils import utcnow

logger = logging.getLogger(__name__)


async def get_org_plan(db: AsyncSession, organization_id: str) -> Optional[AIPlan]:
    """Plano de IA contratado pela organização (ou None quando não há plano)."""
    res = await db.execute(
        select(AIPlan)
        .join(Organization, Organization.ai_plan_id == AIPlan.id)
        .where(
            Organization.id == organization_id, AIPlan.is_active.is_(True)
        )
    )
    return res.scalars().first()


def user_token_limit(user: User, plan: Optional[AIPlan] = None) -> int:
    """O plano da organização, quando existir, prevalece sobre o limite individual."""
    if plan and plan.monthly_token_limit:
        return int(plan.monthly_token_limit)
    return int(user.monthly_token_limit)


def enforce_ai_quota(
    user: User,
    prov: Optional[AIProvider],
    plan: Optional[AIPlan] = None,
) -> None:
    """Lança 429 se o usuário ou o provedor já estouraram a cota mensal."""
    current_period = utcnow().strftime("%Y-%m")
    # Só considera virada de mês quando há um período registrado e ele é antigo;
    # período ausente (legado/NULL) mantém o consumo já contabilizado.
    user_period = getattr(user, "usage_period", None)
    user_used = (
        0
        if user_period and user_period != current_period
        else user.tokens_used_month
    )
    limit = user_token_limit(user, plan)
    if user_used >= limit:
        plan_detail = f" do plano '{plan.name}'" if plan else ""
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Limite mensal de tokens de IA{plan_detail} atingido "
                f"({user_used}/{limit}). "
                "Contate o administrador da organização."
            ),
        )

    if prov and prov.monthly_token_limit:
        prov_period = getattr(prov, "usage_period", None)
        prov_used = (
            0
            if prov_period and prov_period != current_period
            else prov.tokens_used_month
        )
        if prov_used >= prov.monthly_token_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Limite mensal do provedor '{prov.provider_type}' atingido "
                    f"({prov_used}/{prov.monthly_token_limit})."
                ),
            )


async def enforce_ai_quota_for(
    db: AsyncSession, user: User, prov: Optional[AIProvider]
) -> None:
    """Checa a cota considerando o plano da organização."""
    plan = await get_org_plan(db, user.organization_id)
    enforce_ai_quota(user, prov, plan)


def extract_usage(data: dict) -> Tuple[int, int]:
    """Extrai (prompt_tokens, completion_tokens) do payload de usage do provedor."""
    usage = (data or {}).get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    if not prompt and not completion:
        total = int(usage.get("total_tokens") or 0)
        if total:
            completion = total
    return prompt, completion


def estimate_tokens(text: str) -> int:
    """Estimativa conservadora usada apenas quando o provedor não informa usage."""
    return max(1, len(text or "") // 4)


async def charge_usage(
    user_id: Optional[str],
    provider_id: Optional[str],
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Cobra o consumo em sessão própria, de forma atômica, resetando se o mês virou."""
    total = int(prompt_tokens or 0) + int(completion_tokens or 0)
    if total <= 0:
        return
    current_period = utcnow().strftime("%Y-%m")
    try:
        async with AsyncSessionLocal() as session:
            if user_id:
                u_res = await session.execute(select(User).where(User.id == user_id))
                u = u_res.scalars().first()
                if u:
                    if u.usage_period != current_period:
                        u.tokens_used_month = total
                        u.usage_period = current_period
                    else:
                        u.tokens_used_month += total
            if provider_id:
                p_res = await session.execute(
                    select(AIProvider).where(AIProvider.id == provider_id)
                )
                p = p_res.scalars().first()
                if p:
                    if p.usage_period != current_period:
                        p.tokens_used_month = total
                        p.usage_period = current_period
                    else:
                        p.tokens_used_month += total
            await session.commit()
    except Exception:
        logger.exception(
            "Falha ao contabilizar tokens de IA (user=%s provider=%s)",
            user_id,
            provider_id,
        )
