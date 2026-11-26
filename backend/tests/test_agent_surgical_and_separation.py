import os
import pytest
import httpx
import secrets
import json

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")

# Este teste chama um LLM real (`bonsai-27b`). A stack do CI não tem provedor de
# IA e, mesmo com um, o modelo às vezes não converge ("limite de iterações"), então
# o resultado não é determinístico. Só roda quando alguém pede explicitamente, com
# um provedor configurado: `AI_E2E=1 pytest tests/test_agent_surgical_and_separation.py`.
requires_real_llm = pytest.mark.skipif(
    not os.getenv("AI_E2E"),
    reason="depende de um LLM real e não determinístico; defina AI_E2E=1 para rodar",
)


@requires_real_llm
@pytest.mark.asyncio
async def test_agent_intent_and_separation():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        # 1. Registra usuário de teste
        email = f"agent_tester_{secrets.token_hex(4)}@empresa.com"
        pwd = "SecureAgentPass123!"
        res_reg = await client.post("/api/auth/register", json={
            "email": email,
            "password": pwd,
            "name": "Agent Tester",
            "organization_name": f"Org Agent {secrets.token_hex(3)}"
        })
        assert res_reg.status_code == 200, res_reg.text

        csrf = client.cookies.get("mockbird_csrf")
        stream_headers = {"X-CSRF-Token": csrf} if csrf else {}

        # -------------------------------------------------------------------
        # TESTE 1: Pergunta conceitual (NÃO deve gerar patch nem vazar reasoning)
        # -------------------------------------------------------------------
        print("\n--- TESTE 1: Pergunta / Explicação ---")
        async with client.stream(
            "POST",
            "/api/ai/agent/stream",
            headers=stream_headers,
            json={
                "prompt": "O que você acha da tipografia e do contraste desta interface?",
                "current_html": "<div class='bg-slate-900 text-white p-4'><h1 class='text-2xl font-bold'>Título</h1></div>",
                "model_name": "bonsai-27b"
            }
        ) as res_expl:
            assert res_expl.status_code == 200
            done_event = None
            async for line in res_expl.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line.replace("data:", "").strip()
                if not data_str:
                    continue
                ev = json.loads(data_str)
                if ev.get("type") == "agent_done":
                    done_event = ev

            assert done_event is not None, "agent_done não foi emitido!"
            print(f"[Done Event 1] patch: {done_event.get('patch')}")
            print(f"[Done Event 1] patch_type: {done_event.get('patch_type')}")
            print(f"[Done Event 1] summary: {done_event.get('summary')[:100]}...")

            # Para pergunta, NÃO deve haver patch de código
            assert done_event.get("patch") is None or done_event.get("patch") == ""
            assert done_event.get("patch_type") == "none"
            # O summary deve ser uma explicação em português
            assert len(done_event.get("summary", "")) > 10
            # NUNCA deve vazar raciocínio do modelo no patch
            if done_event.get("patch"):
                assert "The user is asking" not in done_event["patch"]

        # -------------------------------------------------------------------
        # TESTE 2: Edição Cirúrgica de Elemento Alvo
        # -------------------------------------------------------------------
        print("\n--- TESTE 2: Edição Cirúrgica de Elemento ---")
        async with client.stream(
            "POST",
            "/api/ai/agent/stream",
            headers=stream_headers,
            json={
                "prompt": "Mude a cor do botão para verde-esmeralda e altere o texto para 'Garantir Vaga'",
                "current_html": "<section class='p-8'><button data-mb-id='btn-cta' class='bg-blue-600 text-white px-4 py-2 rounded'>Começar</button></section>",
                "target_element": {
                    "mbId": "btn-cta",
                    "tag": "button",
                    "selector": "#btn-cta",
                    "outerHtml": "<button data-mb-id='btn-cta' class='bg-blue-600 text-white px-4 py-2 rounded'>Começar</button>"
                },
                "model_name": "bonsai-27b"
            }
        ) as res_surg:
            assert res_surg.status_code == 200
            done_event2 = None
            tools_called = []
            async for line in res_surg.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line.replace("data:", "").strip()
                if not data_str:
                    continue
                ev = json.loads(data_str)
                if ev.get("type") == "tool_call":
                    tools_called.append(ev.get("tool"))
                if ev.get("type") == "agent_done":
                    done_event2 = ev

            assert done_event2 is not None, "agent_done não foi emitido no teste cirúrgico!"
            print(f"[Done Event 2] patch: {done_event2.get('patch')}")
            print(f"[Done Event 2] patch_type: {done_event2.get('patch_type')}")
            print(f"[Done Event 2] target_selector: {done_event2.get('target_selector')}")
            print(f"[Done Event 2] tools: {tools_called}")

            assert done_event2.get("patch_type") == "element"
            patch = done_event2.get("patch") or ""
            assert "<button" in patch
            assert "data-mb-id=" in patch
            # Não deve conter a página inteira
            assert "<!DOCTYPE" not in patch
            assert "<html" not in patch
            # NUNCA vazar raciocínio do modelo no patch
            assert "The user is asking" not in patch

        # -------------------------------------------------------------------
        # TESTE 3: Conserto de Layout ("O layout tá quebrado, poderia ver para concertar?")
        # -------------------------------------------------------------------
        print("\n--- TESTE 3: Conserto de Layout ---")
        async with client.stream(
            "POST",
            "/api/ai/agent/stream",
            headers=stream_headers,
            json={
                "prompt": "O layout tá quebrado, poderia ver para concertar?",
                "current_html": "<div class='flex'><div class='w-full'>Card 1</div><div>Card 2</div>",
                "model_name": "bonsai-27b"
            }
        ) as res_repair:
            assert res_repair.status_code == 200
            done_event3 = None
            async for line in res_repair.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line.replace("data:", "").strip()
                if not data_str:
                    continue
                ev = json.loads(data_str)
                if ev.get("type") == "agent_done":
                    done_event3 = ev

            assert done_event3 is not None
            print(f"[Done Event 3] summary: {done_event3.get('summary')[:100]}...")
            print(f"[Done Event 3] patch len: {len(done_event3.get('patch') or '')}")
            print(f"[Done Event 3] patch_type: {done_event3.get('patch_type')}")

            # Se gerou patch de correção, deve ser HTML válido e SEM vazamento de raciocínio
            if done_event3.get("patch"):
                assert "<" in done_event3["patch"] and ">" in done_event3["patch"]
                assert "The user is asking" not in done_event3["patch"]
                assert "noise overlay div" not in done_event3["patch"]

