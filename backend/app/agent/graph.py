"""Grafo do agente de UI.

Correções importantes em relação à versão anterior:

* Nenhum HTML fictício é inventado quando a LLM falha — o erro real é propagado.
* Os timeouts vêm de `settings` (antes eram 6s em homologação, insuficientes para
  um modelo local).
* A geração de tela completa é feita **por seção**: cada chamada é menor, é
  validada isoladamente e pode ser refeita sem descartar o restante.
* Todo patch passa por `htmlkit.validate_and_repair`; se o validador reprovar, o
  agente pede uma correção ao modelo com a lista de defeitos (máx. 2 tentativas).
"""

import asyncio
import json
import re
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from app.config import settings
from app.agent.state import AgentState, PlanStep, ToolCallRecord, TargetElementInfo
from app.agent.tools import (
    extract_dom_structure,
    extract_element_snippet,
    diagnose_layout_issues,
    verify_ui_quality,
)
from app.agent.htmlkit import (
    PatchValidation,
    assemble_sections,
    extract_html,
    rebuild_html,
    strip_thinking,
    validate_and_repair,
    validate_section,
)


def balance_html_tags(html: str) -> str:
    rebuilt, _, _ = rebuild_html(html or "")
    return rebuilt


def heal_and_wrap_html(raw_html: str) -> str:
    validation = validate_and_repair(raw_html or "", mode="full")
    return validation.html


def clean_extracted_html(text: str, is_full_page: bool = True) -> str:
    extracted = extract_html(text)
    if not extracted:
        return ""
    return heal_and_wrap_html(extracted) if is_full_page else balance_html_tags(extracted)


PLANNER_FALLBACK = [
    PlanStep(id=1, title="Estrutura & Navegação Principal", description="Cabeçalho contextual, navegação ou barra de comando adaptada ao tipo de interface"),
    PlanStep(id=2, title="Área Principal & Componentes Core", description="Visão central da interface com os componentes, dados ou fluxos específicos solicitados"),
    PlanStep(id=3, title="Painéis Complementares & Ações", description="Seções secundárias, detalhamento, interações ou fechamento contextual da tela"),
]

DESIGN_SYSTEM = (
    "DIRETRIZES DE ARQUITETURA E DESIGN ADAPTATIVO (obrigatório):\n"
    "1. PROIBIDO USAR LAYOUT PADRÃO REPETITIVO: Adapte 100% da arquitetura estrutural, paleta de cores (tema claro, escuro, vibrante, pastel, editorial ou corporativo), densidade e tipografia ao domínio e ao pedido específico do usuário.\n"
    "2. ARQUITETURA POR TIPO DE TELA:\n"
    "   - Se for Dashboard / SaaS / App / CRM / Kanban / Chat: use layout de aplicação (ex: sidebar + área operacional, split-view, colunas de kanban, tabelas densas, filtros e painéis). NÃO coloque Hero de marketing nem rodapé institucional de landing page em telas de aplicativo.\n"
    "   - Se for Login / Cadastro / Checkout / Onboarding: use layout focado em fluxo (ex: split-screen 50/50, card centralizado minimalista ou wizard passo a passo).\n"
    "   - Se for Landing Page / E-commerce / Portfólio / Institucional: crie composições autênticas e variadas (ex: bento grid assimétrico, editorial magazine, showcase interativo, split hero ou vitrine limpa) com paleta condizente com o nicho.\n"
    "3. REGRAS TÉCNICAS DO CANVAS:\n"
    "   - Use SOMENTE classes utilitárias do Tailwind CSS (o CDN já está ativo). É PROIBIDO <style>, <script>, <html>, <head> ou <body>.\n"
    "   - Não use Lorem ipsum, placeholders cinzas nem comentários de TODO.\n"
    "   - Quando usar fotografias ou avatares, use <img> com URLs reais do Unsplash contextualizadas ao tema (auto=format&fit=crop&w=1200&q=80).\n"
    "   - Todo container, card, botão, link, imagem e título precisa de data-mb-id único e descritivo.\n"
    "4. INTERATIVIDADE & NAVEGAÇÃO MOCKBIRD:\n"
    "   - Links e botões de fluxo entre telas devem ter data-go='<NomeOuSlug>' ou href='#/<nome>'.\n"
    "   - TODO botão, CTA e item de menu DEVE funcionar: para rolar na mesma página use <a href='#id-da-secao'> e garanta que exista uma <section id='id-da-secao'> correspondente; para trocar de tela use data-go; para abrir modal use data-overlay; para feedback use data-toast='<mensagem>'. Nunca deixe botão ou link sem destino (href vazio, '#' solto ou <button> sem ação).\n"
    "   - Modais devem ter id único e botões de abertura devem ter data-overlay='#<id>'. Botões de fechar devem ter data-close.\n"
    "   - Dados dinâmicos devem ter data-mock='<chave>' e listas com data-mock-list='<itens>'."
)


def _normalize_html(html: str) -> str:
    """Compara HTML ignorando espaços, aspas, atributos de auto-cura e diferenças de envelope do documento."""
    body = re.sub(r"<!DOCTYPE[\s\S]*?<body[^>]*>|</body>[\s\S]*$", "", html or "", flags=re.IGNORECASE)
    body = re.sub(r'\s*data-toast\s*=\s*(["\']).*?\1', '', body, flags=re.IGNORECASE)
    return re.sub(r"[\s\"']+", "", body).lower()


def extract_screen_semantics(html: str) -> Dict[str, Any]:
    """Extrai raio-X semântico da tela atual (títulos, seções, tema e propósito)."""
    if not html or len(html) < 60:
        return {"has_content": False, "summary": "Tela vazia ou em branco."}
    if "Bem-vindo ao Mockbird v2" in html or 'data-mb-id="root-hero"' in html:
        return {"has_content": False, "summary": "Tela inicial placeholder do Mockbird v2."}

    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    h2s = re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.IGNORECASE | re.DOTALL)
    clean_h1s = [re.sub(r"<[^>]+>", "", h).strip() for h in h1s if h.strip()][:3]
    clean_h2s = [re.sub(r"<[^>]+>", "", h).strip() for h in h2s if h.strip()][:5]

    sections = re.findall(r'<(?:section|header|main|footer|aside)\b[^>]*data-mb-id="([^"]+)"', html, re.IGNORECASE)
    if not sections:
        sections = re.findall(r'data-mb-id="([^"]+)"', html)[:6]

    theme = "dark" if 'class="dark"' in html or "bg-slate-950" in html or "bg-[#09090b]" in html else "light"

    summary_parts = []
    if clean_h1s:
        summary_parts.append(f"Produto/Tema principal: {', '.join(clean_h1s)}")
    if clean_h2s:
        summary_parts.append(f"Subtítulos/Recursos: {', '.join(clean_h2s)}")
    if sections:
        summary_parts.append(f"Seções existentes: {', '.join(sections[:5])}")
    summary_parts.append(f"Tema visual: {theme}")

    return {
        "has_content": True,
        "title": clean_h1s[0] if clean_h1s else "Interface ativa",
        "sections": sections,
        "summary": " | ".join(summary_parts),
    }


def format_chat_history(messages: List[Dict[str, Any]]) -> str:
    """Formata os turnos recentes do diálogo sem estourar limites de tokens."""
    if not messages:
        return ""
    lines = ["HISTÓRICO RECENTE DA CONVERSA NESTE PROJETO:"]
    for m in messages[-8:]:
        role = "Usuário" if m.get("role") == "user" else "Assistente"
        content = str(m.get("content") or "").strip()
        if len(content) > 350:
            content = content[:350] + "..."
        if content:
            lines.append(f"- {role}: {content}")
    return "\n".join(lines) + "\n\n"


