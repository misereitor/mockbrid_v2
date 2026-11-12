"""Testes do grafo do agente com LLM falsa (SSE compatível com OpenAI).

Cobrem os modos de falha que quebravam o canvas em produção: provedor fora do
ar, resposta truncada, seção inválida, edição sem efeito e vazamento de
raciocínio como HTML.
"""

import json
from collections import deque
from typing import Deque, Tuple

import httpx
import pytest

from app.agent.graph import MockbirdAgentGraph
from app.agent.state import AgentState, TargetElementInfo


SECTION_1 = (
    '<section data-mb-id="hero" class="min-h-screen flex flex-col items-center justify-center bg-[#09090b] p-16">'
    '<h1 data-mb-id="hero-title" class="text-6xl font-extrabold text-white">Controle total do seu funil</h1>'
    '<p data-mb-id="hero-copy" class="text-slate-300 text-lg">Centralize leads, propostas e receita em um só painel.</p>'
    '<button data-mb-id="hero-cta" class="bg-red-500 text-white px-6 py-3 rounded-xl">Testar grátis</button>'
    "</section>"
)
SECTION_2 = (
    '<section data-mb-id="features" class="py-24 px-8 bg-[#121215]">'
    '<h2 data-mb-id="features-title" class="text-4xl font-bold text-white">Recursos que vendem por você</h2>'
    '<p data-mb-id="features-copy" class="text-slate-300">Automação de follow-up, relatórios e integrações nativas.</p>'
    "</section>"
)
SECTION_3 = (
    '<section data-mb-id="cta" class="py-24 px-8 bg-[#09090b] text-center">'
    '<h2 data-mb-id="cta-title" class="text-4xl font-bold text-white">Comece hoje mesmo</h2>'
    '<button data-mb-id="cta-button" class="bg-white text-black px-8 py-4 rounded-xl">Criar conta</button>'
    "</section>"
)

BUTTON_OLD = "<button data-mb-id='btn-cta' class='bg-blue-600 text-white px-4 py-2 rounded'>Começar</button>"
BUTTON_NEW = "<button data-mb-id='btn-cta' class='bg-emerald-500 text-white px-4 py-2 rounded'>Garantir Vaga</button>"


def _sse(text: str, finish: str = "stop") -> httpx.Response:
    payload = ""
    for i in range(0, len(text), 40):
        payload += "data: " + json.dumps({
            "choices": [{"delta": {"content": text[i:i + 40]}, "finish_reason": None}]
        }) + "\n\n"
    payload += "data: " + json.dumps({
        "choices": [{"delta": {}, "finish_reason": finish}]
    }) + "\n\n"
    payload += "data: [DONE]\n\n"
    return httpx.Response(200, content=payload.encode(), headers={"content-type": "text/event-stream"})


class FakeLLM:
    def __init__(self) -> None:
        self.plan = json.dumps({
            "plan": [
                {"id": 1, "title": "Hero", "description": "Navbar e hero"},
                {"id": 2, "title": "Recursos", "description": "Grid de recursos"},
                {"id": 3, "title": "Conversão", "description": "CTA e rodapé"},
            ]
        })
        self.sections: Deque[Tuple[str, str]] = deque()
        self.section_repairs: Deque[Tuple[str, str]] = deque()
        self.document_repairs: Deque[Tuple[str, str]] = deque()
        self.elements: Deque[Tuple[str, str]] = deque()
        self.element_repairs: Deque[Tuple[str, str]] = deque()
        self.continuations: Deque[Tuple[str, str]] = deque()
        self.explanation = "O contraste está bom; sugiro aumentar o espaçamento entre os cards."
        self.calls: list[str] = []
        self.fail_first_section = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        user_texts = [m["content"] for m in body["messages"] if m.get("role") == "user"]
        last = user_texts[-1] if user_texts else ""
        joined = "\n".join(user_texts)
        self.calls.append(last[:80])

        if "Continue EXATAMENTE" in last:
            text, finish = self.continuations.popleft() if self.continuations else (SECTION_1, "stop")
            return _sse(text, finish)
        if "rejeitado pelo validador" in last:
            if "ELEMENTO ALVO" in joined:
                text, finish = self.element_repairs.popleft() if self.element_repairs else (BUTTON_NEW, "stop")
            elif "SEÇÃO ATUAL" in joined:
                text, finish = self.section_repairs.popleft() if self.section_repairs else (SECTION_2, "stop")
            else:
                text, finish = self.document_repairs.popleft() if self.document_repairs else (SECTION_1, "stop")
            return _sse(text, finish)
        if "Responda SOMENTE JSON" in last:
            return _sse(self.plan)
        if "SEÇÃO ATUAL" in last:
            text, finish = self.sections.popleft() if self.sections else (SECTION_1, "stop")
            return _sse(text, finish)
        if "ELEMENTO ALVO" in last:
            text, finish = self.elements.popleft() if self.elements else (BUTTON_NEW, "stop")
            return _sse(text, finish)
        if "Responda à pergunta do usuário" in last:
            return _sse(self.explanation)
        return _sse("<div class='p-4'>fallback</div>")


