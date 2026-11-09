import json
import re
from typing import AsyncGenerator, Dict, Any, List, Optional
import httpx

from app.agent.state import AgentState, PlanStep, ToolCallRecord
from app.agent.tools import (
    extract_dom_structure, 
    extract_element_snippet,
    diagnose_layout_issues,
    verify_ui_quality
)


def clean_extracted_html(text: str) -> str:
    """Extrai bloco HTML limpo defensivamente.
    Se o texto não contiver HTML real com tags estruturais, retorna string vazia."""
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

    # 3. Procura tags estruturais com fechamento (div, section, main, header, footer, button, form, etc.)
    m_tag = re.search(r"(<(?:div|section|main|header|footer|aside|article|form|nav|button|ul|ol|table|dialog|p|span|a|h[1-6])\b[\s\S]+?</(?:div|section|main|header|footer|aside|article|form|nav|button|ul|ol|table|dialog|p|span|a|h[1-6])>)", text, re.IGNORECASE)
    if m_tag:
        return m_tag.group(1).strip()

    # 4. Procura tags autocontidas válidas (img, input)
    m_self = re.search(r"(<(?:img|input|hr|br)\b[^>]*\/?>)", text, re.IGNORECASE)
    if m_self:
        return m_self.group(1).strip()

    # Se não houver tags HTML reais, NUNCA retorna texto corrido ou pensamento em prosa!
    return ""


