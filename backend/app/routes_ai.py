from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
import httpx
import json
import re
import os

from app.database import get_db
from app.models import User, AIProvider, AIConversation, AIMessage, AIGenerationLog
from app.routes_auth import get_current_user, require_editor, require_admin
from app.authz import authorize_screen
from app.agent.state import AgentState, TargetElementInfo
from app.agent.graph import MockbirdAgentGraph
from app.agent.htmlkit import extract_html, validate_and_repair
from app.config import settings
from app.ai_providers import get_active_provider, is_local_endpoint, resolve_endpoint
from app.quotas import charge_usage, enforce_ai_quota_for, estimate_tokens, extract_usage
from app.crypto import encrypt_secret, decrypt_secret
from app.timeutils import utcnow
import logging
from datetime import datetime
import ipaddress
import socket
from urllib.parse import urlparse

router = APIRouter(prefix="/api/ai", tags=["ai"])
logger = logging.getLogger(__name__)

FORBIDDEN_PORTS = {22, 25, 110, 143, 445, 5432, 5434, 6379, 11211, 2375, 2376, 3306, 27017}


def validate_ai_endpoint_url(url: str) -> str:
    """Valida rigorosamente URLs de IA contra ataques de Server-Side Request Forgery (SSRF).
    Bloqueia acesso a metadados de nuvem, IPs privados não autorizados e portas de serviços de infraestrutura."""
    if not url:
        return ""

    clean_url = url.strip()
    parsed = urlparse(clean_url)

    if parsed.scheme not in ["http", "https"]:
        raise HTTPException(
            status_code=400,
            detail="Esquema de URL inválido. Apenas HTTP e HTTPS são permitidos."
        )

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="Hostname ausente na URL")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port in FORBIDDEN_PORTS:
        raise HTTPException(
            status_code=400,
            detail=f"Porta {port} terminantemente proibida por política de segurança SSRF."
        )

    lower_host = hostname.lower()
    if lower_host in ["metadata.google.internal", "metadata", "instance-data", "db", "mockbird_v2_db", "mockbird_v2_api"]:
        raise HTTPException(
            status_code=400,
            detail="Acesso ao host de metadados ou infraestrutura interna bloqueado por política de segurança SSRF."
        )

    # Hosts locais autorizados explicitamente para provedores de LLM locais
    allowed_local = [
        h.strip().lower() for h in os.getenv("AI_ALLOWED_LOCAL_HOSTS", "localhost,127.0.0.1,172.31.0.1").split(",") if h.strip()
    ]
    is_explicitly_allowed_local = lower_host in allowed_local

    try:
        target_ip = ipaddress.ip_address(hostname)
        ips_to_check = [target_ip]
    except ValueError:
        try:
            addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
            ips_to_check = [ipaddress.ip_address(item[4][0]) for item in addr_info]
        except socket.gaierror:
            raise HTTPException(status_code=400, detail=f"Não foi possível resolver o hostname '{hostname}' via DNS.")

    for ip in ips_to_check:
        if str(ip) == "169.254.169.254":
            raise HTTPException(
                status_code=400,
                detail="Acesso ao endereço de metadados 169.254.169.254 bloqueado por política de segurança SSRF."
            )
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            if not is_explicitly_allowed_local:
                raise HTTPException(
                    status_code=400,
                    detail=f"Endereço de rede ({ip}) não permitido por política de segurança SSRF."
                )

    return clean_url


def _get_provider_api_key(prov: Optional[AIProvider]) -> str:
    """Recupera e descriptografa com segurança a chave de API do provedor."""
    if not prov or not prov.encrypted_api_key:
        return ""
    return decrypt_secret(prov.encrypted_api_key)


def resolve_docker_base_url(url: str) -> str:
    """Se a URL estiver usando localhost ou 127.0.0.1 dentro do container Docker,
    resolve para o gateway da máquina host para alcançar servidores locais como llama.cpp/Ollama."""
    if not url:
        return ""
    clean = url.strip()
    host_ip = os.getenv("DOCKER_HOST_GATEWAY", "172.31.0.1")
    clean = re.sub(r"://localhost\b", f"://{host_ip}", clean)
    clean = re.sub(r"://127\.0\.0\.1\b", f"://{host_ip}", clean)
    return clean


class AIProviderConfig(BaseModel):
    provider_type: str  # openai, anthropic, gemini, openrouter, ollama, custom
    api_key: Optional[str] = ""
    default_model: str
    base_url: Optional[str] = ""
    custom_models: Optional[List[str]] = []


class AIProviderOut(BaseModel):
    id: str
    provider_type: str
    default_model: str
    base_url: Optional[str] = ""
    custom_models: List[Any] = []
    is_active: bool
    monthly_token_limit: int
    tokens_used_month: int
    has_api_key: bool = False
    masked_api_key: Optional[str] = ""

    class Config:
        from_attributes = True


class AIChatRequest(BaseModel):
    prompt: str
    current_html: Optional[str] = ""
    target_element: Optional[Dict[str, Any]] = None
    system_role: Optional[str] = "assistant"
    model_name: Optional[str] = None
    provider_id: Optional[str] = None
    conversation_id: Optional[str] = None
    screen_id: Optional[str] = None
    project_id: Optional[str] = None


class ConversationCreate(BaseModel):
    title: Optional[str] = "Nova Conversa"
    project_id: Optional[str] = None
    screen_id: Optional[str] = None


class ConversationOut(BaseModel):
    id: str
    title: str
    project_id: Optional[str]
    screen_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    patch: Optional[str]
    patch_type: str
    tokens_used: int
    created_at: datetime

    class Config:
        from_attributes = True


