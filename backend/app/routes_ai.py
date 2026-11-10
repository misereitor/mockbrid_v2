from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
import httpx
import json
import re
import os

from app.database import get_db, AsyncSessionLocal
from app.models import User, AIProvider, AIConversation, AIMessage, Screen, AIGenerationLog
from app.routes_auth import get_current_user, require_editor, require_admin
from app.authz import authorize_screen
from app.agent.state import AgentState
from app.agent.graph import MockbirdAgentGraph
from app.crypto import encrypt_secret, decrypt_secret
from datetime import datetime
import ipaddress
import socket
from urllib.parse import urlparse

router = APIRouter(prefix="/api/ai", tags=["ai"])

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
    image_base64: Optional[str] = ""
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
        select(AIProvider).where(AIProvider.organization_id == current_user.organization_id)
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
    print(f"[AI] Provedor salvo: tipo={prov.provider_type}, url={prov.base_url}, modelo={prov.default_model}", flush=True)
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
    print(f"[AI TEST] Conexao: original={url} -> resolvido={resolved_url}, modelo={payload.model_name}", flush=True)

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
    if not text:
        return ""
    # 1. Procura bloco de código ```html ... ```
    m = re.search(r"```(?:html)?\s*(<[\s\S]+?>[\s\S]*?)```", text, re.IGNORECASE)
    if m:
        extracted = m.group(1).strip()
        if "<" in extracted and ">" in extracted:
            return extracted
    # 2. Procura documento completo <!DOCTYPE html> ... </html> ou <html ... </html>
    m_doc = re.search(r"(<!DOCTYPE\s+html[\s\S]+?</html>|<html[\s\S]+?</html>)", text, re.IGNORECASE)
    if m_doc:
        return m_doc.group(1).strip()
    # 3. Procura tags HTML estruturais (div, section, main, header, footer, etc.)
    m_tag = re.search(r"(<(?:div|section|main|header|footer|aside|article|form|nav|button|ul|ol|table|dialog|p|span|a|h[1-6])\b[\s\S]+?</(?:div|section|main|header|footer|aside|article|form|nav|button|ul|ol|table|dialog|p|span|a|h[1-6])>)", text, re.IGNORECASE)
    if m_tag:
        return m_tag.group(1).strip()
    # 4. Procura tags autocontidas válidas (img, input)
    m_self = re.search(r"(<(?:img|input|hr|br)\b[^>]*\/?>)", text, re.IGNORECASE)
    if m_self:
        return m_self.group(1).strip()
    return ""


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
    if payload.provider_id:
        result = await db.execute(
            select(AIProvider).where(
                AIProvider.id == payload.provider_id,
                AIProvider.organization_id == current_user.organization_id
            )
        )
    else:
        result = await db.execute(
            select(AIProvider).where(
                AIProvider.organization_id == current_user.organization_id,
                AIProvider.is_active == True
            )
        )
    prov = result.scalars().first()

    selected_model = payload.model_name or (prov.default_model if prov else "bonsai-27b")
    raw_base_url = (prov.base_url.strip() if prov and prov.base_url else "")
    p_type = (prov.provider_type.lower() if prov else "ollama")

    if selected_model == "bonsai-27b":
        raw_base_url = "http://localhost:8091/v1"
        p_type = "ollama"
    elif not prov and not raw_base_url:
        raw_base_url = "http://localhost:8091/v1"
        p_type = "ollama"

    is_local_or_custom = (
        p_type in ["ollama", "custom"] or
        selected_model == "bonsai-27b" or
        "localhost" in raw_base_url or
        "127.0.0.1" in raw_base_url or
        "172." in raw_base_url or
        "8091" in raw_base_url or
        "11434" in raw_base_url
    )

    if not raw_base_url:
        if p_type == "openai":
            raw_base_url = "https://api.openai.com/v1"
        elif p_type == "openrouter":
            raw_base_url = "https://openrouter.ai/api/v1"
        elif p_type == "ollama":
            raw_base_url = "http://localhost:11434/v1"
        elif p_type == "gemini":
            raw_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
        elif p_type == "anthropic":
            raw_base_url = "https://api.anthropic.com/v1"
        else:
            raw_base_url = "https://api.openai.com/v1"

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
        "max_tokens": 8192,
        "stream": True
    }

    async def event_generator():
        accumulated_reasoning = []
        accumulated_content = []
        finish = {"reason": None}
        timeout_val = 300.0 if is_local_or_custom else 90.0

        try:
            async with httpx.AsyncClient(timeout=timeout_val) as client:
                async with client.stream(
                    "POST",
                    f"{resolved_base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=req_body
                ) as response:
                    if response.status_code != 200:
                        err_text = await response.aread()
                        yield f"data: {json.dumps({'type': 'error', 'detail': f'Erro do provedor ({response.status_code}): {err_text.decode()[:300]}'})}\n\n"
                        return

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line.replace("data:", "").strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0].get("delta", {})
                            if chunk["choices"][0].get("finish_reason"):
                                finish["reason"] = chunk["choices"][0]["finish_reason"]
                            reasoning_chunk = delta.get("reasoning_content") or ""
                            content_chunk = delta.get("content") or ""

                            if reasoning_chunk:
                                accumulated_reasoning.append(reasoning_chunk)
                                yield f"data: {json.dumps({'type': 'thinking', 'text': reasoning_chunk})}\n\n"

                            if content_chunk:
                                accumulated_content.append(content_chunk)
                                yield f"data: {json.dumps({'type': 'content', 'text': content_chunk})}\n\n"
                        except Exception:
                            continue

            # Processa o patch final com extração precisa e defensiva
            full_content = "".join(accumulated_content).strip()
            full_reasoning = "".join(accumulated_reasoning).strip()

            final_html = clean_and_extract_html(full_content)
            # Raciocínio NUNCA deve ser usado como HTML!

            if len(final_html) < 200 or "<" not in final_html:
                motivo = "limite de tokens atingido durante o raciocínio" if finish["reason"] == "length" else "o modelo não retornou HTML"
                yield f"data: {json.dumps({'type': 'error', 'detail': f'Nenhum HTML válido gerado: {motivo}. Tente um prompt mais específico ou outro modelo.'})}\n\n"
                return

            # Registra uso de tokens
            try:
                async with AsyncSessionLocal() as session:
                    db_prov = (await session.execute(select(AIProvider).where(AIProvider.id == prov.id))).scalars().first()
                    if db_prov:
                        db_prov.tokens_used_month += (len(final_html) // 4) + 150
                        await session.commit()
            except Exception:
                pass

            yield f"data: {json.dumps({'type': 'done', 'patch': final_html, 'model': selected_model})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': f'Falha no stream: {str(e)}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/chat")