class MockbirdAgentGraph:
    """Grafo de execução autônoma inteligente com decisão dinâmica de intenção, ferramentas e edição cirúrgica."""

    def __init__(self, base_url: str, headers: Dict[str, str]):
        self.base_url = base_url
        self.headers = headers

    async def _call_llm_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.4,
        max_tokens: int = 4096
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Chama a LLM com stream ativo, separando estritamente reasoning_content de content."""
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers=self.headers,
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True
                }
            ) as response:
                if response.status_code != 200:
                    err = await response.aread()
                    raise RuntimeError(f"LLM HTTP {response.status_code}: {err.decode()[:200]}")

                accumulated_content = []
                accumulated_reasoning = []
                total_chunks = 0

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line.replace("data:", "").strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})

                        r_chunk = delta.get("reasoning_content") or ""
                        c_chunk = delta.get("content") or ""

                        if r_chunk:
                            accumulated_reasoning.append(r_chunk)
                            total_chunks += 1
                            yield {
                                "type": "thinking_chunk",
                                "text": r_chunk
                            }

                        if c_chunk:
                            accumulated_content.append(c_chunk)
                            total_chunks += 1
                            yield {
                                "type": "content_chunk",
                                "text": c_chunk
                            }

                        if total_chunks % 15 == 0:
                            yield {
                                "type": "heartbeat",
                                "chars": sum(len(c) for c in accumulated_content) + sum(len(r) for r in accumulated_reasoning)
                            }
                    except Exception:
                        continue

                full_c = "".join(accumulated_content)
                full_r = "".join(accumulated_reasoning)

                # Extrai tag <think>...</think> se vier dentro de content
                if "<think>" in full_c and "</think>" in full_c:
                    think_part = re.search(r"<think>([\s\S]*?)</think>", full_c)
                    if think_part:
                        full_r += ("\n" if full_r else "") + think_part.group(1).strip()
                        full_c = re.sub(r"<think>[\s\S]*?</think>", "", full_c).strip()

                yield {
                    "type": "completed",
                    "content": full_c,
                    "reasoning": full_r
                }

    def _determine_intent(self, state: AgentState) -> str:
        """Determina a intenção real do usuário para não executar ferramentas desnecessárias."""
        # Se um elemento alvo foi expressamente selecionado, é edição cirúrgica
        if state.target_element and (state.target_element.mbId or state.target_element.selector or state.target_element.outerHtml):
            return "surgical_edit"

        p_lower = state.prompt.lower().strip()

        # Pergunta / Discussão / Explicação conceitual
        explanation_keywords = [
            "o que você acha", "o que acha", "como funciona", "por que", "explique", 
            "quais cores", "dúvida", "ajuda com conceito", "qual é a melhor", "me dê dicas",
            "dicas de design", "como posso melhorar"
        ]
        if any(kw in p_lower for kw in explanation_keywords) and not any(kw in p_lower for kw in ["consert", "mud", "cri", "alter"]):
            return "explanation"

        # Conserto ou reparo de layout quebrado
        repair_keywords = [
            "quebrado", "quebrada", "consertar", "concertar", "arrumar", "alinhar", 
            "corrigir", "ajustar", "bug", "erro no layout", "layout tá", "layout ta"
        ]
        if any(kw in p_lower for kw in repair_keywords):
            return "layout_repair"

        # Criação de nova página ou tela completa do zero
        full_keywords = [
            "crie uma landing page", "cria uma landing page", "nova página", "nova tela",
            "crie um site", "cria um site", "dashboard", "gerar tela", "gerar página", "landing page para"
        ]
        if any(kw in p_lower for kw in full_keywords):
            return "full_page"

        # Se já existe HTML na tela e o prompt é curto/específico (ex: "mude o botão", "troque a foto")
        if state.current_html and len(state.current_html) > 100:
            return "surgical_edit"

        return "full_page"

    async def run(self, state: AgentState) -> AsyncGenerator[Dict[str, Any], None]:
        """Executa o Grafo do Agente Autônomo emitindo eventos em tempo real via SSE."""
        intent = self._determine_intent(state)
        state.intent = intent

        # =========================================================================
        # FLUXO 1: RESPOSTA / CONSULTORIA / EXPLICAÇÃO (Sem gerar patch vazio)
        # =========================================================================
        if intent == "explanation":
            yield {
                "type": "node_start",
                "node": "analyst",
                "title": "Analisando Pergunta e Estrutura",
                "detail": "Avaliando contexto de UI/UX e formulando resposta técnica em Português..."
            }

            dom_summary = extract_dom_structure(state.current_html) if state.current_html else "Tela em branco."
            state.dom_summary = dom_summary

            prompt_analyst = (
                "Você é o Especialista Sênior de UI/UX e Frontend do Mockbird v2.\n"
                "Responda à pergunta do usuário de forma clara, prestativa e técnica em Português do Brasil.\n"
                "NÃO gere blocos de código completos a menos que o usuário peça exemplos curtos.\n\n"
                f"PERGUNTA DO USUÁRIO: {state.prompt}\n"
                f"DOM ATUAL DA TELA:\n{dom_summary}\n"
            )

            assistant_text = ""
            assistant_reasoning = ""

            async for chunk in self._call_llm_stream(
                [{"role": "user", "content": prompt_analyst}],
                state.model_name,
                temperature=0.4,
                max_tokens=1000
            ):
                if chunk["type"] == "completed":
                    assistant_text = chunk["content"]
                    assistant_reasoning = chunk["reasoning"]

            state.is_complete = True
            state.final_summary = assistant_text or "Aqui está a análise solicitada."
            state.reasoning = assistant_reasoning
            state.accumulated_patch = None
            state.patch_type = "none"

            yield {
                "type": "agent_done",
                "patch": None,
                "patch_type": "none",
                "summary": state.final_summary,
                "reasoning": state.reasoning,
                "plan": [],
                "audit": None
            }
            return

        # =========================================================================
        # FLUXO 2: EDIÇÃO CIRÚRGICA DE ELEMENTO ALVO
        # =========================================================================
        if intent == "surgical_edit":
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
                "detail": f"Analisando estrutura, classes CSS e contexto do seletor '{target_selector or target_mb_id}'..."
            }

            state.tools_history.append(ToolCallRecord(
                tool="inspect_element",
                args={"selector": target_selector, "mbId": target_mb_id},
                result=f"Elemento <{target_tag}> inspecionado com sucesso."
            ))

            yield {
                "type": "tool_call",
                "tool": "inspect_element",
                "summary": f"Alvo <{target_tag}> localizado no DOM."
            }

            yield {
                "type": "node_start",
                "node": "executor",
                "title": f"Gerando Modificação Cirúrgica de <{target_tag}>",
                "detail": "Alterando exclusivamente o componente solicitado sem tocar no restante da tela..."
            }

            element_prompt = (
                "Você é o Engenheiro Frontend do Mockbird v2 especializado em refatoração cirúrgica de componentes.\n"
                f"PEDIDO DO USUÁRIO: {state.prompt}\n\n"
                f"ELEMENTO ALVO: <{target_tag}>\n"
                f"IDENTIFICADOR data-mb-id: {target_mb_id or 'alvo'}\n"
                f"SELETOR: {target_selector}\n"
                f"CÓDIGO ATUAL DO ELEMENTO:\n{target_snippet or 'Elemento no Canvas'}\n\n"
                "REGRAS ESTRITAS:\n"
                "1. Retorne APENAS o código HTML atualizado deste elemento específico dentro do bloco ```html ... ```.\n"
                "2. PRESERVE o atributo data-mb-id no elemento modificado.\n"
                "3. NUNCA gere o documento HTML inteiro ou tags <html>/<body>. Apenas o elemento modificado!\n"
                "4. Use Tailwind CSS moderno para o estilo.\n"
                "5. Explique resumidamente em Português o que foi alterado antes ou depois do código."
            )

            raw_code = ""
            assistant_reasoning = ""

            async for chunk in self._call_llm_stream(
                [{"role": "user", "content": element_prompt}],
                state.model_name,
                temperature=0.3,
                max_tokens=2048
            ):
                if chunk["type"] == "heartbeat":
                    yield {
                        "type": "node_progress",
                        "chars": chunk["chars"],
                        "detail": f"Gerando alteração do elemento ({chunk['chars']} caracteres)..."
                    }
                elif chunk["type"] == "completed":
                    raw_code = chunk["content"]
                    assistant_reasoning = chunk["reasoning"]

            extracted_snippet = clean_extracted_html(raw_code)
            
            # Se a LLM não colocou data-mb-id e tínhamos um, garante que o elemento mantenha
            if extracted_snippet and target_mb_id and "data-mb-id" not in extracted_snippet:
                extracted_snippet = re.sub(r"^<([a-zA-Z0-9\-]+)", rf'<\1 data-mb-id="{target_mb_id}"', extracted_snippet, count=1)

            state.accumulated_patch = extracted_snippet if extracted_snippet else None
            state.patch_type = "element" if state.accumulated_patch else "none"
            state.target_selector = target_selector
            state.target_mb_id = target_mb_id
            state.reasoning = assistant_reasoning

            # Mensagem explicativa em português (remove bloco de código para a resposta de texto)
            explanation = re.sub(r"```(?:html)?[\s\S]*?```", "", raw_code).strip()
            state.final_summary = explanation or f"Elemento <{target_tag}> atualizado cirurgicamente com sucesso."

            yield {
                "type": "tool_call",
                "tool": "patch_element",
                "summary": f"Fragmento do elemento <{target_tag}> pronto para aplicação."
            }

            yield {
                "type": "agent_done",
                "patch": state.accumulated_patch,
                "patch_type": state.patch_type,
                "target_selector": state.target_selector,
                "target_mb_id": state.target_mb_id,
                "target_tag": target_tag,
                "summary": state.final_summary,
                "reasoning": state.reasoning,
                "plan": [],
                "audit": None
            }
            return

        # =========================================================================
        # FLUXO 3: REPARO DE LAYOUT QUEBRADO (Preservando conteúdo existente)
        # =========================================================================
        if intent == "layout_repair":
            yield {
                "type": "node_start",
                "node": "inspector",
                "title": "Diagnosticando Quebras no Layout",
                "detail": "Inspecionando hierarquia DOM, tags desbalanceadas e regras de layout..."
            }

            dom_summary = extract_dom_structure(state.current_html)
            detected_issues = diagnose_layout_issues(state.current_html)
            state.dom_summary = dom_summary

            yield {
                "type": "tool_call",
                "tool": "get_canvas_dom",
                "summary": f"DOM inspecionado: {len(detected_issues)} anomalias estruturais detectadas."
            }

            yield {
                "type": "node_start",
                "node": "executor",
                "title": "Corrigindo Estrutura e Estilos de Layout",
                "detail": "Ajustando containers, classes de alinhamento e preservando o conteúdo original..."
            }

            issues_prompt = "\n".join([f"- {iss}" for iss in detected_issues]) if detected_issues else "- Layout visual desalinhado conforme apontado pelo usuário."

            repair_prompt = (
                "Você é o Especialista Frontend Sênior do Mockbird v2.\n"
                f"SOLICITAÇÃO DO USUÁRIO: {state.prompt}\n\n"
                f"DIAGNÓSTICO TÉCNICO INICIAL:\n{issues_prompt}\n\n"
                f"HTML ATUAL DA TELA:\n{state.current_html}\n\n"
                "INSTRUÇÕES CRUCIAIS:\n"
                "1. Corrija o layout quebradiço (alinhe containers com flex/grid adequados, garanta overflow correto, feche tags e garanta responsividade).\n"
                "2. PRESERVE a identidade, os textos e o propósito da tela existente. NUNCA substitua a tela por um template aleatório!\n"
                "3. Emita o código HTML corrigido completo dentro de ```html ... ```.\n"
                "4. Explique em uma frase inicial o que você corrigiu."
            )

            raw_code = ""
            assistant_reasoning = ""

            async for chunk in self._call_llm_stream(
                [{"role": "user", "content": repair_prompt}],
                state.model_name,
                temperature=0.3,
                max_tokens=4096
            ):
                if chunk["type"] == "heartbeat":
                    yield {
                        "type": "node_progress",
                        "chars": chunk["chars"],
                        "detail": f"Construindo correção de layout ({chunk['chars']} caracteres)..."
                    }
                elif chunk["type"] == "completed":
                    raw_code = chunk["content"]
                    assistant_reasoning = chunk["reasoning"]

            extracted_html = clean_extracted_html(raw_code)
            state.accumulated_patch = extracted_html if extracted_html else None
            state.patch_type = "full" if state.accumulated_patch else "none"
            state.reasoning = assistant_reasoning

            # Avalia qualidade
            if state.accumulated_patch:
                state.audit = verify_ui_quality(state.accumulated_patch)
                yield {
                    "type": "audit_result",
                    "passed": state.audit.passed,
                    "score": state.audit.score,
                    "issues": state.audit.issues,
                    "suggestions": state.audit.suggestions
                }

            explanation = re.sub(r"```(?:html)?[\s\S]*?```", "", raw_code).strip()
            state.final_summary = explanation or "Layout corrigido: ajustadas estruturas de container, alinhamentos e tags."

            yield {
                "type": "agent_done",
                "patch": state.accumulated_patch,
                "patch_type": state.patch_type,
                "summary": state.final_summary,
                "reasoning": state.reasoning,
                "audit": state.audit.model_dump() if state.audit else None,
                "plan": []
            }
            return

        # =========================================================================
        # FLUXO 4: GERAÇÃO DE TELA COMPLETA (Planejamento + Execução + Auditoria)
        # =========================================================================
        yield {
            "type": "node_start",
            "node": "inspector",
            "title": "Inspecionando Contexto do Projeto",
            "detail": "Analisando referências de design e tokens visuais..."
        }

        dom_summary = extract_dom_structure(state.current_html) if state.current_html else "Documento vazio."
        state.dom_summary = dom_summary

        yield {
            "type": "tool_call",
            "tool": "get_canvas_dom",
            "summary": "Contexto do Canvas inspecionado."
        }

        # Planejador
        yield {
            "type": "node_start",
            "node": "planner",
            "title": "Planejando Arquitetura e Seções",
            "detail": "Decompondo requisitos em blocos de UI modernos..."
        }

        planner_prompt = (
            "Você é o Arquiteto Principal de Interfaces do Mockbird. Analise o pedido do usuário e decomponha a construção da tela em 3 etapas claras.\n"
            f"Pedido: {state.prompt}\n\n"
            "Responda SOMENTE em formato JSON válido:\n"
            "{\n"
            '  "plan": [\n'
            '    {"id": 1, "title": "Navbar & Hero Section", "description": "Cabeçalho com logo, menu, título impactante e imagem principal"},\n'
            '    {"id": 2, "title": "Grid de Conteúdo / Recursos", "description": "Cards visuais com especificações e fotos reais"},\n'
            '    {"id": 3, "title": "Seção de Conversão & Rodapé", "description": "Formulário com CTA e rodapé organizado"}\n'
            "  ]\n"
            "}"
        )

        planner_content = ""
        async for chunk in self._call_llm_stream(
            [{"role": "user", "content": planner_prompt}],
            state.model_name,
            temperature=0.2,
            max_tokens=600
        ):
            if chunk["type"] == "completed":
                planner_content = chunk["content"]

        try:
            m_json = re.search(r"\{[\s\S]*\}", planner_content)
            if m_json:
                data = json.loads(m_json.group(0))
                steps = [PlanStep(**s) for s in data.get("plan", [])]
                if steps:
                    state.plan = steps
        except Exception:
            state.plan = [
                PlanStep(id=1, title="Estrutura & Hero", description="Cabeçalho e seção de destaque"),
                PlanStep(id=2, title="Grid de Componentes", description="Exposição de produtos/recursos"),
                PlanStep(id=3, title="Conversão & Rodapé", description="Chamadas de ação e links finais")
            ]

        yield {
            "type": "plan_ready",
            "plan": [s.model_dump() for s in state.plan]
        }

        # Executor
        yield {
            "type": "node_start",
            "node": "executor",
            "title": "Gerando Interface Completa",
            "detail": "Construindo código HTML real com Tailwind CSS, fotos reais do Unsplash e data-mb-id..."
        }

        plan_desc = "\n".join([f"- {s.title}: {s.description}" for s in state.plan])
        executor_prompt = (
            "Você é o Diretor de Arte e Desenvolvedor Frontend Sênior do Mockbird v2.\n"
            "Crie o código HTML COMPLETO, ESTONTEANTE e PROFISSIONAL para a solicitação do usuário.\n\n"
            f"SOLICITAÇÃO: {state.prompt}\n"
            f"PLANO APROVADO:\n{plan_desc}\n\n"
            "REGRAS INEGOCIÁVEIS (LEIA COM ATENÇÃO):\n"
            "1. PROIBIDO RESUMIR: NUNCA escreva textos como 'noise overlay div', 'hero div' ou comentários de TODO. Escreva CADA tag, classe, texto e botão por completo!\n"
            "2. IMAGENS REAIS: Use sempre tags <img> com URLs completas e reais do Unsplash.\n"
            "3. DESIGN SYSTEM: Fundo escuro premium (bg-[#09090b] ou bg-slate-950), superfícies bg-[#121215], bordas border-white/10, tipografia sans-serif limpa.\n"
            "4. INTERATIVIDADE: Todo elemento relevante deve ter data-mb-id='...' único.\n"
            "5. EMITA DIRETAMENTE dentro do bloco ```html ... ```."
        )

        raw_code = ""
        assistant_reasoning = ""

        async for chunk in self._call_llm_stream(
            [{"role": "user", "content": executor_prompt}],
            state.model_name,
            temperature=0.4,
            max_tokens=4096
        ):
            if chunk["type"] == "heartbeat":
                yield {
                    "type": "node_progress",
                    "chars": chunk["chars"],
                    "detail": f"Gerando código HTML em tempo real ({chunk['chars']} caracteres)..."
                }
            elif chunk["type"] == "completed":
                raw_code = chunk["content"]
                assistant_reasoning = chunk["reasoning"]

        extracted_html = clean_extracted_html(raw_code)
        state.accumulated_patch = extracted_html if extracted_html else None
        state.patch_type = "full" if state.accumulated_patch else "none"
        state.reasoning = assistant_reasoning

        # Avaliador
        if state.accumulated_patch:
            yield {
                "type": "node_start",
                "node": "evaluator",
                "title": "Avaliador de Qualidade & Antirresumo",
                "detail": "Auditando se o código contém resumos preguiçosos ou tags desbalanceadas..."
            }

            audit = verify_ui_quality(state.accumulated_patch)
            state.audit = audit

            yield {
                "type": "audit_result",
                "passed": audit.passed,
                "score": audit.score,
                "issues": audit.issues,
                "suggestions": audit.suggestions
            }

        state.is_complete = True
        state.final_summary = (
            f"Interface construída com sucesso. "
            f"Qualidade avaliada com nota {state.audit.score if state.audit else 100}/100. "
            f"Pronta para exibição e testes no Canvas."
        )

        yield {
            "type": "agent_done",
            "patch": state.accumulated_patch,
            "patch_type": state.patch_type,
            "summary": state.final_summary,
            "reasoning": state.reasoning,
            "audit": state.audit.model_dump() if state.audit else None,
            "plan": [s.model_dump() for s in state.plan]
        }