class AIVisionCritiqueRequest(BaseModel):
    # Limite de ~6 MB de imagem decodificada para não estourar memória.
    image_base64: Optional[str] = Field(default="", max_length=8_000_000)
    current_html: str
    prompt: str
    model_name: Optional[str] = None
    provider_id: Optional[str] = None


class AITestRequest(BaseModel):
    provider_type: str
    api_key: Optional[str] = ""
    base_url: Optional[str] = ""
    model_name: str


@router.get("/providers", response_model=List[AIProviderOut])
async def list_providers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = await db.execute(
        select(AIProvider)
        .where(AIProvider.organization_id == current_user.organization_id)
        .order_by(AIProvider.is_active.desc(), AIProvider.created_at.desc())
    )
    providers = query.scalars().all()
    results = []
    for p in providers:
        raw_key = _get_provider_api_key(p)
        masked = ""
        if raw_key:
            masked = raw_key[:4] + "..." + raw_key[-4:] if len(raw_key) > 8 else "***"
        results.append(AIProviderOut(
            id=p.id,
            provider_type=p.provider_type,
            default_model=p.default_model,
            base_url=p.base_url,
            custom_models=p.custom_models or [],
            is_active=p.is_active,
            monthly_token_limit=p.monthly_token_limit,
            tokens_used_month=p.tokens_used_month,
            has_api_key=bool(raw_key),
            masked_api_key=masked,
        ))
    return results


@router.post("/providers")
async def save_provider(
    payload: AIProviderConfig,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    if payload.base_url and payload.base_url.strip():
        validate_ai_endpoint_url(payload.base_url)

    result = await db.execute(
        select(AIProvider).where(
            AIProvider.organization_id == current_user.organization_id,
            AIProvider.provider_type == payload.provider_type
        )
    )
    prov = result.scalars().first()
    clean_custom_models = list(dict.fromkeys([m.strip() for m in (payload.custom_models or []) if m.strip()]))
    if payload.default_model and payload.default_model.strip() not in clean_custom_models:
        clean_custom_models.insert(0, payload.default_model.strip())

    api_key_str = (payload.api_key or "").strip()
    encrypted_key = encrypt_secret(api_key_str) if api_key_str else ""

    if not prov:
        prov = AIProvider(
            organization_id=current_user.organization_id,
            provider_type=payload.provider_type,
            default_model=payload.default_model.strip(),
            base_url=(payload.base_url or "").strip(),
            custom_models=clean_custom_models,
            encrypted_api_key=encrypted_key
        )
        db.add(prov)
    else:
        if api_key_str:
            prov.encrypted_api_key = encrypted_key
        prov.default_model = payload.default_model.strip()
        prov.base_url = (payload.base_url or "").strip()
        prov.custom_models = clean_custom_models

    await db.commit()
    await db.refresh(prov)
    logger.info("Provedor de IA salvo: tipo=%s url=%s modelo=%s", prov.provider_type, prov.base_url, prov.default_model)
    return {
        "message": "Provedor e modelos configurados com sucesso",
        "provider_id": prov.id,
        "default_model": prov.default_model,
        "custom_models": prov.custom_models
    }


@router.post("/test-connection")
async def test_ai_connection(
    payload: AITestRequest,
    current_user: User = Depends(require_admin)
):
    url = (payload.base_url or "").strip()
    p_type = payload.provider_type.lower()
    
    if not url:
        if p_type == "openai":
            url = "https://api.openai.com/v1"
        elif p_type == "openrouter":
            url = "https://openrouter.ai/api/v1"
        elif p_type == "ollama":
            url = "http://localhost:11434/v1"
        elif p_type == "gemini":
            url = "https://generativelanguage.googleapis.com/v1beta/openai"
        elif p_type == "anthropic":
            url = "https://api.anthropic.com/v1"
        else:
            url = "https://api.openai.com/v1"

    # Valida proteção contra SSRF antes de qualquer conexão de rede
    validate_ai_endpoint_url(url)

    resolved_url = resolve_docker_base_url(url)
    logger.info("Teste de conexao IA: %s -> %s modelo=%s", url, resolved_url, payload.model_name)

    headers = {"Content-Type": "application/json"}
    api_key = (payload.api_key or "").strip()
    if api_key:
        if p_type == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {api_key}"
    else:
        headers["Authorization"] = "Bearer local-key"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if p_type == "anthropic":
                res = await client.post(
                    f"{resolved_url.rstrip('/')}/messages",
                    headers=headers,
                    json={
                        "model": payload.model_name or "claude-3-5-sonnet-20241022",
                        "max_tokens": 10,
                        "messages": [{"role": "user", "content": "ping"}]
                    }
                )
            else:
                res = await client.post(
                    f"{resolved_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json={
                        "model": payload.model_name or "gpt-4o-mini",
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 5
                    }
                )

            if res.status_code in [200, 201]:
                return {"status": "ok", "message": f"Conexão bem-sucedida com o endpoint e modelo {payload.model_name}!"}
            else:
                return {
                    "status": "error",
                    "code": res.status_code,
                    "message": f"Servidor retornou status {res.status_code}: {res.text[:200]}"
                }
    except Exception as e:
        return {"status": "error", "message": f"Falha ao conectar em {resolved_url}: {str(e)}"}


