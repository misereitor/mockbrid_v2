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
from app.agent.state import AgentState, PlanStep, ToolCallRecord
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
    PlanStep(id=1, title="Estrutura & Hero", description="Cabeçalho, navegação e seção de destaque com CTA"),
    PlanStep(id=2, title="Grid de Conteúdo", description="Cards/seções que expõem recursos, produtos ou dados principais"),
    PlanStep(id=3, title="Conversão & Rodapé", description="Chamada final para ação e rodapé com links"),
]

DESIGN_SYSTEM = (
    "DESIGN SYSTEM (obrigatório): fundo #09090b, superfícies #121215, bordas border-white/10, "
    "texto branco/slate-300, cantos rounded-2xl, badges bg-white/5 backdrop-blur-md, "
    "tipografia sans-serif com tracking-tight nos títulos, espaçamento generoso (py-16/py-24), "
    "responsivo (grid-cols-1 md:grid-cols-2 lg:grid-cols-3). "
    "Use SOMENTE classes utilitárias do Tailwind (o CDN já está ativo). É PROIBIDO <style>, "
    "<script>, <html>, <head> ou <body>. Não use Lorem ipsum, placeholders cinzas nem comentários de TODO. "
    "Imagens sempre com <img> de URLs reais do Unsplash (auto=format&fit=crop&w=1200&q=80). "
    "Todo container, card, botão, link, imagem e título precisa de data-mb-id único e descritivo."
)


def _normalize_html(html: str) -> str:
    """Compara HTML ignorando espaços, aspas e diferenças de envelope do documento."""
    body = re.sub(r"<!DOCTYPE[\s\S]*?<body[^>]*>|</body>[\s\S]*$", "", html or "", flags=re.IGNORECASE)
    return re.sub(r"[\s\"']+", "", body).lower()


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
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
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
    def _determine_intent(self, state: AgentState) -> str:
        if state.target_element and (
            state.target_element.mbId or state.target_element.selector or state.target_element.outerHtml
        ):
            return "surgical_edit"

        p_lower = state.prompt.lower().strip()

        explanation_keywords = [
            "o que você acha", "o que acha", "como funciona", "por que", "explique",
            "quais cores", "dúvida", "ajuda com conceito", "qual é a melhor", "me dê dicas",
            "dicas de design", "como posso melhorar",
        ]
        if any(kw in p_lower for kw in explanation_keywords) and not any(
            kw in p_lower for kw in ["consert", "mud", "cri", "alter"]
        ):
            return "explanation"

        repair_keywords = [
            "quebrado", "quebrada", "consertar", "concertar", "arrumar", "alinhar",
            "corrigir", "ajustar", "bug", "erro no layout", "layout tá", "layout ta",
        ]
        if any(kw in p_lower for kw in repair_keywords):
            return "layout_repair"

        full_keywords = [
            "crie uma landing page", "cria uma landing page", "nova página", "nova tela",
            "crie um site", "cria um site", "dashboard", "gerar tela", "gerar página", "landing page para",
        ]
        if any(kw in p_lower for kw in full_keywords):
            return "full_page"

        if state.current_html and len(state.current_html) > 100:
            return "surgical_edit"

        return "full_page"

    # ------------------------------------------------------------------
    # Execução
    # ------------------------------------------------------------------
    async def run(self, state: AgentState) -> AsyncGenerator[Dict[str, Any], None]:
        intent = self._determine_intent(state)
        state.intent = intent
        self.model = state.model_name

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

        base_prompt = (
            "Você é o Engenheiro Frontend do Mockbird v2 especializado em refatoração cirúrgica.\n"
            f"PEDIDO DO USUÁRIO: {state.prompt}\n\n"
            f"ELEMENTO ALVO: <{target_tag}>\n"
            f"IDENTIFICADOR data-mb-id: {target_mb_id or 'alvo'}\n"
            f"SELETOR: {target_selector}\n"
            f"CÓDIGO ATUAL DO ELEMENTO:\n{target_snippet or 'Elemento no Canvas'}\n\n"
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

    # -- Fluxo 4: tela completa por seções ------------------------------
    async def _plan(self, state: AgentState) -> AsyncGenerator[Dict[str, Any], None]:
        yield {
            "type": "node_start",
            "node": "planner",
            "title": "Planejando Arquitetura e Seções",
            "detail": "Decompondo o pedido em blocos de UI que serão gerados e validados separadamente...",
        }

        prompt = (
            "Você é o Arquiteto Principal de Interfaces do Mockbird. Decomponha o pedido em 3 seções "
            "independentes de uma página web, em ordem de leitura.\n"
            f"Pedido: {state.prompt}\n\n"
            "Responda SOMENTE JSON válido no formato:\n"
            '{"plan": [{"id": 1, "title": "Navbar & Hero", "description": "..."}]}'
        )

        out: Dict[str, Any] = {}
        async for event in self._collect(
            [{"role": "user", "content": prompt}],
            out,
            max_tokens=500,
            temperature=0.2,
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
                "\nSEÇÕES JÁ GERADAS (não repita o conteúdo delas):\n"
                + "\n".join(f"- {t}" for t in previous)
                + "\n"
            )
        position = "primeira" if index == 0 else ("última" if index == total - 1 else f"{index + 1}ª")
        return (
            "Você é o Diretor de Arte e Desenvolvedor Frontend Sênior do Mockbird v2.\n"
            f"PEDIDO COMPLETO DO USUÁRIO: {state.prompt}\n"
            f"Você está gerando a {position} de {total} seções.\n"
            f"SEÇÃO ATUAL: {step.title} — {step.description}\n"
            f"{context}\n"
            f"{DESIGN_SYSTEM}\n\n"
            "FORMATO DA RESPOSTA:\n"
            "1. Uma frase curta de raciocínio e, em seguida, o bloco ```html ... ```.\n"
            f"2. O bloco deve começar com <section data-mb-id=\"section-{index + 1}\" ...> e terminar com </section>.\n"
            "3. Nada de <html>, <head>, <body>, <style> ou <script>.\n"
            "4. Conteúdo real e completo em Português (sem resumir, sem placeholders).\n"
            "5. Se for a primeira seção, inclua <header> com navbar e o hero. "
            "Se for a última, inclua a chamada final e o <footer>."
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
                    temperature=0.35,
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