def locate_surgical_target(html: str, prompt: str) -> Optional[TargetElementInfo]:
    """Localiza automaticamente o elemento alvo no HTML quando o usuário pede alteração pontual sem ter clicado nele."""
    if not html or len(html) < 60:
        return None
    p_lower = prompt.lower().strip()

    # 1. Botão / CTA
    btn_triggers = [
        "cor do botão", "cor do botao", "mude o botão", "mude o botao", "troque o botão", "troque o botao",
        "altere o botão", "altere o botao", "texto do botão", "texto do botao", "botão vermelho", "botao vermelho",
        "botão verde", "botao verde", "botão azul", "botao azul", "mude o cta", "troque o cta"
    ]
    if any(t in p_lower for t in btn_triggers):
        buttons = re.findall(
            r"""(<button\b[^>]*data-mb-id\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)</button>)""",
            html,
            re.IGNORECASE,
        )
        if buttons:
            for full_tag, mb_id, inner in buttons:
                clean_inner = re.sub(r"<[^>]+>", "", inner).lower().strip()
                words = [w for w in clean_inner.split() if len(w) > 3]
                if any(w in p_lower for w in words):
                    return TargetElementInfo(
                        mbId=mb_id,
                        tag="button",
                        selector=f"#{mb_id}",
                        snippet=clean_inner[:60],
                        outerHtml=full_tag,
                    )
            full_tag, mb_id, inner = buttons[0]
            clean_inner = re.sub(r"<[^>]+>", "", inner).strip()
            return TargetElementInfo(
                mbId=mb_id,
                tag="button",
                selector=f"#{mb_id}",
                snippet=clean_inner[:60],
                outerHtml=full_tag,
            )

    # 2. Título Principal (H1)
    title_triggers = [
        "mude o título", "mude o titulo", "troque o título", "troque o titulo",
        "altere o título", "altere o titulo", "mude o h1", "troque o h1",
        "título principal", "titulo principal"
    ]
    if any(t in p_lower for t in title_triggers):
        h1_match = re.search(
            r"""(<h1\b[^>]*data-mb-id\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)</h1>)""",
            html,
            re.IGNORECASE,
        )
        if h1_match:
            full_tag, mb_id, inner = h1_match.group(1), h1_match.group(2), h1_match.group(3)
            clean_inner = re.sub(r"<[^>]+>", "", inner).strip()
            return TargetElementInfo(
                mbId=mb_id,
                tag="h1",
                selector=f"#{mb_id}",
                snippet=clean_inner[:60],
                outerHtml=full_tag,
            )

    # 3. Subtítulo (H2)
    sub_triggers = ["mude o subtítulo", "mude o subtitulo", "troque o subtítulo", "troque o subtitulo", "mude o h2"]
    if any(t in p_lower for t in sub_triggers):
        h2_match = re.search(
            r"""(<h2\b[^>]*data-mb-id\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)</h2>)""",
            html,
            re.IGNORECASE,
        )
        if h2_match:
            full_tag, mb_id, inner = h2_match.group(1), h2_match.group(2), h2_match.group(3)
            clean_inner = re.sub(r"<[^>]+>", "", inner).strip()
            return TargetElementInfo(
                mbId=mb_id,
                tag="h2",
                selector=f"#{mb_id}",
                snippet=clean_inner[:60],
                outerHtml=full_tag,
            )

    # 4. Navbar / Header
    nav_triggers = ["mude o navbar", "troque o navbar", "mude o cabeçalho", "troque o cabeçalho", "mude o header"]
    if any(t in p_lower for t in nav_triggers):
        nav_match = re.search(
            r"""(<(?:header|nav)\b[^>]*data-mb-id\s*=\s*["']([^"']+)["'][^>]*>[\s\S]*?</(?:header|nav)>)""",
            html,
            re.IGNORECASE,
        )
        if nav_match:
            full_tag, mb_id = nav_match.group(1), nav_match.group(2)
            tag_name = "header" if "<header" in full_tag.lower() else "nav"
            return TargetElementInfo(
                mbId=mb_id,
                tag=tag_name,
                selector=f"#{mb_id}",
                snippet="Navegação / Cabeçalho",
                outerHtml=full_tag[:2000],
            )

    # 5. Footer / Rodapé
    footer_triggers = ["mude o rodapé", "mude o rodape", "troque o rodapé", "troque o rodape", "mude o footer"]
    if any(t in p_lower for t in footer_triggers):
        foot_match = re.search(
            r"""(<footer\b[^>]*data-mb-id\s*=\s*["']([^"']+)["'][^>]*>[\s\S]*?</footer>)""",
            html,
            re.IGNORECASE,
        )
        if foot_match:
            full_tag, mb_id = foot_match.group(1), foot_match.group(2)
            return TargetElementInfo(
                mbId=mb_id,
                tag="footer",
                selector=f"#{mb_id}",
                snippet="Rodapé da página",
                outerHtml=full_tag[:2000],
            )

    return None