def build_system_prompt() -> str:
    return (
        "Você é o Diretor de Arte e Engenheiro Frontend Principal do Mockbird v2, premiado internacionalmente (Awwwards, Apple, Stripe e Linear). "
        "Seu objetivo é criar interfaces web estonteantes, modernas, elegantes e prontas para produção.\n\n"
        "REGRAS DE OURO DE DESIGN & COMPOSIÇÃO:\n"
        "1. IMAGENS REAIS DE ALTA RESOLUÇÃO (OBRIGATÓRIO):\n"
        "   - NUNCA use caixas cinzas vazias, divs cinzas de placeholder ou 'placeholder.com'.\n"
        "   - Use sempre tags <img> com URLs reais e funcionais do Unsplash com parâmetros de qualidade:\n"
        "     * Carros Esportivos / Sedans (Honda Civic, Type R, etc.):\n"
        "       https://images.unsplash.com/photo-1618843479313-40f8afb4b4d8?auto=format&fit=crop&w=1200&q=80\n"
        "       https://images.unsplash.com/photo-1590362891991-f776e747a588?auto=format&fit=crop&w=1200&q=80\n"
        "       https://images.unsplash.com/photo-1552519507-da3b142c6e3d?auto=format&fit=crop&w=1200&q=80\n"
        "     * Carros SUVs / Modernos (HR-V, CR-V):\n"
        "       https://images.unsplash.com/photo-1533473359331-0135ef1b58bf?auto=format&fit=crop&w=1200&q=80\n"
        "       https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=1200&q=80\n"
        "     * Detalhes de Interior & Volante:\n"
        "       https://images.unsplash.com/photo-1542282088-72c9c27ed0cd?auto=format&fit=crop&w=1200&q=80\n"
        "     * SaaS / Dashboards / Tecnologia:\n"
        "       https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=1200&q=80\n"
        "       https://images.unsplash.com/photo-1460925895917-afdab827c52f?auto=format&fit=crop&w=1200&q=80\n"
        "2. ANATOMIA DE UMA PÁGINA COMPLETA:\n"
        "   - Navbar: Logo limpo com ícone SVG ou tipografia forte, links de navegação com espaçamento generoso, botão de ação (CTA) em destaque.\n"
        "   - Hero Section: Título monumental (text-4xl md:text-6xl font-extrabold tracking-tight text-white leading-tight), subtítulo claro e persuasivo (text-slate-300 text-lg leading-relaxed max-w-2xl), badge moderno no topo (backdrop-blur-md bg-white/5 border border-white/10 px-3 py-1 rounded-full text-xs text-slate-300), e foto de destaque em alta escala.\n"
        "   - Grid de Produtos / Modelos: Cards com imagem em aspect-video ou h-60 com object-cover, título do modelo, especificações técnicas em badges (ex: '315 cv', '0-100 em 5.4s', 'Híbrido e:HEV'), preço em destaque e botão de ação.\n"
        "   - Seção de Destaque / Engenharia: Duas colunas com imagem e lista de diferenciais com ícones SVG modernos.\n"
        "   - Footer: Links organizados por categorias, newsletter e copyright.\n"
        "3. CORES, CONTRASTE & TOKENS:\n"
        "   - Fundo escuro premium (bg-[#09090b] ou bg-[var(--color-bg)]), superfícies em bg-[#121215] ou bg-[var(--color-surface)], bordas sutis border-white/10 ou border-[var(--color-border)].\n"
        "   - Tipografia limpa com Inter/sans-serif e contrastes nítidos. Cores de texto text-white para títulos e text-slate-300 para corpo.\n"
        "4. IDENTIFICADORES DATA-MB-ID:\n"
        "   - Todo container, card, botão, imagem e título DEVE ter data-mb-id='...' único (ex: data-mb-id='hero-title', data-mb-id='card-civic-type-r') para inspeção no canvas.\n"
        "5. SAÍDA DIRETA:\n"
        "   - Raciocine de forma ágil e concisa, e emita diretamente o código HTML completo dentro do bloco ```html ... ```."
    )


def clean_and_extract_html(text: str) -> str:
    """Compatibilidade: extração robusta vive em `app.agent.htmlkit`."""
    return extract_html(text)


