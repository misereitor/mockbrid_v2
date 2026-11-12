"""Resolução única de provedores de IA (modelo, endpoint e tipo).

Antes esta lógica estava duplicada em quatro rotas de `routes_ai.py`, o que
fazia cada provedor novo precisar de quatro edições. Qualquer regra nova de
endpoint/modelo deve viver aqui.
"""

from typing import Optional, Tuple

from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models import AIProvider

DEFAULT_MODEL = "bonsai-27b"
DEFAULT_LOCAL_BASE_URL = "http://localhost:8091/v1"

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "anthropic": "https://api.anthropic.com/v1",
}
FALLBACK_BASE_URL = DEFAULT_BASE_URLS["openai"]

_LOCAL_MARKERS = ("localhost", "127.0.0.1", "172.", "10.", "192.168.", ":8091", ":11434")


def is_local_endpoint(url: str) -> bool:
    """Heurística de endpoint local (llama.cpp, Ollama, gateway na rede interna)."""
    lowered = (url or "").lower()
    return any(marker in lowered for marker in _LOCAL_MARKERS)


async def get_active_provider(
    db: AsyncSession,
    organization_id: str,
    provider_id: Optional[str] = None,
) -> Optional[AIProvider]:
    """Busca o provedor pedido (sempre restrito ao tenant) ou o primeiro ativo."""
    if provider_id:
        result = await db.execute(
            select(AIProvider).where(
                AIProvider.id == provider_id,
                AIProvider.organization_id == organization_id,
            )
        )
        return result.scalars().first()

    # Determinístico: o provedor configurado mais recentemente é o usado. Antes,
    # `.first()` sem ORDER BY escolhia uma linha arbitrária quando a organização
    # tinha mais de um provedor (ex.: uma chave antiga inválida vencia a nova).
    result = await db.execute(
        select(AIProvider)
        .where(
            AIProvider.organization_id == organization_id,
            AIProvider.is_active == True,  # noqa: E712
        )
        .order_by(desc(AIProvider.created_at))
    )
    return result.scalars().first()


def resolve_endpoint(prov: Optional[AIProvider], requested_model: Optional[str]) -> Tuple[str, str, str, bool]:
    """Retorna (modelo, base_url, provider_type, is_local_or_custom)."""
    selected_model = requested_model or (prov.default_model if prov else DEFAULT_MODEL)
    raw_base_url = (prov.base_url.strip() if prov and prov.base_url else "")
    p_type = (prov.provider_type.lower() if prov else "ollama")

    if selected_model == DEFAULT_MODEL:
        raw_base_url = DEFAULT_LOCAL_BASE_URL
        p_type = "ollama"
    elif not prov and not raw_base_url:
        raw_base_url = DEFAULT_LOCAL_BASE_URL
        p_type = "ollama"

    is_local_or_custom = p_type in ("ollama", "custom") or selected_model == DEFAULT_MODEL or any(
        marker in raw_base_url for marker in _LOCAL_MARKERS
    )

    if not raw_base_url:
        raw_base_url = DEFAULT_BASE_URLS.get(p_type, FALLBACK_BASE_URL)

    return selected_model, raw_base_url, p_type, is_local_or_custom
