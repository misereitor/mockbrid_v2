import pytest
import httpx
import secrets
import os

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_ai_rbac_and_ssrf_protection():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Registra proprietário
        admin_email = f"ai_sec_admin_{secrets.token_hex(4)}@empresa.com"
        pwd = "AdminPass123!"
        reg = await client.post("/api/auth/register", json={
            "email": admin_email,
            "password": pwd,
            "name": "AI Admin",
            "organization_name": f"Org AI Sec {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        admin_headers = {"X-CSRF-Token": csrf} if csrf else {}

        # 2. Convida membro com papel 'viewer'
        viewer_email = f"ai_viewer_{secrets.token_hex(4)}@empresa.com"
        inv_res = await client.post("/api/org/members/invite", json={
            "email": viewer_email,
            "name": "Viewer IA Test",
            "role": "viewer",
            "temporary_password": pwd
        }, headers=admin_headers)
        assert inv_res.status_code == 200

        # 3. Teste Anti-SSRF: Tenta cadastrar ou testar conexão com IP de metadados de nuvem e IP interno
        ssrf_payloads = [
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://127.0.0.1:5432",  # Porta do Postgres
            "http://10.0.0.1:8080",
        ]
        for bad_url in ssrf_payloads:
            test_conn = await client.post("/api/ai/test-connection", json={
                "provider_type": "custom",
                "base_url": bad_url,
                "model_name": "test-model"
            }, headers=admin_headers)
            # Deve ser terminantemente bloqueado com 400 ou status de erro de segurança
            if test_conn.status_code == 200:
                data = test_conn.json()
                assert data.get("status") == "error" and ("ssrf" in data.get("message", "").lower() or "não permitido" in data.get("message", "").lower() or "bloqueado" in data.get("message", "").lower()), f"SSRF não bloqueado para {bad_url}: {data}"
            else:
                assert test_conn.status_code in [400, 403], f"SSRF não retornou 400/403 para {bad_url}: {test_conn.status_code}"

    # 4. Teste RBAC: Viewer tenta chamar endpoints de IA -> DEVE RETORNAR 403
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as viewer_client:
        login_res = await viewer_client.post("/api/auth/login", json={
            "email": viewer_email,
            "password": pwd
        })
        assert login_res.status_code == 200
        v_csrf = viewer_client.cookies.get("mockbird_csrf")
        v_headers = {"X-CSRF-Token": v_csrf} if v_csrf else {}

        # Viewer tenta gerar via chat tradicional
        chat_res = await viewer_client.post("/api/ai/chat", json={
            "prompt": "Gere um botão",
            "current_html": "<div></div>"
        }, headers=v_headers)
        assert chat_res.status_code == 403, f"Viewer não pode usar /api/ai/chat: {chat_res.status_code}"

        # Viewer tenta chamar agente autônomo
        agent_res = await viewer_client.post("/api/ai/agent/stream", json={
            "prompt": "Gere um botão",
            "current_html": "<div></div>"
        }, headers=v_headers)
        assert agent_res.status_code == 403, f"Viewer não pode usar /api/ai/agent/stream: {agent_res.status_code}"

        # Viewer tenta configurar provedor -> Deve falhar com 403
        prov_res = await viewer_client.post("/api/ai/providers", json={
            "provider_type": "openai",
            "default_model": "gpt-4o",
            "api_key": "sk-123"
        }, headers=v_headers)
        assert prov_res.status_code == 403, f"Viewer não pode configurar provedor: {prov_res.status_code}"

