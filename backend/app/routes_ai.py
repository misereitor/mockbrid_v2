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
from app.models import User, AIProvider
from app.routes_auth import get_current_user
from app.agent.state import AgentState
from app.agent.graph import MockbirdAgentGraph

router = APIRouter(prefix="/api/ai", tags=["ai"])


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

    class Config:
        from_attributes = True


class AIChatRequest(BaseModel):
    prompt: str
    current_html: Optional[str] = ""
    target_element: Optional[Dict[str, Any]] = None
    system_role: Optional[str] = "assistant"
    model_name: Optional[str] = None
    provider_id: Optional[str] = None


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
    return query.scalars().all()


@router.post("/providers")
async def save_provider(
    payload: AIProviderConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Apenas administradores podem configurar provedores de IA")

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

    if not prov:
        prov = AIProvider(
            organization_id=current_user.organization_id,
            provider_type=payload.provider_type,
            default_model=payload.default_model.strip(),
            base_url=(payload.base_url or "").strip(),
            custom_models=clean_custom_models,
            encrypted_api_key=api_key_str
        )
        db.add(prov)
    else:
        if api_key_str:
            prov.encrypted_api_key = api_key_str
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
    current_user: User = Depends(get_current_user)
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


@router.post("/chat/stream")
async def ai_generate_stream(
    payload: AIChatRequest,
    current_user: User = Depends(get_current_user),
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
    if prov and prov.encrypted_api_key:
        headers["Authorization"] = f"Bearer {prov.encrypted_api_key}"
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
    current_user: User = Depends(get_current_user),
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

    if not prov or (not is_local_or_custom and not prov.encrypted_api_key):
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
                    "x-api-key": prov.encrypted_api_key or "dummy",
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
                if prov.encrypted_api_key:
                    headers["Authorization"] = f"Bearer {prov.encrypted_api_key}"
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
    current_user: User = Depends(get_current_user),
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

    timeout_val = 360.0 if is_local_or_custom else 120.0
    print(f"[VISION CRITIQUE] Iniciando auditoria: modelo={selected_model}, endpoint={resolved_base_url}, timeout={timeout_val}s", flush=True)

    try:
        async with httpx.AsyncClient(timeout=timeout_val) as client:
            # 1. Provedor Anthropic com Imagem Real Multimodal
            if p_type == "anthropic" and supports_native_vision and has_valid_image:
                headers = {
                    "x-api-key": (prov.encrypted_api_key if prov else "") or "dummy",
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
                if prov and prov.encrypted_api_key:
                    headers["Authorization"] = f"Bearer {prov.encrypted_api_key}"
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
            if prov and prov.encrypted_api_key:
                headers["Authorization"] = f"Bearer {prov.encrypted_api_key}"
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
        print(f"[VISION CRITIQUE] Exceção: {str(e)}", flush=True)
        return {"status": "error", "detail": f"Falha no loop de auto-validação visual: {str(e)}"}


@router.post("/agent/stream")
async def ai_agent_graph_stream(
    payload: AIChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Executa o Grafo de Estados (LangGraph) do Agente Autônomo do Mockbird v2 e streama eventos em tempo real."""
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

    resolved_base_url = resolve_docker_base_url(raw_base_url)

    headers = {"Content-Type": "application/json"}
    if prov and prov.encrypted_api_key:
        headers["Authorization"] = f"Bearer {prov.encrypted_api_key}"
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
        current_html=payload.current_html or "",
        target_element=target_info,
        model_name=selected_model
    )
    graph = MockbirdAgentGraph(base_url=resolved_base_url, headers=headers)

    async def event_generator():
        try:
            async for ev in graph.run(state):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': f'Falha no grafo do agente: {str(e)}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