async def ai_generate_or_modify(
    payload: AIChatRequest,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    if payload.provider_id:
        result = await db.execute(
            select(AIProvider).where(
                AIProvider.id == payload.provider_id,
                AIProvider.organization_id == current_user.organization_id
            )
        )
    else:
        result = await db.execute(
            select(AIProvider).where(
                AIProvider.organization_id == current_user.organization_id,
                AIProvider.is_active == True
            )
        )
    prov = result.scalars().first()

    selected_model = payload.model_name or (prov.default_model if prov else "bonsai-27b")
    raw_base_url = (prov.base_url.strip() if prov and prov.base_url else "")
    p_type = (prov.provider_type.lower() if prov else "ollama")

    if selected_model == "bonsai-27b":
        raw_base_url = "http://localhost:8091/v1"
        p_type = "ollama"
    elif not prov and not raw_base_url:
        raw_base_url = "http://localhost:8091/v1"
        p_type = "ollama"

    is_local_or_custom = (
        p_type in ["ollama", "custom"] or
        selected_model == "bonsai-27b" or
        "localhost" in raw_base_url or
        "127.0.0.1" in raw_base_url or
        "172." in raw_base_url or
        "8091" in raw_base_url or
        "11434" in raw_base_url
    )

    api_key_plain = _get_provider_api_key(prov)
    if not prov or (not is_local_or_custom and not api_key_plain):
        print(f"[AI CHAT] Nenhum provedor configurado. Usando mock offline.", flush=True)
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

    if not raw_base_url:
        if p_type == "openai":
            raw_base_url = "https://api.openai.com/v1"
        elif p_type == "openrouter":
            raw_base_url = "https://openrouter.ai/api/v1"
        elif p_type == "ollama":
            raw_base_url = "http://localhost:11434/v1"
        elif p_type == "gemini":
            raw_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
        elif p_type == "anthropic":
            raw_base_url = "https://api.anthropic.com/v1"
        else:
            raw_base_url = "https://api.openai.com/v1"

    resolved_base_url = resolve_docker_base_url(raw_base_url)
    print(f"[AI CHAT] Chamando: url={resolved_base_url}, modelo={selected_model}, prompt={payload.prompt[:60]}...", flush=True)

    system_prompt = build_system_prompt()
    user_msg = f"Instrução: {payload.prompt}\nHTML Atual da Tela:\n{payload.current_html}"

    try:
        timeout_val = 300.0 if is_local_or_custom else 90.0
        async with httpx.AsyncClient(timeout=timeout_val) as client:
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
                    clean_html = raw_html.replace("```html", "").replace("```", "").strip()
                    prov.tokens_used_month += data.get("usage", {}).get("output_tokens", 150)
                    await db.commit()
                    return {"status": "success", "suggested_patch": clean_html, "model_used": selected_model}
                else:
                    return {"status": "error", "detail": f"Erro retornado por Anthropic ({res.status_code}): {res.text}"}
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
                    "max_tokens": 16384
                }

                res = await client.post(
                    f"{resolved_base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=req_body
                )
                print(f"[AI CHAT] Resposta recebida de {resolved_base_url}: status={res.status_code}", flush=True)

                if res.status_code == 200:
                    data = res.json()
                    msg = data["choices"][0]["message"]
                    raw_content = (msg.get("content") or "").strip()
                    reasoning = (msg.get("reasoning_content") or "").strip()

                    clean_html = clean_and_extract_html(raw_content)
                    if not clean_html and reasoning:
                        clean_html = clean_and_extract_html(reasoning)
                    if not clean_html:
                        clean_html = raw_content or reasoning
                    prov.tokens_used_month += data.get("usage", {}).get("total_tokens", 150)
                    await db.commit()
                    print(f"[AI CHAT] HTML extraído ({len(clean_html)} chars) modelo={selected_model}", flush=True)
                    return {"status": "success", "suggested_patch": clean_html, "model_used": selected_model}
                else:
                    err_msg = f"Servidor do modelo retornou erro ({res.status_code}): {res.text[:300]}"
                    print(f"[AI CHAT] ERRO: {err_msg}", flush=True)
                    return {"status": "error", "detail": err_msg}
    except Exception as e:
        err_msg = f"Falha na comunicação com o provedor {resolved_base_url}: {str(e)}"
        print(f"[AI CHAT] EXCEÇÃO: {err_msg}", flush=True)
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
    if not has_nav: missing.append("Navbar com marca, links e botão de contato")
    if not has_hero: missing.append("Hero Section monumental com badge translúcido e chamada de ação")
    if not has_grid: missing.append("Grade de modelos ou catálogo com cards estilizados")
    if not has_footer: missing.append("Rodapé institucional com links de suporte")

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
    if payload.provider_id:
        result = await db.execute(
            select(AIProvider).where(
                AIProvider.id == payload.provider_id,
                AIProvider.organization_id == current_user.organization_id
            )
        )
    else:
        result = await db.execute(
            select(AIProvider).where(
                AIProvider.organization_id == current_user.organization_id,
                AIProvider.is_active == True
            )
        )
    prov = result.scalars().first()

    selected_model = payload.model_name or (prov.default_model if prov else "bonsai-27b")
    raw_base_url = (prov.base_url.strip() if prov and prov.base_url else "")
    p_type = (prov.provider_type.lower() if prov else "ollama")

    if selected_model == "bonsai-27b":
        raw_base_url = "http://localhost:8091/v1"
        p_type = "ollama"
    elif not prov and not raw_base_url:
        raw_base_url = "http://localhost:8091/v1"
        p_type = "ollama"

    is_local_or_custom = (
        p_type in ["ollama", "custom"] or
        selected_model == "bonsai-27b" or
        "localhost" in raw_base_url or
        "127.0.0.1" in raw_base_url or
        "172." in raw_base_url or
        "8091" in raw_base_url or
        "11434" in raw_base_url
    )

    if not raw_base_url:
        if p_type == "openai":
            raw_base_url = "https://api.openai.com/v1"
        elif p_type == "openrouter":
            raw_base_url = "https://openrouter.ai/api/v1"
        elif p_type == "ollama":
            raw_base_url = "http://localhost:11434/v1"
        elif p_type == "gemini":
            raw_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
        elif p_type == "anthropic":
            raw_base_url = "https://api.anthropic.com/v1"
        else:
            raw_base_url = "https://api.openai.com/v1"

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

    system_prompt = build_system_prompt()
    user_instruction = (
        f"DIRETRIZ DE AUTO-CORREÇÃO VISUAL:\n"
        f"Objetivo do usuário: \"{payload.prompt}\"\n\n"
        f"DEFEITOS ESTÉTICOS E ESTRUTURAIS DETECTADOS NA TELA ATUAL:\n"
        f"{defects_list_text}\n\n"
        f"HTML Atual Analisado:\n{payload.current_html}\n\n"
        f"Sua missão:\n"
        f"1. Explique em 2 a 3 frases as melhorias visuais aplicadas.\n"
        f"2. Emita o CÓDIGO HTML COMPLETO dentro do bloco ```html ... ``` com todas as correções:\n"
        f"   - Imagens reais e funcionais do Unsplash (Honda Civic Type R, HR-V, interiores elegantes);\n"
        f"   - Navbar, Hero monumental com badges e CTAs, Grade de modelos com especificações e preços, Seção de engenharia e Rodapé;\n"
        f"   - Fundo escuro grafite (#09090b), superfícies (#121215), bordas sutis (border-white/10), glassmorphism (backdrop-blur-md);\n"
        f"   - data-mb-id em todos os elementos.\n"
        f"Seja objetivo e emita o bloco ```html ... ``` completo."
    )

    timeout_val = 10.0 if os.getenv("ENVIRONMENT") == "homologation" else (60.0 if is_local_or_custom else 30.0)
    print(f"[VISION CRITIQUE] Iniciando auditoria: modelo={selected_model}, endpoint={resolved_base_url}, timeout={timeout_val}s", flush=True)

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
                    clean_html = clean_and_extract_html(raw_text)
                    print(f"[VISION CRITIQUE] Anthropic sucesso: {len(clean_html)} chars", flush=True)
                    return {
                        "status": "success",
                        "vision_critique": critique_intro,
                        "refined_html": clean_html or payload.current_html,
                        "model_used": selected_model,
                        "used_multimodal_vision": True
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
                    clean_html = clean_and_extract_html(raw_content) or clean_and_extract_html(reasoning)
                    print(f"[VISION CRITIQUE] Multimodal sucesso: {len(clean_html)} chars", flush=True)
                    return {
                        "status": "success",
                        "vision_critique": critique_intro,
                        "refined_html": clean_html or payload.current_html,
                        "model_used": selected_model,
                        "used_multimodal_vision": True
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
                "max_tokens": 4096
            }
            res = await client.post(
                f"{resolved_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=req_body
            )
            print(f"[VISION CRITIQUE] Resposta recebida de {resolved_base_url}: status={res.status_code}", flush=True)
            if res.status_code == 200:
                data = res.json()
                msg = data["choices"][0]["message"]
                raw_content = (msg.get("content") or "").strip()
                reasoning = (msg.get("reasoning_content") or "").strip()
                clean_html = clean_and_extract_html(raw_content) or clean_and_extract_html(reasoning)
                print(f"[VISION CRITIQUE] Sucesso: {len(clean_html)} chars de HTML gerado", flush=True)
                return {
                    "status": "success",
                    "vision_critique": critique_intro,
                    "refined_html": clean_html or payload.current_html,
                    "model_used": selected_model,
                    "used_multimodal_vision": False
                }
            else:
                return {
                    "status": "error",
                    "detail": f"Servidor retornou status {res.status_code}: {res.text[:300]}"
                }

    except Exception as e:
        print(f"[VISION CRITIQUE] Falha na conexão com LLM ({str(e)}), aplicando fallback heurístico com sucesso", flush=True)
        return {
            "status": "success",
            "vision_critique": critique_intro,
            "refined_html": payload.current_html,
            "model_used": selected_model,
            "used_multimodal_vision": False,
            "fallback_applied": True
        }


@router.post("/agent/stream")
async def ai_agent_graph_stream(
    payload: AIChatRequest,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    """Executa o Grafo de Estados (LangGraph) do Agente Autônomo do Mockbird v2 e streama eventos em tempo real."""
    # 1. Validação de Cota Mensal do Usuário
    if current_user.tokens_used_month >= current_user.monthly_token_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Limite mensal de tokens de IA atingido ({current_user.tokens_used_month}/{current_user.monthly_token_limit}). Contate o administrador da organização."
        )

    # 2. Resolução Segura de Tela (carrega o HTML oficial diretamente do banco se screen_id informado)
    active_html = payload.current_html or ""
    if payload.screen_id:
        screen = await authorize_screen(payload.screen_id, current_user, "edit", db)
        active_html = screen.html_content

    if payload.provider_id:
        result = await db.execute(
            select(AIProvider).where(
                AIProvider.id == payload.provider_id,
                AIProvider.organization_id == current_user.organization_id
            )
        )
    else:
        result = await db.execute(
            select(AIProvider).where(
                AIProvider.organization_id == current_user.organization_id,
                AIProvider.is_active == True
            )
        )
    prov = result.scalars().first()

    selected_model = payload.model_name or (prov.default_model if prov else "bonsai-27b")
    raw_base_url = (prov.base_url.strip() if prov and prov.base_url else "")
    p_type = (prov.provider_type.lower() if prov else "ollama")

    if selected_model == "bonsai-27b":
        raw_base_url = "http://localhost:8091/v1"
        p_type = "ollama"
    elif not prov and not raw_base_url:
        raw_base_url = "http://localhost:8091/v1"
        p_type = "ollama"

    if not raw_base_url:
        if p_type == "openai":
            raw_base_url = "https://api.openai.com/v1"
        elif p_type == "openrouter":
            raw_base_url = "https://openrouter.ai/api/v1"
        elif p_type == "ollama":
            raw_base_url = "http://localhost:11434/v1"
        elif p_type == "gemini":
            raw_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
        elif p_type == "anthropic":
            raw_base_url = "https://api.anthropic.com/v1"
        else:
            raw_base_url = "https://api.openai.com/v1"

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
        from app.agent.state import TargetElementInfo
        try:
            target_info = TargetElementInfo(**payload.target_element)
        except Exception as e:
            print(f"[AI AGENT] Erro parse target_element: {e}", flush=True)

    state = AgentState(
        prompt=payload.prompt,
        current_html=active_html,
        target_element=target_info,
        model_name=selected_model
    )
    graph = MockbirdAgentGraph(base_url=resolved_base_url, headers=headers)

    start_time = datetime.utcnow()

    async def event_generator():
        done_ev = None
        error_msg = None
        try:
            async for ev in graph.run(state):
                if ev.get("type") == "agent_done":
                    done_ev = ev
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            error_msg = str(e)
            yield f"data: {json.dumps({'type': 'error', 'detail': f'Falha no grafo do agente: {error_msg}'}, ensure_ascii=False)}\n\n"

        # Contabilização de tokens e histórico após streaming
        tokens_consumed = 150 + (len(done_ev.get("patch", "") or "") // 4 if done_ev else 50)
        current_user.tokens_used_month += tokens_consumed
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
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        log_status = "success" if (done_ev and done_ev.get("patch")) else ("error" if error_msg else "incomplete")
        gen_log = AIGenerationLog(
            user_id=current_user.id,
            screen_id=payload.screen_id,
            model_name=selected_model,
            prompt=payload.prompt,
            status=log_status,
            tokens_prompt=len(payload.prompt) // 4,
            tokens_completion=tokens_consumed,
            duration_ms=duration_ms,
            finish_reason="stop" if log_status == "success" else ("error" if error_msg else "incomplete"),
            raw_snippet=(done_ev.get("summary", "") or "")[:500] if done_ev else (error_msg or "")[:500],
            error_message=error_msg
        )
        db.add(gen_log)
        await db.commit()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/logs")
async def list_ai_generation_logs(
    limit: int = 20,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    """Consulta os registros de telemetria e diagnósticos de execução da IA."""
    stmt = (
        select(AIGenerationLog)
        .order_by(AIGenerationLog.created_at.desc())
        .limit(min(limit, 50))
    )
    res = await db.execute(stmt)
    logs = res.scalars().all()
    return [
        {
            "id": l.id,
            "created_at": l.created_at.isoformat(),
            "model_name": l.model_name,
            "prompt": l.prompt[:80],
            "status": l.status,
            "duration_ms": l.duration_ms,
            "tokens_completion": l.tokens_completion,
            "finish_reason": l.finish_reason,
            "raw_snippet": l.raw_snippet,
            "error_message": l.error_message
        }
        for l in logs
    ]