def _graph(fake: FakeLLM) -> MockbirdAgentGraph:
    graph = MockbirdAgentGraph(
        base_url="http://fake-llm/v1",
        headers={"Authorization": "Bearer test"},
        transport=httpx.MockTransport(fake),
    )
    graph.max_attempts = 2
    graph.max_repairs = 1
    return graph


async def _collect(graph: MockbirdAgentGraph, state: AgentState) -> list[dict]:
    events = []
    async for event in graph.run(state):
        events.append(event)
    return events


def _done(events: list[dict]):
    return [e for e in events if e["type"] == "agent_done"]


@pytest.mark.asyncio
async def test_provider_down_returns_error_without_fake_patch():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    graph = MockbirdAgentGraph("http://fake/v1", {}, transport=httpx.MockTransport(handler))
    graph.max_attempts = 2

    events = await _collect(graph, AgentState(prompt="Crie uma landing page", current_html="", model_name="fake"))

    errors = [e for e in events if e["type"] == "error"]
    assert errors, "o erro do provedor precisa ser visível"
    assert "Tempo esgotado" in errors[0]["detail"]
    assert not _done(events), "não pode existir agent_done sem HTML válido"
    assert "Interface Atualizada" not in json.dumps(events)


@pytest.mark.asyncio
async def test_http_401_is_not_retried_and_mentions_provider_config():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    graph = MockbirdAgentGraph("http://fake/v1", {}, transport=httpx.MockTransport(handler))
    events = await _collect(graph, AgentState(prompt="Crie uma landing page", current_html="", model_name="fake"))

    error = next(e for e in events if e["type"] == "error")
    assert "401" in error["detail"]
    assert "Configurações → LLM" in error["detail"]
    assert len(requests) == 1, "erro de autenticação não deve ser repetido"


@pytest.mark.asyncio
async def test_full_page_generates_each_section_and_validates_document():
    fake = FakeLLM()
    fake.sections = deque([(SECTION_1, "stop"), (SECTION_2, "stop"), (SECTION_3, "stop")])

    events = await _collect(_graph(fake), AgentState(prompt="Crie uma landing page de CRM", current_html="", model_name="fake"))

    validations = [e for e in events if e["type"] == "validation_result"]
    assert len(validations) >= 3
    assert all(v["ok"] for v in validations)

    done = _done(events)[0]
    assert done["patch_type"] == "full"
    assert done["patch"].count("<html") == 1
    assert "hero-title" in done["patch"] and "features" in done["patch"] and "cta-button" in done["patch"]
    assert done["omitted_sections"] == []
    assert done["audit"]["passed"] is True


