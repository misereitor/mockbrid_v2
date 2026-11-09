import os
import pytest
import httpx

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_api_health():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        res = await client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["service"] == "Mockbird v2"
        assert data["environment"] == "homologation"


@pytest.mark.asyncio
async def test_auth_and_project_flow():
    import secrets
    random_email = f"user_{secrets.token_hex(4)}@mockbird.dev"
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # 1. Registro
        reg_res = await client.post("/api/auth/register", json={
            "name": "QA Tester",
            "email": random_email,
            "password": "senha_forte_123",
            "organization_name": "Empresa QA"
        })
        assert reg_res.status_code == 200
        user_data = reg_res.json()
        assert user_data["email"] == random_email

        # 2. Login
        login_res = await client.post("/api/auth/login", json={
            "email": random_email,
            "password": "senha_forte_123"
        })
        assert login_res.status_code == 200
        cookies = login_res.cookies
        csrf_token = cookies.get("mockbird_csrf")
        csrf_headers = {"X-CSRF-Token": csrf_token} if csrf_token else {}

        # 2.1 Teste de Proteção CSRF: mutação com cookie mas SEM X-CSRF-Token deve falhar com 403
        attack_res = await client.post("/api/projects", json={
            "name": "Projeto CSRF Attack",
            "description": "Tentativa forjada"
        }, cookies=cookies)
        assert attack_res.status_code == 403, "API deve bloquear mutação com cookie sem header CSRF"

        # 3. Criação de Projeto Legítima (com cookie + cabeçalho CSRF)
        proj_res = await client.post("/api/projects", json={
            "name": "Projeto Teste E2E",
            "description": "Validação de Homologação"
        }, cookies=cookies, headers=csrf_headers)
        assert proj_res.status_code == 200
        proj_data = proj_res.json()
        assert proj_data["name"] == "Projeto Teste E2E"
        assert proj_data["entry_screen_id"] is not None

        # 4. Verificação de Tokens do Projeto
        proj_id = proj_data["id"]
        tokens_res = await client.get(f"/api/tokens/{proj_id}", cookies=cookies)
        assert tokens_res.status_code == 200
        tokens_data = tokens_res.json()
        assert "color-primary" in tokens_data["light_tokens"]
        assert "color-primary" in tokens_data["dark_tokens"]

        # 5. MCP Tools: get_project_map (agora protegido por autenticação e isolado por tenant)
        mcp_res = await client.post(
            f"/mcp/tools/get_project_map?project_id={proj_id}",
            cookies=cookies,
            headers=csrf_headers
        )
        assert mcp_res.status_code == 200
        mcp_data = mcp_res.json()
        assert mcp_data["project"]["id"] == proj_id
        assert len(mcp_data["canvases"]) > 0
        screen_id = mcp_data["canvases"][0]["screens"][0]["id"]

        # 6. MCP Tools: get_implementation_bundle (protegido por autenticação)
        bundle_res = await client.post(
            f"/mcp/tools/get_implementation_bundle?screen_id={screen_id}",
            cookies=cookies,
            headers=csrf_headers
        )
        assert bundle_res.status_code == 200
        bundle_data = bundle_res.json()
        assert "react_jsx" in bundle_data
        assert "export function" in bundle_data["react_jsx"]


@pytest.mark.asyncio
async def test_mcp_info():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        res = await client.get("/mcp/info")
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "mockbird-mcp-server"
        assert len(data["tools"]) == 3