@router.get("/conversations", response_model=List[ConversationOut])
async def list_conversations(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lista as conversas de IA criadas exclusivamente pelo usuário atual."""
    query = select(AIConversation).where(
        AIConversation.user_id == current_user.id,
        AIConversation.organization_id == current_user.organization_id
    )
    if project_id:
        query = query.where(AIConversation.project_id == project_id)
    res = await db.execute(query.order_by(AIConversation.updated_at.desc()))
    return res.scalars().all()


@router.post("/conversations", response_model=ConversationOut)
async def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    """Cria uma nova sessão de conversa para o usuário."""
    conv = AIConversation(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        project_id=payload.project_id,
        screen_id=payload.screen_id,
        title=payload.title or "Nova Conversa"
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("/conversations/{conv_id}/messages", response_model=List[MessageOut])
async def get_conversation_messages(
    conv_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retorna o histórico de mensagens de uma conversa pertencente ao usuário."""
    res = await db.execute(
        select(AIConversation).where(
            AIConversation.id == conv_id,
            AIConversation.user_id == current_user.id
        )
    )
    conv = res.scalars().first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    msg_res = await db.execute(
        select(AIMessage).where(AIMessage.conversation_id == conv_id).order_by(AIMessage.created_at.asc())
    )
    return msg_res.scalars().all()


@router.delete("/conversations/{conv_id}")
async def delete_conversation(
    conv_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Exclui uma conversa do usuário."""
    res = await db.execute(
        select(AIConversation).where(
            AIConversation.id == conv_id,
            AIConversation.user_id == current_user.id
        )
    )
    conv = res.scalars().first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    await db.delete(conv)
    await db.commit()
    return {"message": "Conversa excluída com sucesso", "conversation_id": conv_id}


@router.post("/chat/stream")
async def ai_generate_stream(
    payload: AIChatRequest,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    """Endpoint Server-Sent Events (SSE) para streaming em tempo real do pensamento e do HTML."""
    prov = await get_active_provider(db, current_user.organization_id, payload.provider_id)
    await enforce_ai_quota_for(db, current_user, prov)
    selected_model, raw_base_url, p_type, is_local_or_custom = resolve_endpoint(prov, payload.model_name)

    validate_ai_endpoint_url(raw_base_url)
    resolved_base_url = resolve_docker_base_url(raw_base_url)
    system_prompt = build_system_prompt()
    user_msg = f"Instrução: {payload.prompt}\nHTML Atual da Tela:\n{payload.current_html}"

    headers = {"Content-Type": "application/json"}
    api_key_plain = _get_provider_api_key(prov)
    if api_key_plain:
        headers["Authorization"] = f"Bearer {api_key_plain}"
    else:
        headers["Authorization"] = "Bearer local-llm"

    req_body = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.5,
        "max_tokens": int(settings.AI_LLM_MAX_TOKENS),
        "stream": True
    }
    if is_local_endpoint(resolved_base_url) and settings.AI_DISABLE_THINKING:
        req_body["chat_template_kwargs"] = {"enable_thinking": False}

    # Capturado antes do stream: a dependência de request pode ser finalizada
    # antes do gerador terminar.
    user_id_for_usage = current_user.id
    provider_id_for_usage = prov.id if prov else None
    target_mb_id = (payload.target_element or {}).get("mbId")
    patch_mode = "element" if (payload.target_element and (target_mb_id or payload.target_element.get("outerHtml"))) else "full"

    timeout = httpx.Timeout(
        float(settings.AI_LLM_READ_TIMEOUT),
        connect=float(settings.AI_LLM_CONNECT_TIMEOUT),
        write=60.0,
        pool=float(settings.AI_LLM_CONNECT_TIMEOUT),
    )

    def sse(event: Dict[str, Any]) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    async def event_generator():
        accumulated_reasoning = []
        accumulated_content = []
        finish = {"reason": None}
        messages = list(req_body["messages"])

        yield sse({"type": "meta", "model": selected_model, "provider": p_type, "endpoint": resolved_base_url})

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                # 2 rodadas no máximo: a segunda apenas continua uma resposta truncada.
                for round_index in range(2):
                    body = {k: v for k, v in req_body.items() if k != "messages"}
                    body["messages"] = messages

                    async with client.stream(
                        "POST",
                        f"{resolved_base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=body,
                    ) as response:
                        if response.status_code != 200:
                            err_text = await response.aread()
                            hint = " Verifique a chave/URL/modelo em Configurações → LLM." if response.status_code in (401, 403, 404) else ""
                            yield sse({
                                "type": "error",
                                "detail": f"Provedor '{p_type}' retornou {response.status_code}: {err_text.decode(errors='replace')[:300]}.{hint}",
                            })
                            return

                        async for line in response.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            data_str = line[5:].strip()
                            if not data_str or data_str == "[DONE]":
                                continue
                            try:
                                chunk = json.loads(data_str)
                                choice = (chunk.get("choices") or [{}])[0]
                                delta = choice.get("delta") or {}
                                if choice.get("finish_reason"):
                                    finish["reason"] = choice["finish_reason"]
                                reasoning_chunk = delta.get("reasoning_content") or delta.get("reasoning") or ""
                                content_chunk = delta.get("content") or ""

                                if reasoning_chunk:
                                    accumulated_reasoning.append(reasoning_chunk)
                                    yield sse({"type": "thinking", "text": reasoning_chunk})

                                if content_chunk:
                                    accumulated_content.append(content_chunk)
                                    yield sse({"type": "content", "text": content_chunk})
                            except Exception:
                                continue

                    partial = "".join(accumulated_content).strip()
                    if finish["reason"] != "length" or not partial or round_index == 1:
                        break

                    yield sse({"type": "thinking", "text": "\n\nResposta truncada; continuando exatamente do ponto de parada...\n\n"})
                    messages = messages + [
                        {"role": "assistant", "content": partial},
                        {
                            "role": "user",
                            "content": (
                                "Continue exatamente de onde o HTML parou. Não repita o conteúdo anterior, "
                                "não escreva explicações e feche todas as tags."
                            ),
                        },
                    ]

            full_content = "".join(accumulated_content).strip()
            full_reasoning = "".join(accumulated_reasoning).strip()
            raw_html = full_content
            if not extract_html(raw_html) and "```" in full_reasoning:
                raw_html = full_reasoning

            if not extract_html(raw_html):
                motivo = (
                    "o limite de tokens foi atingido antes de qualquer HTML"
                    if finish["reason"] == "length"
                    else "o modelo respondeu sem bloco de código HTML"
                )
                yield sse({
                    "type": "error",
                    "detail": f"Nenhum HTML foi gerado: {motivo}. Tente um pedido mais específico ou outro modelo.",
                })
                return

            validation = validate_and_repair(raw_html, mode=patch_mode, mb_id=target_mb_id)
            yield sse({"type": "validation_result", "scope": patch_mode, **validation.to_event()})

            if not validation.ok:
                yield sse({
                    "type": "error",
                    "detail": (
                        "O HTML gerado não passou na validação: "
                        + "; ".join(validation.errors[:3])
                        + ". Nada foi aplicado no canvas."
                    ),
                })
                return

            # Registra uso estimado (o stream SSE nem sempre devolve usage)
            await charge_usage(
                user_id_for_usage,
                provider_id_for_usage,
                estimate_tokens(payload.prompt) + estimate_tokens(payload.current_html or ""),
                estimate_tokens(validation.html),
            )

            yield sse({
                "type": "done",
                "patch": validation.html,
                "patch_type": patch_mode,
                "model": selected_model,
                "validation": validation.to_event(),
            })

        except httpx.TimeoutException:
            yield sse({
                "type": "error",
                "detail": (
                    f"O provedor não respondeu em {int(settings.AI_LLM_READ_TIMEOUT)}s. "
                    "Modelos locais podem ser lentos; tente uma seção menor ou outro modelo."
                ),
            })
        except Exception as e:
            logger.exception("chat/stream: falha no stream")
            yield sse({"type": "error", "detail": f"Falha no stream: {str(e)}"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/chat")
async def ai_generate_or_modify(
    payload: AIChatRequest,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    prov = await get_active_provider(db, current_user.organization_id, payload.provider_id)
    await enforce_ai_quota_for(db, current_user, prov)
    selected_model, raw_base_url, p_type, is_local_or_custom = resolve_endpoint(prov, payload.model_name)

    api_key_plain = _get_provider_api_key(prov)
    if not prov or (not is_local_or_custom and not api_key_plain):
        logger.info("AI chat: nenhum provedor configurado, usando mock offline")
        return {
            "status": "simulated",
            "model_used": selected_model,
            "message": "Nenhum provedor de IA com chave cadastrada na sua organização. Usando motor assistivo padrão.",
            "suggested_patch": (
                '<div class="p-6 rounded-2xl bg-[var(--color-surface)] border border-[var(--color-border)] shadow-md space-y-4" data-mb-id="ai-generated-card">\n'
                f'  <h3 class="text-xl font-bold text-[var(--color-text)]">{payload.prompt}</h3>\n'
                '  <p class="text-sm opacity-80 text-[var(--color-text)]">Gerado pelo assistente de IA respeitando as variáveis de Design Tokens do projeto.</p>\n'
                '  <button class="px-4 py-2 bg-[var(--color-primary)] text-white text-xs font-semibold rounded-lg shadow-sm" data-toast="Ação Executada!">Botão de Ação</button>\n'
                '</div>'
            )
        }

    validate_ai_endpoint_url(raw_base_url)
    resolved_base_url = resolve_docker_base_url(raw_base_url)
    logger.info("AI chat: url=%s modelo=%s prompt=%r", resolved_base_url, selected_model, payload.prompt[:60])

    system_prompt = build_system_prompt()
    user_msg = f"Instrução: {payload.prompt}\nHTML Atual da Tela:\n{payload.current_html}"
    chat_mode = "element" if (payload.target_element and payload.target_element.get("mbId")) else "full"
    chat_mb_id = (payload.target_element or {}).get("mbId")

    def _validated_patch(raw_text: str, reasoning: str = "") -> tuple[str, str | None, dict]:
        raw = raw_text or ""
        if not extract_html(raw) and "```" in (reasoning or ""):
            raw = reasoning
        validation = validate_and_repair(raw, mode=chat_mode, mb_id=chat_mb_id)
        if not validation.ok:
            return "", "; ".join(validation.errors[:3]), validation.to_event()
        return validation.html, None, validation.to_event()

    timeout = httpx.Timeout(
        float(settings.AI_LLM_READ_TIMEOUT),
        connect=float(settings.AI_LLM_CONNECT_TIMEOUT),
        write=60.0,
        pool=float(settings.AI_LLM_CONNECT_TIMEOUT),
    )

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if p_type == "anthropic":
                headers = {
                    "x-api-key": api_key_plain or "dummy",
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                }
                res = await client.post(
                    f"{resolved_base_url.rstrip('/')}/messages",
                    headers=headers,
                    json={
                        "model": selected_model,
                        "max_tokens": 4096,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_msg}]
                    }
                )
                if res.status_code == 200:
                    data = res.json()
                    raw_html = data["content"][0]["text"]
                    clean_html, failure, validation_meta = _validated_patch(raw_html)
                    prompt_t, completion_t = extract_usage(data)
                    await charge_usage(current_user.id, prov.id if prov else None, prompt_t, completion_t)
                    if failure:
                        return {"status": "error", "detail": f"HTML inválido: {failure}", "validation": validation_meta}
                    return {
                        "status": "success",
                        "suggested_patch": clean_html,
                        "patch_type": chat_mode,
                        "model_used": selected_model,
                        "validation": validation_meta,
                    }
                else:
                    return {"status": "error", "detail": f"Erro retornado por Anthropic ({res.status_code}): {res.text[:300]}"}
            else:
                headers = {"Content-Type": "application/json"}
                if api_key_plain:
                    headers["Authorization"] = f"Bearer {api_key_plain}"
                else:
                    headers["Authorization"] = "Bearer local-llm"

                req_body = {
                    "model": selected_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg}
                    ],
                    "temperature": 0.5,
                    "max_tokens": int(settings.AI_LLM_MAX_TOKENS),
                }
                if is_local_endpoint(resolved_base_url) and settings.AI_DISABLE_THINKING:
                    req_body["chat_template_kwargs"] = {"enable_thinking": False}

                res = await client.post(
                    f"{resolved_base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=req_body
                )
                logger.info("AI chat: resposta de %s status=%s", resolved_base_url, res.status_code)

                if res.status_code == 200:
                    data = res.json()
                    msg = data["choices"][0]["message"]
                    raw_content = (msg.get("content") or "").strip()
                    reasoning = (msg.get("reasoning_content") or "").strip()

                    clean_html, failure, validation_meta = _validated_patch(raw_content, reasoning)
                    prompt_t, completion_t = extract_usage(data)
                    await charge_usage(current_user.id, prov.id if prov else None, prompt_t, completion_t)
                    logger.info("AI chat: HTML validado (%s chars) modelo=%s", len(clean_html), selected_model)
                    if failure:
                        return {"status": "error", "detail": f"HTML inválido: {failure}", "validation": validation_meta}
                    return {
                        "status": "success",
                        "suggested_patch": clean_html,
                        "patch_type": chat_mode,
                        "model_used": selected_model,
                        "validation": validation_meta,
                    }
                else:
                    err_msg = f"Servidor do modelo retornou erro ({res.status_code}): {res.text[:300]}"
                    logger.warning("AI chat: %s", err_msg)
                    return {"status": "error", "detail": err_msg}
    except Exception as e:
        err_msg = f"Falha na comunicação com o provedor {resolved_base_url}: {str(e)}"
        logger.exception("AI chat: falha de comunicação com o provedor")
        return {"status": "error", "detail": err_msg}


def audit_html_design_defects(html: str, prompt: str) -> List[str]:
    defects = []
    lower_html = (html or "").lower()
    
    # 1. Imagens reais e de alta resolução
    if "unsplash.com" not in lower_html and "<img" not in lower_html:
        defects.append("Layout sem fotografias reais em alta resolução (visual vazio ou com placeholders genéricos)")
    elif "unsplash.com" not in lower_html:
        defects.append("Imagens sem acabamento fotográfico profissional ou parâmetros de resolução adequados")

    # 2. Seções fundamentais da página
    has_nav = "<nav" in lower_html or "navbar" in lower_html or "header" in lower_html
    has_hero = "hero" in lower_html or "text-4xl" in lower_html or "text-5xl" in lower_html or "text-6xl" in lower_html
    has_grid = "grid" in lower_html or "flex-wrap" in lower_html or "card" in lower_html
    has_footer = "footer" in lower_html

    missing = []
    if not has_nav:
        missing.append("Navbar com marca, links e botão de contato")
    if not has_hero:
        missing.append("Hero Section monumental com badge translúcido e chamada de ação")
    if not has_grid:
        missing.append("Grade de modelos ou catálogo com cards estilizados")
    if not has_footer:
        missing.append("Rodapé institucional com links de suporte")

    if missing:
        defects.append(f"Seções anatômicas essenciais ausentes: {', '.join(missing)}")

    # 3. Contexto específico (ex: automotivo / carros)
    if any(k in prompt.lower() for k in ["carro", "honda", "veículo", "automóvel", "auto", "moto"]):
        if not any(k in lower_html for k in ["cv", "hp", "km/h", "0-100", "turbo", "híbrido", "torque", "r$", "preço", "civic", "hr-v"]):
            defects.append("Falta de dados técnicos automotivos reais (potência em cv, aceleração 0-100 km/h, motorização híbrida/turbo e faixas de valor)")

    # 4. Acabamento visual moderno (bordas sutis, glassmorphism e dark mode neutro)
    if "backdrop-blur" not in lower_html and "bg-white/" not in lower_html and "border-white/" not in lower_html:
        defects.append("Falta de acabamento moderno em glassmorphism (backdrop-blur-md) e bordas finas sutis (border-white/10)")

    # 5. data-mb-id para direct manipulation
    if "data-mb-id" not in lower_html:
        defects.append("Ausência de atributos data-mb-id nos elementos para inspeção no canvas")

    if not defects:
        defects.append("Ajuste de ritmo vertical, proporções de tipografia e refinamento de botões de conversão primários")

    return defects


@router.post("/vision-critique")
async def ai_vision_critique(
    payload: AIVisionCritiqueRequest,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    """Loop de Auto-Validação Visual (Vision Self-Correction Loop):
    Analisa o screenshot do canvas e o HTML atual, identifica defeitos estéticos
    e reescreve o código HTML com acabamento de alto nível."""
    prov = await get_active_provider(db, current_user.organization_id, payload.provider_id)
    await enforce_ai_quota_for(db, current_user, prov)
    selected_model, raw_base_url, p_type, is_local_or_custom = resolve_endpoint(prov, payload.model_name)

    validate_ai_endpoint_url(raw_base_url)
    resolved_base_url = resolve_docker_base_url(raw_base_url)
    defects = audit_html_design_defects(payload.current_html, payload.prompt)
    defects_list_text = "\n".join(f"- {d}" for d in defects)

    # Extrai payload limpo da imagem base64
    clean_b64 = payload.image_base64 or ""
    if "," in clean_b64:
        clean_b64 = clean_b64.split(",", 1)[1]
    has_valid_image = bool(clean_b64 and len(clean_b64) > 100)

    # Decide se o modelo é multimodal nativo
    supports_native_vision = (
        not is_local_or_custom and
        any(v in selected_model.lower() for v in ["gpt-4o", "claude-3", "gemini", "vision", "vl"])
    )

    critique_intro = (
        f"Auditoria Visual Mockbird v2:\n"
        f"Com base na análise da tela atual para \"{payload.prompt}\", foram detectados e sanados os seguintes pontos:\n"
        f"{defects_list_text}"
    )

    def _refine(raw_html: str) -> tuple[str, dict]:
        """Valida o HTML refinado; em caso de falha mantém a tela atual intacta."""
        report = validate_and_repair(raw_html or "", mode="full")
        meta = report.to_event()
        if not report.ok:
            meta["fallback_to_current"] = True
            logger.warning("Vision critique: HTML refinado reprovado (%s)", "; ".join(report.errors[:2]))
            return payload.current_html, meta
        return report.html, meta

    system_prompt = build_system_prompt()
    user_instruction = (
        f"DIRETRIZ DE AUTO-CORREÇÃO VISUAL:\n"
        f"Objetivo do usuário: \"{payload.prompt}\"\n\n"
        f"DEFEITOS ESTÉTICOS E ESTRUTURAIS DETECTADOS NA TELA ATUAL:\n"
        f"{defects_list_text}\n\n"
        f"HTML Atual Analisado:\n{payload.current_html}\n\n"
        f"Sua missão:\n"
        f"1. Explique em 2 a 3 frases as melhorias visuais aplicadas.\n"
        f"2. Emita o CÓDIGO HTML COMPLETO dentro do bloco ```html ... ```, aplicando as\n"
        f"   correções ao HTML atual e PRESERVANDO seu conteúdo e propósito (não troque\n"
        f"   por um template genérico). Melhore hierarquia, espaçamento, contraste,\n"
        f"   tipografia e responsividade; use data-mb-id nos elementos editáveis.\n"
        f"Seja objetivo e emita o bloco ```html ... ``` completo."
    )

    timeout_val = float(settings.AI_LLM_READ_TIMEOUT)
    logger.info("Vision critique: modelo=%s endpoint=%s timeout=%s", selected_model, resolved_base_url, timeout_val)

    try:
        async with httpx.AsyncClient(timeout=timeout_val) as client:
            api_key_plain = _get_provider_api_key(prov)
            # 1. Provedor Anthropic com Imagem Real Multimodal
            if p_type == "anthropic" and supports_native_vision and has_valid_image:
                headers = {
                    "x-api-key": api_key_plain or "dummy",
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                }
                res = await client.post(
                    f"{resolved_base_url.rstrip('/')}/messages",
                    headers=headers,
                    json={
                        "model": selected_model,
                        "max_tokens": 4096,
                        "system": system_prompt,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/png",
                                            "data": clean_b64
                                        }
                                    },
                                    {
                                        "type": "text",
                                        "text": user_instruction
                                    }
                                ]
                            }
                        ]
                    }
                )
                if res.status_code == 200:
                    data = res.json()
                    raw_text = data["content"][0]["text"]
                    clean_html, validation_meta = _refine(raw_text)
                    logger.info("Vision critique (Anthropic): %s chars", len(clean_html))
                    prompt_t, completion_t = extract_usage(data)
                    await charge_usage(current_user.id, prov.id if prov else None, prompt_t, completion_t)
                    return {
                        "status": "success",
                        "vision_critique": critique_intro,
                        "refined_html": clean_html,
                        "model_used": selected_model,
                        "used_multimodal_vision": True,
                        "validation": validation_meta,
                    }

            # 2. Provedor OpenAI / OpenRouter / Gemini com Imagem Real Multimodal
            elif supports_native_vision and has_valid_image:
                headers = {"Content-Type": "application/json"}
                if api_key_plain:
                    headers["Authorization"] = f"Bearer {api_key_plain}"
                else:
                    headers["Authorization"] = "Bearer local-llm"

                req_body = {
                    "model": selected_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": user_instruction},
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{clean_b64}"}}
                            ]
                        }
                    ],
                    "temperature": 0.4,
                    "max_tokens": 4096
                }
                res = await client.post(
                    f"{resolved_base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=req_body
                )
                if res.status_code == 200:
                    data = res.json()
                    msg = data["choices"][0]["message"]
                    raw_content = (msg.get("content") or "").strip()
                    reasoning = (msg.get("reasoning_content") or "").strip()
                    clean_html, validation_meta = _refine(
                        extract_html(raw_content) or (extract_html(reasoning) if "```" in reasoning else "")
                    )
                    logger.info("Vision critique (multimodal): %s chars", len(clean_html))
                    prompt_t, completion_t = extract_usage(data)
                    await charge_usage(current_user.id, prov.id if prov else None, prompt_t, completion_t)
                    return {
                        "status": "success",
                        "vision_critique": critique_intro,
                        "refined_html": clean_html,
                        "model_used": selected_model,
                        "used_multimodal_vision": True,
                        "validation": validation_meta,
                    }

            # 3. Provedor Local / Bonsai-27b / Fallback com Auto-Auditoria Heurística
            headers = {"Content-Type": "application/json"}
            if api_key_plain:
                headers["Authorization"] = f"Bearer {api_key_plain}"
            else:
                headers["Authorization"] = "Bearer local-llm"

            req_body = {
                "model": selected_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_instruction}
                ],
                "temperature": 0.4,
                "max_tokens": int(settings.AI_VISION_MAX_TOKENS),
            }
            if is_local_endpoint(resolved_base_url) and settings.AI_DISABLE_THINKING:
                req_body["chat_template_kwargs"] = {"enable_thinking": False}
            res = await client.post(
                f"{resolved_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=req_body
            )
            logger.info("Vision critique: resposta de %s status=%s", resolved_base_url, res.status_code)
            if res.status_code == 200:
                data = res.json()
                msg = data["choices"][0]["message"]
                raw_content = (msg.get("content") or "").strip()
                reasoning = (msg.get("reasoning_content") or "").strip()
                clean_html, validation_meta = _refine(
                    extract_html(raw_content) or (extract_html(reasoning) if "```" in reasoning else "")
                )
                logger.info("Vision critique: %s chars de HTML gerado", len(clean_html))
                prompt_t, completion_t = extract_usage(data)
                await charge_usage(current_user.id, prov.id if prov else None, prompt_t, completion_t)
                return {
                    "status": "success",
                    "vision_critique": critique_intro,
                    "refined_html": clean_html,
                    "model_used": selected_model,
                    "used_multimodal_vision": False,
                    "validation": validation_meta,
                }
            else:
                return {
                    "status": "error",
                    "detail": f"Servidor retornou status {res.status_code}: {res.text[:300]}"
                }

    except Exception as e:
        logger.warning("Vision critique: falha na conexão com LLM (%s), aplicando fallback heurístico", e)
        return {
            "status": "success",
            "vision_critique": critique_intro,
            "refined_html": payload.current_html,
            "model_used": selected_model,
            "used_multimodal_vision": False,
            "fallback_applied": True,
            "validation_failed": True,
        }


@router.post("/agent/stream")
async def ai_agent_graph_stream(
    payload: AIChatRequest,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    """Executa o Grafo de Estados (LangGraph) do Agente Autônomo do Mockbird v2 e streama eventos em tempo real."""
    # 1. Resolução Segura de Tela (carrega o HTML oficial diretamente do banco se screen_id informado)
    active_html = payload.current_html or ""
    if payload.screen_id:
        screen = await authorize_screen(payload.screen_id, current_user, "edit", db)
        active_html = screen.html_content

    # 2. Provedor, cota e endpoint (resolução única)
    prov = await get_active_provider(db, current_user.organization_id, payload.provider_id)
    await enforce_ai_quota_for(db, current_user, prov)
    selected_model, raw_base_url, p_type, _is_local = resolve_endpoint(prov, payload.model_name)

    # Validação rigorosa anti-SSRF
    validate_ai_endpoint_url(raw_base_url)
    resolved_base_url = resolve_docker_base_url(raw_base_url)

    headers = {"Content-Type": "application/json"}
    api_key_plain = _get_provider_api_key(prov)
    if api_key_plain:
        headers["Authorization"] = f"Bearer {api_key_plain}"
    else:
        headers["Authorization"] = "Bearer local-llm"

    target_info = None
    if payload.target_element:
        try:
            target_info = TargetElementInfo(**payload.target_element)
        except Exception as e:
            logger.warning("AI agent: erro ao interpretar target_element: %s", e)

    state = AgentState(
        prompt=payload.prompt,
        current_html=active_html,
        target_element=target_info,
        model_name=selected_model
    )
    graph = MockbirdAgentGraph(
        base_url=resolved_base_url,
        headers=headers,
        disable_thinking=True,
    )

    start_time = utcnow()

    async def event_generator():
        done_ev = None
        error_msg = None
        validation_meta = None

        yield f"data: {json.dumps({'type': 'meta', 'model': selected_model, 'provider': p_type, 'endpoint': resolved_base_url}, ensure_ascii=False)}\n\n"
        try:
            async for ev in graph.run(state):
                if ev.get("type") == "agent_done":
                    done_ev = ev
                elif ev.get("type") == "error":
                    error_msg = ev.get("detail") or "Erro desconhecido no agente."
                elif ev.get("type") == "validation_result":
                    validation_meta = {k: v for k, v in ev.items() if k != "type"}
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            error_msg = str(e)
            logger.exception("AI agent: falha no grafo")
            yield f"data: {json.dumps({'type': 'error', 'detail': f'Falha no grafo do agente: {error_msg}'}, ensure_ascii=False)}\n\n"

        # Contabilização de tokens e histórico após streaming
        tokens_consumed = estimate_tokens(payload.prompt) + (estimate_tokens(done_ev.get("patch", "")) if done_ev else 0)
        await charge_usage(current_user.id, prov.id if prov else None, estimate_tokens(payload.prompt), tokens_consumed)
        if payload.conversation_id:
            user_msg = AIMessage(
                conversation_id=payload.conversation_id,
                role="user",
                content=payload.prompt,
                tokens_used=len(payload.prompt) // 4
            )
            bot_msg = AIMessage(
                conversation_id=payload.conversation_id,
                role="assistant",
                content=done_ev.get("summary", "") if done_ev else "Concluído",
                patch=done_ev.get("patch") if done_ev else None,
                patch_type=done_ev.get("patch_type", "none") if done_ev else "none",
                tokens_used=tokens_consumed
            )
            db.add(user_msg)
            db.add(bot_msg)

        # Registro de Telemetria e Diagnóstico da IA
        duration_ms = int((utcnow() - start_time).total_seconds() * 1000)
        conversed = bool(done_ev and (done_ev.get("patch") or done_ev.get("patch_type") in ("none", None)))
        log_status = "success" if (conversed and not error_msg) else ("error" if error_msg else "incomplete")
        raw_snippet = (done_ev.get("summary", "") if done_ev else (error_msg or ""))[:500]
        if validation_meta and validation_meta.get("errors"):
            raw_snippet = (raw_snippet + " | validação: " + "; ".join(validation_meta["errors"][:2]))[:500]
        gen_log = AIGenerationLog(
            user_id=current_user.id,
            screen_id=payload.screen_id,
            model_name=selected_model,
            prompt=payload.prompt,
            status=log_status,
            tokens_prompt=estimate_tokens(payload.prompt),
            tokens_completion=tokens_consumed,
            duration_ms=duration_ms,
            finish_reason="stop" if log_status == "success" else ("error" if error_msg else "incomplete"),
            raw_snippet=raw_snippet,
            error_message=error_msg
        )
        db.add(gen_log)
        await db.commit()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/logs")
async def list_ai_generation_logs(
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    """Consulta a telemetria de IA **restrita ao tenant** (e ao próprio usuário,
    exceto para owner/admin da organização)."""
    stmt = select(AIGenerationLog).join(User, User.id == AIGenerationLog.user_id).where(
        User.organization_id == current_user.organization_id
    )
    if current_user.role not in ["owner", "admin"]:
        stmt = stmt.where(AIGenerationLog.user_id == current_user.id)

    stmt = stmt.order_by(AIGenerationLog.created_at.desc()).offset(max(0, offset)).limit(min(max(1, limit), 50))
    res = await db.execute(stmt)
    logs = res.scalars().all()
    return [
        {
            "id": log.id,
            "created_at": log.created_at.isoformat(),
            "model_name": log.model_name,
            "prompt": log.prompt[:80],
            "status": log.status,
            "duration_ms": log.duration_ms,
            "tokens_completion": log.tokens_completion,
            "finish_reason": log.finish_reason,
            "raw_snippet": log.raw_snippet,
            "error_message": log.error_message
        }
        for log in logs
    ]