@pytest.mark.asyncio
async def test_invalid_section_is_asked_to_fix_itself():
    fake = FakeLLM()
    fake.sections = deque([
        ("<section class='p-4'></section>", "stop"),
        (SECTION_2, "stop"),
        (SECTION_3, "stop"),
    ])
    fake.section_repairs = deque([(SECTION_1, "stop")])

    events = await _collect(_graph(fake), AgentState(prompt="Crie uma landing page de CRM", current_html="", model_name="fake"))

    failed = [v for v in events if v["type"] == "validation_result" and not v["ok"]]
    assert failed, "a seção vazia deveria ser reprovada"
    done = _done(events)[0]
    assert "hero-title" in done["patch"]
    assert any("Corrigindo seção" in (e.get("detail") or "") for e in events if e["type"] == "node_progress")


@pytest.mark.asyncio
async def test_all_sections_invalid_returns_error_and_applies_nothing():
    fake = FakeLLM()
    fake.sections = deque([("<section></section>", "stop")] * 3)
    fake.section_repairs = deque([("<section></section>", "stop")] * 3)

    events = await _collect(_graph(fake), AgentState(prompt="Crie uma landing page de CRM", current_html="", model_name="fake"))

    assert not _done(events)
    error = next(e for e in events if e["type"] == "error")
    assert "Nenhuma seção válida" in error["detail"]


@pytest.mark.asyncio
async def test_truncated_section_requests_continuation():
    truncated = SECTION_1[: len(SECTION_1) // 2]
    rest = SECTION_1[len(SECTION_1) // 2:]
    fake = FakeLLM()
    fake.sections = deque([(truncated, "length"), (SECTION_2, "stop"), (SECTION_3, "stop")])
    fake.continuations = deque([(rest, "stop")])

    events = await _collect(_graph(fake), AgentState(prompt="Crie uma landing page de CRM", current_html="", model_name="fake"))

    done = _done(events)[0]
    assert "hero-cta" in done["patch"]
    assert any("truncada" in (e.get("detail") or "") for e in events if e["type"] == "node_progress")


@pytest.mark.asyncio
async def test_surgical_edit_returns_validated_element_patch():
    fake = FakeLLM()
    fake.elements = deque([(BUTTON_NEW, "stop")])

    state = AgentState(
        prompt="Mude a cor do botão para verde e o texto para 'Garantir Vaga'",
        current_html=f"<section class='p-8'>{BUTTON_OLD}</section>",
        target_element=TargetElementInfo(mbId="btn-cta", tag="button", selector="#btn-cta", outerHtml=BUTTON_OLD),
        model_name="fake",
    )
    events = await _collect(_graph(fake), state)

    done = _done(events)[0]
    assert done["patch_type"] == "element"
    assert done["patch"].startswith("<button")
    assert 'data-mb-id="btn-cta"' in done["patch"]
    assert "Garantir Vaga" in done["patch"]
    assert done["summary"]


@pytest.mark.asyncio
async def test_surgical_edit_that_changes_nothing_is_rejected():
    fake = FakeLLM()
    fake.elements = deque([(BUTTON_OLD, "stop")])
    fake.element_repairs = deque([(BUTTON_OLD, "stop")])

    state = AgentState(
        prompt="Mude a cor do botão",
        current_html=f"<section class='p-8'>{BUTTON_OLD}</section>",
        target_element=TargetElementInfo(mbId="btn-cta", tag="button", selector="#btn-cta", outerHtml=BUTTON_OLD),
        model_name="fake",
    )
    events = await _collect(_graph(fake), state)

    assert not _done(events)
    error = next(e for e in events if e["type"] == "error")
    assert "idêntico" in error["detail"]


@pytest.mark.asyncio
async def test_explanation_flow_never_emits_html_patch():
    fake = FakeLLM()
    events = await _collect(
        _graph(fake),
        AgentState(
            prompt="O que você acha do contraste desta interface?",
            current_html="<div class='bg-slate-900 p-4'><h1>Título</h1></div>",
            model_name="fake",
        ),
    )

    done = _done(events)[0]
    assert done["patch"] is None
    assert done["patch_type"] == "none"
    assert "contraste" in done["summary"]