class _LLMError(RuntimeError):
    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class MockbirdAgentGraph:
    """Grafo de execução autônoma com decisão de intenção, ferramentas e validação."""

    def __init__(
        self,
        base_url: str,
        headers: Dict[str, str],
        transport: Optional[httpx.AsyncBaseTransport] = None,
        disable_thinking: bool = False,
    ):
        from app.ai_providers import is_local_endpoint

        self.base_url = base_url
        self.headers = headers
        self.transport = transport
        # Modelos de raciocínio (Qwen3/bonsai) gastam todo o `max_tokens` pensando
        # antes de emitir o primeiro caractere de HTML. Em endpoints locais
        # desligamos o thinking via chat template quando o servidor suportar.
        self.disable_thinking = (
            disable_thinking
            and bool(getattr(settings, "AI_DISABLE_THINKING", True))
            and is_local_endpoint(base_url)
        )
        self.read_timeout = float(getattr(settings, "AI_LLM_READ_TIMEOUT", 600.0))
        self.connect_timeout = float(getattr(settings, "AI_LLM_CONNECT_TIMEOUT", 10.0))
        self.max_tokens = int(getattr(settings, "AI_LLM_MAX_TOKENS", 8192))
        self.section_max_tokens = int(getattr(settings, "AI_SECTION_MAX_TOKENS", 2600))
        self.max_attempts = max(1, int(getattr(settings, "AI_LLM_MAX_ATTEMPTS", 2)))
        self.max_repairs = max(0, int(getattr(settings, "AI_AGENT_MAX_REPAIRS", 1)))
        self.dynamic_enabled = bool(getattr(settings, "AI_AGENT_DYNAMIC", True))
        self.max_iterations = max(1, int(getattr(settings, "AI_AGENT_MAX_ITERATIONS", 10)))

    # ------------------------------------------------------------------
    # Camada de transporte / streaming
    # ------------------------------------------------------------------
    def _client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            self.read_timeout,
            connect=self.connect_timeout,
            write=60.0,
            pool=self.connect_timeout,
        )
        kwargs: Dict[str, Any] = {"timeout": timeout}
        if self.transport is not None:
            kwargs["transport"] = self.transport
        return httpx.AsyncClient(**kwargs)

    async def _stream_once(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        req_messages: List[Dict[str, Any]] = []
        img_url = getattr(self, "image_url", None)
        for idx, m in enumerate(messages):
            if idx == len(messages) - 1 and m.get("role") == "user" and img_url and isinstance(m.get("content"), str):
                req_messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": m["content"]},
                        {"type": "image_url", "image_url": {"url": img_url if img_url.startswith("data:") else f"data:image/png;base64,{img_url}"}},
                    ],
                })
            else:
                req_messages.append(m)

        body: Dict[str, Any] = {
            "model": model,
            "messages": req_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if self.disable_thinking:
            # llamacpp/Qwen3: desativa o bloco de raciocínio no template de chat.
            body["chat_template_kwargs"] = {"enable_thinking": False}
        async with self._client() as client:
            async with client.stream(
                "POST",
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers=self.headers,
                json=body,
            ) as response:
                if response.status_code != 200:
                    raw = (await response.aread()).decode(errors="replace")
                    retryable = response.status_code in (408, 409, 425, 429) or response.status_code >= 500
                    hint = ""
                    if response.status_code == 401:
                        hint = " Verifique a chave de API do provedor em Configurações → LLM."
                    elif response.status_code == 404:
                        hint = " Verifique a URL base e o nome do modelo configurado."
                    raise _LLMError(
                        f"Provedor retornou {response.status_code}: {raw[:300]}{hint}",
                        retryable=retryable,
                    )

                accumulated_content: List[str] = []
                accumulated_reasoning: List[str] = []
                finish_reason: Optional[str] = None
                total_chunks = 0

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str:
                        continue
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        choice = (chunk.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                        r_chunk = delta.get("reasoning_content") or delta.get("reasoning") or ""
                        c_chunk = delta.get("content") or ""
                        if r_chunk:
                            accumulated_reasoning.append(r_chunk)
                            total_chunks += 1
                            yield {"type": "thinking_chunk", "text": r_chunk}
                        if c_chunk:
                            accumulated_content.append(c_chunk)
                            total_chunks += 1
                            yield {"type": "content_chunk", "text": c_chunk}
                        if total_chunks and total_chunks % 20 == 0:
                            yield {
                                "type": "heartbeat",
                                "chars": sum(len(c) for c in accumulated_content),
                                "reasoning_chars": sum(len(r) for r in accumulated_reasoning),
                            }
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                        continue

                full_content = strip_thinking("".join(accumulated_content))
                full_reasoning = "".join(accumulated_reasoning)

                # Alguns modelos devolvem o HTML dentro do reasoning_content quando
                # não têm canal de conteúdo separado. Só aceitamos se houver bloco.
                if not extract_html(full_content) and "```" in full_reasoning:
                    salvaged = extract_html(full_reasoning)
                    if salvaged:
                        yield {"type": "node_progress", "chars": len(salvaged), "detail": "HTML recuperado do raciocínio do modelo."}
                        full_content = salvaged

                # Alguns modelos (ex.: DeepSeek R1) embrulham <think>...</think> no content.
                think_match = re.search(r"<think(?:ing)?>([\s\S]*?)</think(?:ing)?>", "".join(accumulated_content), re.IGNORECASE)
                if think_match:
                    full_reasoning += "\n" + think_match.group(1).strip()

                yield {
                    "type": "completed",
                    "content": full_content,
                    "reasoning": full_reasoning,
                    "finish_reason": finish_reason,
                }

    async def _call_llm_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.4,
        max_tokens: int = 8192,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Chama a LLM com streaming, tentativas limitadas e erro explícito."""
        last_error: Optional[str] = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                async for event in self._stream_once(messages, model, temperature, max_tokens):
                    if event["type"] == "completed":
                        yield event
                        return
                    yield event
                # Stream terminou sem evento 'completed' (improvável)
                last_error = "O provedor encerrou o stream sem conteúdo."
            except _LLMError as exc:
                last_error = str(exc)
                if not exc.retryable or attempt == self.max_attempts:
                    break
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = (
                    f"Tempo esgotado/queda de conexão com o provedor após {int(self.read_timeout)}s: {exc.__class__.__name__}"
                )
                if attempt == self.max_attempts:
                    break
            except Exception as exc:  # nunca deixamos o gerador morrer sem diagnóstico
                last_error = f"Falha inesperada na chamada da LLM: {exc}"
                break

            if attempt < self.max_attempts:
                yield {
                    "type": "node_progress",
                    "chars": 0,
                    "detail": f"Instabilidade no provedor; tentativa {attempt + 1} de {self.max_attempts}...",
                }
                await asyncio.sleep(1.5 * attempt)

        yield {"type": "error", "detail": last_error or "Falha desconhecida ao chamar a LLM."}

    async def _collect(
        self,
        messages: List[Dict[str, str]],
        out: Dict[str, Any],
        *,
        max_tokens: int,
        temperature: float,
        detail: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Executa a chamada emitindo progresso e preenche `out` com o resultado."""
        out["content"] = ""
        out["reasoning"] = ""
        out["finish_reason"] = None
        out["error"] = None

        async for event in self._call_llm_stream(messages, self.model, temperature, max_tokens):
            if event["type"] == "completed":
                out["content"] = event.get("content") or ""
                out["reasoning"] = event.get("reasoning") or ""
                out["finish_reason"] = event.get("finish_reason")
            elif event["type"] == "heartbeat":
                yield {
                    "type": "node_progress",
                    "chars": event.get("chars", 0),
                    "detail": f"{detail} ({event.get('chars', 0)} caracteres)",
                }
            elif event["type"] == "error":
                out["error"] = event.get("detail")
            elif event["type"] == "node_progress":
                yield event
            elif event["type"] == "content_chunk":
                # Mantém o streaming disponível para o painel; o conteúdo
                # completo continua sendo consolidado no evento completed.
                yield event
            elif event["type"] == "thinking_chunk":
                yield event

    async def _continue(
        self,
        messages: List[Dict[str, str]],
        partial: str,
        out: Dict[str, Any],
        **kwargs,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Pede a continuação exata de uma geração truncada por limite de tokens."""
        continued = dict(out)
        yield {
            "type": "node_progress",
            "chars": len(partial),
            "detail": "Resposta truncada pelo provedor; pedindo continuação...",
        }
        cont_messages = messages + [
            {"role": "assistant", "content": partial},
            {
                "role": "user",
                "content": (
                    "Continue EXATAMENTE de onde o HTML parou. Não repita o que já foi escrito, "
                    "não adicione explicações e feche todas as tags abertas."
                ),
            },
        ]
        async for event in self._collect(cont_messages, continued, **kwargs):
            yield event
        out["error"] = continued.get("error")
        out["finish_reason"] = continued.get("finish_reason")
        out["reasoning"] = (out.get("reasoning") or "") + (continued.get("reasoning") or "")
        out["content"] = partial + (continued.get("content") or "")

    # ------------------------------------------------------------------
    # Intenção
    # ------------------------------------------------------------------
    async def _run_dynamic(self, state: AgentState) -> AsyncGenerator[Dict[str, Any], None]:
        """Executa o agente como um loop de decisões, com fallback seguro e consciência de contexto."""
        yield {"type": "node_start", "node": "agent", "title": "Agente Autônomo", "detail": "Analisando histórico, tela na mesa e decidindo a próxima ação..."}
        has_target = bool(
            state.target_element
            and (state.target_element.mbId or state.target_element.selector or state.target_element.outerHtml)
        )
        if not has_target and state.current_html:
            inferred = locate_surgical_target(state.current_html, state.prompt)
            if inferred:
                state.target_element = inferred
                has_target = True
        semantics = extract_screen_semantics(state.current_html)
        state.screen_semantics = semantics
        history_text = format_chat_history(state.messages)

        is_existing_screen = semantics["has_content"]
        mesa_info = f"ESTADO DA MESA: {semantics['summary']}" if is_existing_screen else "ESTADO DA MESA: Tela inicial placeholder (iniciar do zero)."

        if has_target:
            actions_desc = "inspect_element, diagnose_layout, set_plan, generate_element_patch (edita o elemento selecionado), evolve_current_screen, finish."
        elif is_existing_screen:
            actions_desc = "get_dom_slice, diagnose_layout, set_plan, evolve_current_screen (turbina e evolui o produto/site atual na mesa sem perder o tema), generate_full_patch (recomeça do zero), finish."
        else:
            actions_desc = "get_dom_slice, diagnose_layout, set_plan, generate_full_patch (cria a página completa do zero), finish."

        system = (
            "Você é o Agente Autônomo Sênior de UI/UX do Mockbird v2.\n"
            "Trabalhe em turnos e escolha UMA ação por vez.\n"
            "Responda SOMENTE um JSON válido no formato {\"thought\":\"...\",\"action\":\"...\",\"args\":{}}.\n"
            f"Ações permitidas: {actions_desc}\n"
            "REGRA DE CONTEXTO: Se já existir uma interface na mesa, NUNCA perca o produto ou assunto original a menos que o usuário peça explicitamente para recomeçar outro projeto do zero."
        )
        context = (
            f"{history_text}"
            f"{mesa_info}\n"
            f"PEDIDO DO USUÁRIO: {state.prompt}\n"
            f"DOM ATUAL: {extract_dom_structure(state.current_html) if state.current_html else 'vazio'}"
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": context}]
        for iteration in range(self.max_iterations):
            out: Dict[str, Any] = {}
            async for event in self._collect(messages, out, max_tokens=700, temperature=0.2, detail="Pensando"):
                yield event
            if out.get("error"):
                state.error = out["error"]
                yield {"type": "error", "detail": out["error"]}
                return
            raw = (out.get("content") or "").strip()
            match = re.search(r"\{[\s\S]*\}", raw)
            decision: Optional[Dict[str, Any]] = None
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict) and isinstance(parsed.get("action"), str):
                        decision = parsed
                except (json.JSONDecodeError, TypeError):
                    decision = None
            if not decision:
                # Protocolo não suportado: preserva os fluxos testados e seguros.
                yield {"type": "node_progress", "chars": 0, "detail": "Modelo sem protocolo de ferramentas; usando fluxo compatível."}
                async for event in self._run_deterministic(state):
                    yield event
                return

            action = decision["action"]
            args = decision.get("args") or {}
            thought = str(decision.get("thought") or "")[:500]
            yield {"type": "node_progress", "chars": 0, "detail": thought or f"Executando {action}"}
            if action == "inspect_element":
                identifier = str(args.get("target") or args.get("mbId") or state.target_mb_id or "")
                result = extract_element_snippet(state.current_html, identifier) or "Elemento não localizado."
                summary = f"Elemento inspecionado ({len(result)} caracteres)."
                state.tools_history.append(ToolCallRecord(tool=action, args=args, result=summary, success=bool(result)))
                yield {"type": "tool_call", "tool": action, "summary": summary}
                yield {"type": "tool_result", "tool": action, "ok": bool(result), "summary": summary}
            elif action in ("get_dom_slice", "diagnose_layout"):
                result = extract_dom_structure(state.current_html) if action == "get_dom_slice" else diagnose_layout_issues(state.current_html)
                summary = f"{action}: {len(result)} item(ns)."
                state.tools_history.append(ToolCallRecord(tool=action, args=args, result=summary))
                yield {"type": "tool_call", "tool": action, "summary": summary}
                yield {"type": "tool_result", "tool": action, "ok": True, "summary": summary, "data": result}
            elif action == "set_plan":
                state.plan = [PlanStep(id=i + 1, title=str(item.get("title", f"Etapa {i + 1}")), description=str(item.get("description", ""))) for i, item in enumerate(args.get("steps", [])) if isinstance(item, dict)]
                if not state.plan:
                    state.plan = [step.model_copy() for step in PLANNER_FALLBACK]
                yield {"type": "plan_ready", "plan": [s.model_dump() for s in state.plan]}
                yield {"type": "plan", "plan": [s.model_dump() for s in state.plan]}
            elif action == "generate_element_patch":
                if not has_target:
                    # Sem elemento selecionado no canvas: se há tela na mesa evolui, senão cria
                    if is_existing_screen:
                        async for event in self._run_evolve_screen(state):
                            yield event
                    else:
                        async for event in self._run_full_page(state):
                            yield event
                    return
                async for event in self._run_surgical(state):
                    yield event
                return
            elif action in ("create_connected_screen", "connected_screen"):
                async for event in self._run_connected_screen(state):
                    yield event
                return
            elif action in ("evolve_current_screen", "evolve_screen"):
                async for event in self._run_evolve_screen(state):
                    yield event
                return
            elif action in ("generate_full_patch", "generate_section"):
                is_repair = any(kw in state.prompt.lower() for kw in ["consert", "quebrad", "arrum", "bug", "ajust", "alinh"])
                is_connected = is_existing_screen and any(kw in state.prompt.lower() for kw in ["tela de", "página de", "pagina de", "nova tela", "nova página", "nova pagina", "tela conectada", "fluxo de"]) and not any(kw in state.prompt.lower() for kw in ["esquece", "novo projeto", "outro site", "do zero"])
                if is_repair:
                    async for event in self._run_layout_repair(state):
                        yield event
                elif is_connected:
                    async for event in self._run_connected_screen(state):
                        yield event
                elif is_existing_screen and not any(kw in state.prompt.lower() for kw in ["esquece", "novo projeto", "outro site", "do zero"]):
                    # Se já há tela na mesa e o usuário pediu melhoria/ajuste geral, evolui sem apagar o tema
                    async for event in self._run_evolve_screen(state):
                        yield event
                else:
                    async for event in self._run_full_page(state):
                        yield event
                return
            elif action == "finish":
                state.is_complete = True
                state.final_summary = str(args.get("summary") or thought or "Execução concluída.")
                yield {"type": "agent_done", "patch": state.accumulated_patch, "patch_type": state.patch_type, "summary": state.final_summary, "reasoning": out.get("reasoning"), "plan": [s.model_dump() for s in state.plan]}
                return
            else:
                yield {"type": "tool_result", "tool": action, "ok": False, "summary": "Ferramenta desconhecida."}
            messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": "Continue com a próxima ação. Responda somente JSON."}]
        yield {"type": "error", "detail": "O agente atingiu o limite de iterações sem concluir."}

    async def _run_deterministic(self, state: AgentState) -> AsyncGenerator[Dict[str, Any], None]:
        intent = self._determine_intent(state)
        state.intent = intent
        if intent == "explanation":
            async for event in self._run_explanation(state):
                yield event
        elif intent == "surgical_edit":
            async for event in self._run_surgical(state):
                yield event
        elif intent == "layout_repair":
            async for event in self._run_layout_repair(state):
                yield event
        elif intent == "evolve_screen":
            async for event in self._run_evolve_screen(state):
                yield event
        elif intent == "connected_screen":
            async for event in self._run_connected_screen(state):
                yield event
        else:
            async for event in self._run_full_page(state):
                yield event

    def _determine_intent(self, state: AgentState) -> str:
        has_target = bool(
            state.target_element
            and (state.target_element.mbId or state.target_element.selector or state.target_element.outerHtml)
        )
        if not has_target and state.current_html:
            inferred = locate_surgical_target(state.current_html, state.prompt)
            if inferred:
                state.target_element = inferred
                has_target = True

        if has_target:
            return "surgical_edit"

        p_lower = state.prompt.lower().strip()

        explanation_keywords = [
            "o que você acha", "o que acha", "como funciona", "por que", "explique",
            "quais cores", "dúvida", "ajuda com conceito", "qual é a melhor", "me dê dicas",
            "dicas de design", "como posso melhorar",
        ]
        if any(kw in p_lower for kw in explanation_keywords) and not any(
            kw in p_lower for kw in ["consert", "mud", "cri", "alter", "melhor", "frac", "ruim", "ajust", "adicion"]
        ):
            return "explanation"

        repair_keywords = [
            "quebrado", "quebrada", "consertar", "concertar", "arrumar", "alinhar",
            "corrigir", "ajustar", "bug", "erro no layout", "layout tá", "layout ta",
        ]
        if any(kw in p_lower for kw in repair_keywords):
            return "layout_repair"

        # Consciência da mesa: verifica se já existe uma tela construída no canvas
        semantics = extract_screen_semantics(state.current_html)
        state.screen_semantics = semantics
        is_existing_screen = semantics["has_content"]

        if is_existing_screen:
            # Palavras explícitas que pedem para apagar e recomeçar outro projeto do zero
            new_project_keywords = [
                "esquece", "novo projeto", "outro projeto", "outra página", "outro site", "outro app",
                "crie do zero", "recomece", "limpe a tela", "nova tela do zero"
            ]
            if any(kw in p_lower for kw in new_project_keywords):
                return "full_page"

            connected_screen_keywords = [
                "tela de", "página de", "pagina de", "nova tela", "nova página", "nova pagina",
                "tela conectada", "fluxo de", "segunda tela", "tela seguinte", "tela para"
            ]
            if any(kw in p_lower for kw in connected_screen_keywords):
                return "connected_screen"

            # Se o usuário está criticando, pedindo vendas, melhorias ou mais seções: EVOLUI
            evolve_keywords = [
                "fraco", "fraca", "melhore", "melhorar", "mude", "mudar", "vender", "venda",
                "feio", "feia", "adicione", "adiciona", "coloque", "coloca", "mais moderno",
                "mais bonito", "aumente", "redesenhe", "refaça", "ajuste", "falta", "ruim",
                "não gostei", "nao gostei", "ficou", "está", "esta", "acrescente", "seção", "secao",
                "botão", "botao", "cta", "tabela", "preço", "preco", "cores", "copy", "conversão", "conversao"
            ]
            if any(kw in p_lower for kw in evolve_keywords):
                return "evolve_screen"

        full_keywords = [
            "crie", "cria", "criar", "gere", "gera", "gerar", "construa", "faça", "faca",
            "landing page", "landpage", "lp", "landing", "nova página", "nova tela", "novo layout",
            "site", "dashboard", "painel", "tela de", "página de", "sistema", "app", "aplicativo",
            "kanban", "login", "checkout", "e-commerce", "loja", "portfólio", "portfolio", "home",
        ]
        if any(kw in p_lower for kw in full_keywords):
            if is_existing_screen and ("seção" in p_lower or "secao" in p_lower or "bloco" in p_lower):
                return "evolve_screen"
            return "full_page"

        if is_existing_screen:
            return "evolve_screen"

        return "full_page"

    # ------------------------------------------------------------------
    # Execução
    # ------------------------------------------------------------------
    async def run(self, state: AgentState) -> AsyncGenerator[Dict[str, Any], None]:
        # O loop dinâmico também usa `_collect`, que precisa do modelo antes
        # de qualquer decisão ou fallback.
        self.model = state.model_name
        self.image_url = state.image_url
        if self.dynamic_enabled:
            async for event in self._run_dynamic(state):
                yield event
            return
        intent = self._determine_intent(state)
        state.intent = intent

        if intent == "explanation":
            async for event in self._run_explanation(state):
                yield event
            return
        if intent == "surgical_edit":
            async for event in self._run_surgical(state):
                yield event
            return
        if intent == "layout_repair":
            async for event in self._run_layout_repair(state):
                yield event
            return
        if intent == "evolve_screen":
            async for event in self._run_evolve_screen(state):
                yield event
            return
        if intent == "connected_screen":
            async for event in self._run_connected_screen(state):
                yield event
            return
        async for event in self._run_full_page(state):
            yield event

    # -- Fluxo 1: consultoria -------------------------------------------
    async def _run_explanation(self, state: AgentState) -> AsyncGenerator[Dict[str, Any], None]:
        yield {
            "type": "node_start",
            "node": "analyst",
            "title": "Analisando Pergunta e Estrutura",
            "detail": "Avaliando contexto de UI/UX e formulando resposta técnica em Português...",
        }

        dom_summary = extract_dom_structure(state.current_html) if state.current_html else "Tela em branco."
        state.dom_summary = dom_summary

        prompt = (
            "Você é o Especialista Sênior de UI/UX e Frontend do Mockbird v2.\n"
            "Responda à pergunta do usuário de forma clara, prestativa e técnica em Português do Brasil.\n"
            "NÃO gere blocos de código completos a menos que o usuário peça exemplos curtos.\n\n"
            f"PERGUNTA DO USUÁRIO: {state.prompt}\n"
            f"DOM ATUAL DA TELA:\n{dom_summary}\n"
        )

        out: Dict[str, Any] = {}
        async for event in self._collect(
            [{"role": "user", "content": prompt}],
            out,
            max_tokens=1200,
            temperature=0.4,
            detail="Redigindo análise",
        ):
            yield event

        if out["error"]:
            state.error = out["error"]
            yield {"type": "error", "detail": out["error"]}
            return

        state.is_complete = True
        state.final_summary = (out["content"] or "").strip() or "Não foi possível produzir a análise solicitada."
        state.reasoning = out["reasoning"]
        state.accumulated_patch = None
        state.patch_type = "none"

        yield {
            "type": "agent_done",
            "patch": None,
            "patch_type": "none",
            "summary": state.final_summary,
            "reasoning": state.reasoning,
            "plan": [],
            "audit": None,
        }

    # -- Fluxo 2: edição cirúrgica --------------------------------------
    async def _run_surgical(self, state: AgentState) -> AsyncGenerator[Dict[str, Any], None]:
        target = state.target_element
        if not target or not (target.mbId or target.selector or target.outerHtml):
            # Se não há elemento alvo selecionado, executa como página completa com segurança
            async for event in self._run_full_page(state):
                yield event
            return

        target_mb_id = target.mbId if target else None
        target_tag = target.tag if target else "elemento"
        target_selector = target.selector if target else (f"#{target_mb_id}" if target_mb_id else "")

        target_snippet = target.outerHtml if (target and target.outerHtml) else ""
        if not target_snippet and target_mb_id and state.current_html:
            target_snippet = extract_element_snippet(state.current_html, target_mb_id) or ""

        yield {
            "type": "node_start",
            "node": "inspector",
            "title": f"Inspecionando Elemento Alvo <{target_tag}>",
            "detail": f"Analisando estrutura, classes CSS e contexto do seletor '{target_selector or target_mb_id}'...",
        }

        state.tools_history.append(ToolCallRecord(
            tool="inspect_element",
            args={"selector": target_selector, "mbId": target_mb_id},
            result=f"Elemento <{target_tag}> inspecionado com sucesso.",
        ))
        yield {
            "type": "tool_call",
            "tool": "inspect_element",
            "summary": f"Alvo <{target_tag}> localizado no DOM.",
        }

        yield {
            "type": "node_start",
            "node": "executor",
            "title": f"Gerando Modificação Cirúrgica de <{target_tag}>",
            "detail": "Alterando exclusivamente o componente solicitado sem tocar no restante da tela...",
        }

        proj_ctx = f"\n{state.project_context}\n" if state.project_context else ""
        base_prompt = (
            "Você é o Engenheiro Frontend do Mockbird v2 especializado em refatoração cirúrgica.\n"
            f"PEDIDO DO USUÁRIO: {state.prompt}\n\n"
            f"ELEMENTO ALVO: <{target_tag}>\n"
            f"IDENTIFICADOR data-mb-id: {target_mb_id or 'alvo'}\n"
            f"SELETOR: {target_selector}\n"
            f"CÓDIGO ATUAL DO ELEMENTO:\n{target_snippet or 'Elemento no Canvas'}\n\n"
            f"{proj_ctx}"
            "REGRAS ESTRITAS:\n"
            "0. Raciocínio curto (máx. 3 linhas) e código imediatamente dentro de ```html ... ```.\n"
            "1. Devolva UM único elemento HTML atualizado (o próprio elemento alvo), nada mais.\n"
            f"2. PRESERVE data-mb-id=\"{target_mb_id or 'alvo'}\" no elemento raiz.\n"
            "3. NUNCA devolva o documento inteiro nem <html>/<body>.\n"
            "4. Use Tailwind CSS; mantenha classes existentes que não conflitem com o pedido.\n"
            "5. Explique em 1 frase, em Português, o que mudou (fora do bloco de código)."
        )

        messages = [{"role": "user", "content": base_prompt}]
        validation: Optional[PatchValidation] = None
        out: Dict[str, Any] = {}
        attempts = self.max_repairs + 1

        for attempt in range(1, attempts + 1):
            async for event in self._collect(
                messages,
                out,
                max_tokens=min(self.max_tokens, 3072),
                temperature=0.3,
                detail="Gerando alteração do elemento",
            ):
                yield event

            if out["error"]:
                state.error = out["error"]
                yield {"type": "error", "detail": out["error"]}
                return

            validation = validate_and_repair(out["content"], mode="element", mb_id=target_mb_id)
            unchanged = bool(
                target_snippet
                and validation.html
                and _normalize_html(validation.html) == _normalize_html(target_snippet)
            )
            problem = None
            if not validation.ok:
                problem = "; ".join(validation.errors)
            elif unchanged:
                problem = "O elemento devolvido é idêntico ao atual (a alteração não foi aplicada)."

            yield {"type": "validation_result", "scope": "element", **validation.to_event()}

            if problem is None:
                break
            if attempt == attempts:
                state.error = f"Validação da edição falhou: {problem}"
                yield {
                    "type": "error",
                    "detail": (
                        f"A edição não pôde ser aplicada: {problem}. "
                        "Tente descrever a mudança com mais detalhes ou selecionar outro elemento."
                    ),
                }
                return

            yield {
                "type": "node_progress",
                "chars": len(validation.html or ""),
                "detail": f"Ajustando a edição ({problem[:120]}). Tentativa {attempt + 1}/{attempts}...",
            }
            messages = [
                {"role": "user", "content": base_prompt},
                {"role": "assistant", "content": "```html\n" + (out["content"] or "")[:6000] + "\n```"},
                {"role": "user", "content": validation.repair_prompt()},
            ]

        assert validation is not None
        if not validation.ok:
            yield {"type": "error", "detail": "Edição inválida após as tentativas de correção."}
            return

        state.accumulated_patch = validation.html
        state.patch_type = "element"
        state.target_selector = target_selector
        state.target_mb_id = target_mb_id
        state.reasoning = out["reasoning"]

        explanation = re.sub(r"```(?:html)?[\s\S]*?```", "", out["content"]).strip()
        state.final_summary = explanation or f"Elemento <{target_tag}> atualizado cirurgicamente com sucesso."
        state.is_complete = True

        yield {
            "type": "tool_call",
            "tool": "patch_element",
            "summary": f"Fragmento de <{target_tag}> validado ({validation.score}/100) e pronto para aplicação.",
        }
        yield {
            "type": "agent_done",
            "patch": state.accumulated_patch,
            "patch_type": "element",
            "target_selector": state.target_selector,
            "target_mb_id": state.target_mb_id,
            "target_tag": target_tag,
            "summary": state.final_summary,
            "reasoning": state.reasoning,
            "plan": [],
            "audit": {
                "passed": True,
                "score": validation.score,
                "issues": validation.errors,
                "suggestions": validation.warnings,
            },
        }

    # -- Fluxo 3: reparo de layout --------------------------------------
    async def _run_layout_repair(self, state: AgentState) -> AsyncGenerator[Dict[str, Any], None]:
        yield {
            "type": "node_start",
            "node": "inspector",
            "title": "Diagnosticando Quebras no Layout",
            "detail": "Inspecionando hierarquia DOM, tags desbalanceadas e regras de layout...",
        }

        dom_summary = extract_dom_structure(state.current_html)
        detected_issues = diagnose_layout_issues(state.current_html)
        state.dom_summary = dom_summary

        yield {
            "type": "tool_call",
            "tool": "get_canvas_dom",
            "summary": f"DOM inspecionado: {len(detected_issues)} anomalias estruturais detectadas.",
        }

        yield {
            "type": "node_start",
            "node": "executor",
            "title": "Corrigindo Estrutura e Estilos de Layout",
            "detail": "Ajustando containers, alinhamento e responsividade preservando o conteúdo original...",
        }

        issues_prompt = (
            "\n".join(f"- {iss}" for iss in detected_issues)
            if detected_issues
            else "- Layout visual desalinhado conforme apontado pelo usuário."
        )
        base_prompt = (
            "Você é o Especialista Frontend Sênior do Mockbird v2.\n"
            f"SOLICITAÇÃO DO USUÁRIO: {state.prompt}\n\n"
            f"DIAGNÓSTICO TÉCNICO INICIAL:\n{issues_prompt}\n\n"
            "HTML ATUAL (pode estar truncado/quebrado):\n"
            f"```html\n{state.current_html[:24000]}\n```\n\n"
            "INSTRUÇÕES CRUCIAIS:\n"
            "1. Corrija o layout (flex/grid, overflow, responsividade) e feche todas as tags.\n"
            "2. PRESERVE textos, imagens e o propósito da tela. NÃO substitua por um template genérico.\n"
            "3. Devolva o HTML COMPLETO corrigido dentro de ```html ... ``` (sem <html>/<body>).\n"
            "4. Preserve/crie data-mb-id nos elementos editáveis.\n"
            "5. Explique em uma frase, antes do código, o que foi corrigido."
        )

        messages = [{"role": "user", "content": base_prompt}]
        out: Dict[str, Any] = {}
        validation: Optional[PatchValidation] = None
        attempts = self.max_repairs + 1

        for attempt in range(1, attempts + 1):
            async for event in self._collect(
                messages,
                out,
                max_tokens=self.max_tokens,
                temperature=0.3,
                detail="Construindo correção de layout",
            ):
                yield event

            if out["error"]:
                state.error = out["error"]
                yield {"type": "error", "detail": out["error"]}
                return

            # O reparo pode atuar num snippet pequeno (ex.: dois cards); não
            # exigimos o mesmo volume de texto de uma página inteira.
            validation = validate_and_repair(
                out["content"], mode="full", min_chars=60, min_text_chars=3
            )
            identical = bool(
                state.current_html
                and validation.html
                and _normalize_html(validation.html) == _normalize_html(state.current_html)
            )
            problem = None
            if not validation.ok:
                problem = "; ".join(validation.errors[:4])
            elif identical:
                problem = "O HTML devolvido é idêntico ao atual (nada foi corrigido)."

            yield {"type": "validation_result", "scope": "full", **validation.to_event()}

            if problem is None:
                break
            if attempt == attempts:
                yield {
                    "type": "error",
                    "detail": (
                        f"A correção de layout não passou na validação: {problem}. "
                        "Selecione o elemento específico e peça a alteração por partes."
                    ),
                }
                return

            messages = [
                {"role": "user", "content": base_prompt},
                {"role": "assistant", "content": "```html\n" + (out["content"] or "")[:16000] + "\n```"},
                {"role": "user", "content": validation.repair_prompt()},
            ]

        assert validation is not None
        state.accumulated_patch = validation.html
        state.patch_type = "full"
        state.reasoning = out["reasoning"]
        explanation = re.sub(r"```(?:html)?[\s\S]*?```", "", out["content"]).strip()
        state.final_summary = explanation or "Layout corrigido: containers, alinhamento e tags ajustados."

        audit = verify_ui_quality(validation.html)
        if validation.errors:
            audit.passed = False
            audit.issues = list(audit.issues) + validation.errors
            audit.score = min(audit.score, validation.score)
        state.audit = audit
        yield {
            "type": "audit_result",
            "passed": audit.passed,
            "score": audit.score,
            "issues": audit.issues,
            "suggestions": audit.suggestions,
        }
        yield {
            "type": "agent_done",
            "patch": state.accumulated_patch,
            "patch_type": "full",
            "summary": state.final_summary,
            "reasoning": state.reasoning,
            "audit": audit.model_dump(),
            "plan": [],
        }

    # -- Fluxo 4: evolução e aprimoramento da tela na mesa ---------------
    async def _run_evolve_screen(self, state: AgentState) -> AsyncGenerator[Dict[str, Any], None]:
        yield {
            "type": "node_start",
            "node": "analyst",
            "title": "Analisando Tela na Mesa e Pedido de Evolução",
            "detail": "Inspecionando produto/tema atual para aprimorar copy, persuasão e design mantendo a essência...",
        }

        semantics = extract_screen_semantics(state.current_html)
        state.screen_semantics = semantics
        history_text = format_chat_history(state.messages)

        yield {
            "type": "tool_call",
            "tool": "inspect_screen_semantics",
            "summary": f"Contexto identificado na mesa: {semantics['summary']}",
        }

        yield {
            "type": "node_start",
            "node": "executor",
            "title": "Evoluindo e Turbinando a Interface",
            "detail": "Aprimorando seções existentes, persuasão de vendas e botões 100% funcionais...",
        }

        proj_ctx = f"\n{state.project_context}\n" if state.project_context else ""
        base_prompt = (
            "Você é o Diretor de Arte e Especialista Sênior em Conversão (CRO) e Frontend do Mockbird v2.\n"
            f"{history_text}"
            f"ESTADO ATUAL DA TELA NA MESA:\n{semantics['summary']}\n\n"
            f"HTML ATUAL DA TELA:\n```html\n{state.current_html[:28000]}\n```\n\n"
            f"CRÍTICA / PEDIDO DE EVOLUÇÃO DO USUÁRIO:\n{state.prompt}\n\n"
            f"{proj_ctx}"
            "DIRETRIZES FUNDAMENTAIS DE EVOLUÇÃO:\n"
            "1. PRESERVE O PRODUTO E TEMA: Se a tela atual é sobre a Honda Civic Type R (ou outro produto da mesa), MANTENHA o mesmo produto e identidade visual! NUNCA mude para outro assunto.\n"
            "2. ATENDA A CRÍTICA DO USUÁRIO: Se o usuário achou fraco para vender, torne a página altamente persuasiva! Adicione estatísticas de performance (potência, aceleração), tabela de versões/preços, comparativo, depoimentos/críticas de revistas especializadas, seções de pré-reserva/financiamento e formulário de agendamento de test-drive.\n"
            "3. BOTÕES 100% FUNCIONAIS: Todo botão ou link de CTA DEVE ter href com âncora correspondente (ex: <a href='#test-drive'>) e uma <section id='test-drive'> real, ou data-toast='<mensagem>'. NUNCA deixe botão morto.\n"
            "4. Raciocínio curto (máx. 2 linhas) e em seguida o bloco ```html ... ``` com o HTML COMPLETO da página enriquecida (sem <html>/<body>).\n"
            f"{DESIGN_SYSTEM}"
        )

        messages = [{"role": "user", "content": base_prompt}]
        out: Dict[str, Any] = {}
        validation: Optional[PatchValidation] = None
        attempts = self.max_repairs + 1

        for attempt in range(1, attempts + 1):
            async for event in self._collect(
                messages,
                out,
                max_tokens=self.max_tokens,
                temperature=0.45,
                detail="Construindo evolução da interface",
            ):
                yield event

            if out["error"]:
                state.error = out["error"]
                yield {"type": "error", "detail": out["error"]}
                return

            if out.get("finish_reason") == "length" and out.get("content"):
                async for event in self._continue(
                    messages,
                    out["content"],
                    out,
                    max_tokens=self.max_tokens,
                    temperature=0.3,
                    detail="Completando documento evoluído",
                ):
                    yield event

            validation = validate_and_repair(
                out["content"], mode="full", min_chars=200, min_text_chars=10
            )

            yield {"type": "validation_result", "scope": "full", **validation.to_event()}

            if validation.ok:
                break
            if attempt == attempts:
                if validation.html and len(validation.html) > 400:
                    break
                state.error = f"Validação falhou: {'; '.join(validation.errors[:3])}"
                yield {"type": "error", "detail": state.error}
                return

            yield {
                "type": "node_progress",
                "chars": len(validation.html or ""),
                "detail": f"Ajustando fechamento do HTML ({validation.errors[0][:80]})...",
            }
            messages = [
                {"role": "user", "content": base_prompt},
                {"role": "assistant", "content": "```html\n" + (out["content"] or "")[:18000] + "\n```"},
                {"role": "user", "content": validation.repair_prompt()},
            ]

        assert validation is not None and validation.html
        state.accumulated_patch = validation.html
        state.patch_type = "full"
        state.is_complete = True
        state.reasoning = out["reasoning"]

        explanation = re.sub(r"```(?:html)?[\s\S]*?```", "", out["content"]).strip()
        state.final_summary = explanation or f"Interface do {semantics.get('title', 'produto')} evoluída com foco em conversão e persuasão."

        audit = verify_ui_quality(validation.html)
        state.audit = audit
        yield {
            "type": "audit_result",
            "passed": audit.passed,
            "score": audit.score,
            "issues": audit.issues,
            "suggestions": audit.suggestions,
        }
        yield {
            "type": "agent_done",
            "patch": state.accumulated_patch,
            "patch_type": "full",
            "summary": state.final_summary,
            "reasoning": state.reasoning,
            "audit": audit.model_dump(),
            "plan": [],
        }

    # -- Fluxo: criação de tela conectada ao fluxo ----------------------
    async def _run_connected_screen(self, state: AgentState) -> AsyncGenerator[Dict[str, Any], None]:
        yield {
            "type": "node_start",
            "node": "architect",
            "title": "Arquiteto de Fluxos Multi-Tela",
            "detail": "Desenhando tela filha conectada via data-go compatível com a identidade visual do projeto...",
        }
        semantics = state.screen_semantics or extract_screen_semantics(state.current_html)
        history_text = format_chat_history(state.messages)
        parent_title = semantics.get("title", "Início")

        p_lower = state.prompt.lower()
        screen_name = "Nova Tela"
        for candidate in ["agendamento", "checkout", "carrinho", "contato", "detalhes", "login", "cadastro", "obrigado", "sucesso", "planos"]:
            if candidate in p_lower:
                screen_name = candidate.capitalize()
                break
        if screen_name == "Nova Tela":
            match = re.search(r"""(?:tela|página|pagina)\s+(?:de\s+)?([a-zA-Z0-9À-ÿ\s]{3,20})""", state.prompt, re.IGNORECASE)
            if match:
                screen_name = match.group(1).strip().capitalize()

        system = (
            "Você é o Arquiteto e Designer Sênior do Mockbird v2.\n"
            f"Você deve gerar uma NOVA TELA COMPLETA para o fluxo do projeto.\n"
            f"A tela principal atual é: '{parent_title}' ({semantics.get('summary', '')}).\n"
            f"NOVA TELA A CRIAR: '{screen_name}'.\n\n"
            "DIRETRIZES OBRIGATÓRIAS:\n"
            f"1. A nova tela DEVE seguir exatamente o mesmo tema visual, cores ({semantics.get('summary', '')}) e tipografia da tela principal.\n"
            f"2. DEVE conter um botão/link de retorno no topo ou breadcrumb com data-go='Início' ou data-go='{parent_title}' (ex: <a href='#/inicio' data-go='Início' class='...'>← Voltar</a>).\n"
            "3. O conteúdo deve ser rico, profissional e funcional (formulário funcional com inputs estilizados, cards de confirmação, botões interativos com data-toast).\n"
            "4. Responda SOMENTE o HTML dentro de ```html ... ``` sem explicações adicionais."
        )

        user_prompt = f"{history_text}PEDIDO: {state.prompt}\nCrie o código completo da tela '{screen_name}'."
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}]

        out: Dict[str, Any] = {}
        async for event in self._collect(messages, out, max_tokens=self.max_tokens, temperature=0.3, detail=f"Gerando tela conectada '{screen_name}'"):
            yield event

        raw = out.get("content") or ""
        extracted = extract_html(raw)
        validation = validate_and_repair(extracted, mode="full")
        if not validation.ok:
            validation = validate_and_repair(raw, mode="full")

        state.accumulated_patch = validation.html
        state.patch_type = "full"
        state.is_complete = True
        state.final_summary = f"Tela conectada '{screen_name}' criada com sucesso! Conectada à tela principal via data-go."

        yield {
            "type": "create_screen",
            "name": screen_name,
            "html": validation.html,
        }

        yield {
            "type": "agent_done",
            "patch": validation.html,
            "patch_type": "full",
            "summary": state.final_summary,
            "reasoning": out.get("reasoning"),
            "plan": [],
        }

    # -- Fluxo 5: tela completa do zero por seções ----------------------
    async def _plan(self, state: AgentState) -> AsyncGenerator[Dict[str, Any], None]:
        yield {
            "type": "node_start",
            "node": "planner",
            "title": "Planejando Arquitetura e Seções",
            "detail": "Decompondo o pedido em blocos de UI que serão gerados e validados separadamente...",
        }

        history_text = format_chat_history(state.messages)
        prompt = (
            "Você é o Arquiteto Principal de Interfaces do Mockbird. Analise o pedido do usuário, "
            f"{history_text}"
            "escolha uma direção estética e estrutural única (tema claro ou escuro, layout de app, dashboard, "
            "fluxo, editorial ou landing page conforme o domínio) e decomponha a interface em 3 blocos "
            "arquiteturais específicos para esse pedido (NÃO use sempre 'Navbar/Hero/Grid/Footer' se o pedido "
            "for um aplicativo, painel, formulário ou se pedir outra estrutura; inclua na description de cada bloco "
            "a paleta de cores, estilo visual e componentes exatos daquele bloco).\n"
            f"Pedido: {state.prompt}\n\n"
            "Responda SOMENTE JSON válido no formato:\n"
            '{"plan": [{"id": 1, "title": "Nome do Bloco 1", "description": "Estilo visual, paleta e componentes detalhados deste bloco"}]}'
        )

        out: Dict[str, Any] = {}
        async for event in self._collect(
            [{"role": "user", "content": prompt}],
            out,
            max_tokens=500,
            temperature=0.55,
            detail="Planejando seções",
        ):
            yield event

        if out["error"]:
            state.error = out["error"]
            yield {"type": "error", "detail": out["error"]}
            return

        plan: List[PlanStep] = []
        if not out["error"]:
            match = re.search(r"\{[\s\S]*\}", out["content"] or "")
            if match:
                try:
                    data = json.loads(match.group(0))
                    for item in data.get("plan", []):
                        if not isinstance(item, dict):
                            continue
                        plan.append(PlanStep(
                            id=int(item.get("id") or len(plan) + 1),
                            title=str(item.get("title") or f"Seção {len(plan) + 1}")[:80],
                            description=str(item.get("description") or "Seção da interface")[:300],
                        ))
                except (json.JSONDecodeError, ValueError, TypeError):
                    plan = []

        if len(plan) < 2:
            plan = [step.model_copy() for step in PLANNER_FALLBACK]

        state.plan = plan[:3]
        yield {"type": "plan_ready", "plan": [s.model_dump() for s in state.plan]}

    def _section_prompt(self, state: AgentState, index: int, total: int, previous: List[str]) -> str:
        step = state.plan[index]
        context = ""
        if previous:
            context = (
                "\nBLOCOS JÁ GERADOS ANTES DESTE (mantenha a mesma paleta de cores e identidade visual, sem repetir conteúdo):\n"
                + "\n".join(f"- {t}" for t in previous)
                + "\n"
            )
        position = "primeira" if index == 0 else ("última" if index == total - 1 else f"{index + 1}ª")
        proj_ctx = f"\n{state.project_context}\n" if state.project_context else ""
        return (
            "Você é o Diretor de Arte e Desenvolvedor Frontend Sênior do Mockbird v2.\n"
            f"PEDIDO COMPLETO DO USUÁRIO: {state.prompt}\n"
            f"Você está gerando a {position} de {total} partes da interface.\n"
            f"SEÇÃO ATUAL: {step.title} — {step.description}\n"
            f"{context}\n"
            f"{proj_ctx}"
            f"{DESIGN_SYSTEM}\n\n"
            "FORMATO DA RESPOSTA:\n"
            "1. Uma frase curta de raciocínio e, em seguida, o bloco ```html ... ```.\n"
            f"2. Envolva o bloco em um container raiz com data-mb-id=\"section-{index + 1}\" (pode ser <section>, <header>, <main>, <div> ou <aside> conforme a arquitetura da tela).\n"
            "3. Nada de <html>, <head>, <body>, <style> ou <script>.\n"
            "4. Conteúdo rico, autêntico e completo em Português (sem resumir, sem placeholders).\n"
            "5. Construa exatamente a arquitetura, paleta de cores e componentes pedidos para esta parte — NÃO force header/hero/footer genéricos se não fizerem sentido para esta interface."
        )

    async def _run_full_page(self, state: AgentState) -> AsyncGenerator[Dict[str, Any], None]:
        yield {
            "type": "node_start",
            "node": "inspector",
            "title": "Inspecionando Contexto do Projeto",
            "detail": "Analisando referências de design e tokens visuais...",
        }
        state.dom_summary = extract_dom_structure(state.current_html) if state.current_html else "Documento vazio."
        yield {
            "type": "tool_call",
            "tool": "get_canvas_dom",
            "summary": "Contexto do Canvas inspecionado.",
        }

        async for event in self._plan(state):
            yield event
        if state.error:
            return

        yield {
            "type": "node_start",
            "node": "executor",
            "title": "Gerando Interface Completa por Seções",
            "detail": "Cada seção é gerada, validada e corrigida individualmente antes de entrar na tela...",
        }

        sections: List[str] = []
        titles: List[str] = []
        failures: List[str] = []
        total = len(state.plan)

        for index, step in enumerate(state.plan):
            yield {
                "type": "node_start",
                "node": f"executor:section-{index + 1}",
                "title": f"Seção {index + 1}/{total}: {step.title}",
                "detail": step.description,
            }

            base_prompt = self._section_prompt(state, index, total, titles)
            messages = [{"role": "user", "content": base_prompt}]
            out: Dict[str, Any] = {}
            validation: Optional[PatchValidation] = None
            attempts = self.max_repairs + 1

            for attempt in range(1, attempts + 1):
                async for event in self._collect(
                    messages,
                    out,
                    max_tokens=self.section_max_tokens,
                    temperature=0.55,
                    detail=f"Gerando seção {index + 1}/{total}",
                ):
                    yield event

                if out["error"]:
                    # Erro de transporte/autenticação: não adianta tentar as próximas seções.
                    yield {"type": "error", "detail": out["error"]}
                    return

                # O modelo pode gastar todo o orçamento em raciocínio e devolver
                # conteúdo vazio. Nesse caso pedimos explicitamente só o HTML.
                if not extract_html(out.get("content") or "") and out.get("reasoning"):
                    if attempt < attempts:
                        yield {
                            "type": "node_progress",
                            "chars": 0,
                            "detail": "O modelo gastou o limite em raciocínio; pedindo apenas o HTML...",
                        }
                        messages = messages + [{
                            "role": "user",
                            "content": (
                                "Sua resposta anterior consumiu todo o limite de tokens em raciocínio e não "
                                "produziu HTML. Responda AGORA somente com o bloco ```html ... ``` da seção, "
                                "sem nenhum raciocínio antes ou depois."
                            ),
                        }]
                        continue

                # Truncamento: pede continuação exata uma única vez.
                if out.get("finish_reason") == "length" and out.get("content"):
                    async for event in self._continue(
                        messages,
                        out["content"],
                        out,
                        max_tokens=self.section_max_tokens,
                        temperature=0.35,
                        detail=f"Completando seção {index + 1}/{total}",
                    ):
                        yield event

                validation = validate_section(out["content"])
                yield {"type": "validation_result", "scope": f"section-{index + 1}", **validation.to_event()}

                if validation.ok:
                    break
                if attempt == attempts:
                    failures.append(f"{step.title}: {'; '.join(validation.errors[:3])}")
                    break

                yield {
                    "type": "node_progress",
                    "chars": len(validation.html or ""),
                    "detail": f"Corrigindo seção {index + 1} ({validation.errors[0][:80]})...",
                }
                messages = [
                    {"role": "user", "content": base_prompt},
                    {"role": "assistant", "content": "```html\n" + (out["content"] or "")[:6000] + "\n```"},
                    {"role": "user", "content": validation.repair_prompt()},
                ]

            if validation and validation.ok and validation.html:
                sections.append(validation.html)
                titles.append(step.title)
                yield {
                    "type": "tool_call",
                    "tool": "section_ready",
                    "summary": f"Seção '{step.title}' validada ({validation.score}/100).",
                }

        if not sections:
            detail = failures[0] if failures else "o modelo não retornou HTML válido"
            yield {
                "type": "error",
                "detail": (
                    f"Nenhuma seção válida foi gerada ({detail}). "
                    "Verifique o provedor/modelo em Configurações → LLM ou tente um pedido mais específico."
                ),
            }
            return

        yield {
            "type": "node_start",
            "node": "evaluator",
            "title": "Montando e Auditando a Tela",
            "detail": "Combinando as seções validadas e verificando estrutura final...",
        }

        assembled = assemble_sections(sections)
        if not assembled.ok and self.max_repairs:
            yield {"type": "validation_result", "scope": "document", **assembled.to_event()}
            yield {
                "type": "node_progress",
                "chars": len(assembled.html or ""),
                "detail": "Corrigindo inconsistências do documento montado...",
            }
            body = re.sub(r"<!DOCTYPE[\s\S]*?<body[^>]*>|</body>[\s\S]*$", "", assembled.html or "")
            repair_messages = [
                {"role": "user", "content": (
                    "Corrija o HTML abaixo mantendo o conteúdo e o design. Devolva o HTML completo "
                    "dentro de ```html ... ```, sem <html>/<body>.\n\n"
                    f"{DESIGN_SYSTEM}\n\nPROBLEMAS:\n" + "\n".join(f"- {e}" for e in assembled.errors)
                )},
                {"role": "assistant", "content": "```html\n" + body[:16000] + "\n```"},
                {"role": "user", "content": "Aplique as correções e devolva o HTML final fechado."},
            ]
            out = {}
            async for event in self._collect(
                repair_messages,
                out,
                max_tokens=self.max_tokens,
                temperature=0.3,
                detail="Corrigindo documento final",
            ):
                yield event
            if out["error"]:
                yield {"type": "error", "detail": out["error"]}
                return
            assembled = validate_and_repair(out["content"], mode="full", min_chars=200)
            yield {"type": "validation_result", "scope": "document", **assembled.to_event()}

        if not assembled.ok:
            yield {
                "type": "error",
                "detail": (
                    "O documento final não passou na validação: "
                    + "; ".join(assembled.errors[:3])
                    + ". Tente novamente ou gere a tela em partes."
                ),
            }
            return

        state.accumulated_patch = assembled.html
        state.patch_type = "full"
        state.is_complete = True
        state.reasoning = out.get("reasoning") if isinstance(out, dict) else None

        audit = verify_ui_quality(assembled.html)
        if failures:
            audit.passed = False
            audit.issues = list(audit.issues) + [f"Seção omitida — {f}" for f in failures]
        state.audit = audit
        yield {
            "type": "audit_result",
            "passed": audit.passed,
            "score": audit.score,
            "issues": audit.issues,
            "suggestions": audit.suggestions,
        }

        omitted = f" {len(failures)} seção(ões) foram omitidas." if failures else ""
        state.final_summary = (
            f"Tela construída em {len(sections)} seção(ões) validadas e aplicada no canvas "
            f"(qualidade {audit.score}/100).{omitted}"
        )

        yield {
            "type": "agent_done",
            "patch": state.accumulated_patch,
            "patch_type": "full",
            "summary": state.final_summary,
            "reasoning": state.reasoning,
            "audit": audit.model_dump(),
            "plan": [s.model_dump() for s in state.plan],
            "omitted_sections": failures,
        }
