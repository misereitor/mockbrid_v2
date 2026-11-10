import os
import pytest
import httpx
import secrets
from app.crypto import encrypt_secret, decrypt_secret

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_comments_and_mcp_security_audit():
    """Valida proteção de segurança em comentários e ferramentas MCP."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client_a:
        # 1. Registra Tenant A
        email_a = f"sec_a_{secrets.token_hex(4)}@empresa.com"
        pwd = "PasswordStrong123!"
        reg_a = await client_a.post(
            "/api/auth/register",
            json={
                "email": email_a,
                "password": pwd,
                "name": "Admin Tenant A",
                "organization_name": f"Org A {secrets.token_hex(3)}",
            },
        )
        assert reg_a.status_code == 200
        cookies_a = reg_a.cookies
        csrf_a = cookies_a.get("mockbird_csrf")
        headers_a = {"X-CSRF-Token": csrf_a} if csrf_a else {}

        # 2. Cria Projeto e obtém tela em Tenant A
        proj_a = await client_a.post(
            "/api/projects",
            json={"name": "Projeto Tenant A", "description": "Dados Confidenciais"},
            cookies=cookies_a,
            headers=headers_a,
        )
        assert proj_a.status_code == 200
        proj_a_data = proj_a.json()
        proj_a_id = proj_a_data["id"]
        screen_a_id = proj_a_data["entry_screen_id"]

        # 3. Tenant A cria um comentário na sua própria tela
        com_res = await client_a.post(
            "/api/comments",
            json={
                "screen_id": screen_a_id,
                "element_mb_id": "btn-cta",
                "pin_x": 100.0,
                "pin_y": 150.0,
                "body": "Comentário Confidencial do Tenant A",
            },
            cookies=cookies_a,
            headers=headers_a,
        )
        assert com_res.status_code == 200
        comment_id = com_res.json()["id"]

    # 4. Requisições Anônimas
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as anon_client:
        # A. Listar comentários sem auth -> 401
        res_anon_com = await anon_client.get(f"/api/comments/screen/{screen_a_id}")
        assert res_anon_com.status_code == 401, "Comentários não devem ser públicos"

        # B. MCP tools sem auth -> 401
        res_anon_mcp = await anon_client.post(
            f"/mcp/tools/get_project_map?project_id={proj_a_id}"
        )
        assert res_anon_mcp.status_code == 401, "MCP project map requer autenticação"

        res_anon_bundle = await anon_client.post(
            f"/mcp/tools/get_implementation_bundle?screen_id={screen_a_id}"
        )
        assert (
            res_anon_bundle.status_code == 401
        ), "MCP implementation bundle requer autenticação"

        # C. Handshake MCP info permanece público (200)
        res_info = await anon_client.get("/mcp/info")
        assert res_info.status_code == 200

    # 5. Tentativas Cross-Tenant por Usuário B de outra organização
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client_b:
        email_b = f"sec_b_{secrets.token_hex(4)}@empresa.com"
        reg_b = await client_b.post(
            "/api/auth/register",
            json={
                "email": email_b,
                "password": pwd,
                "name": "Admin Tenant B",
                "organization_name": f"Org B {secrets.token_hex(3)}",
            },
        )
        assert reg_b.status_code == 200
        cookies_b = reg_b.cookies
        csrf_b = cookies_b.get("mockbird_csrf")
        headers_b = {"X-CSRF-Token": csrf_b} if csrf_b else {}

        # Tenant B tenta ler comentários da tela de A -> 404 (IDOR bloqueado)
        res_b_read = await client_b.get(
            f"/api/comments/screen/{screen_a_id}", cookies=cookies_b
        )
        assert res_b_read.status_code == 404

        # Tenant B tenta criar comentário na tela de A -> 404
        res_b_create = await client_b.post(
            "/api/comments",
            json={
                "screen_id": screen_a_id,
                "element_mb_id": "hack",
                "pin_x": 0.0,
                "pin_y": 0.0,
                "body": "Invasão Tenant B",
            },
            cookies=cookies_b,
            headers=headers_b,
        )
        assert res_b_create.status_code == 404

        # Tenant B tenta resolver comentário de A -> 404
        res_b_res = await client_b.patch(
            f"/api/comments/{comment_id}/resolve", cookies=cookies_b, headers=headers_b
        )
        assert res_b_res.status_code == 404

        # Tenant B tenta acessar mapa de projeto de A via MCP com cookie -> 401 (cookies rejeitados no MCP)
        res_b_mcp = await client_b.post(
            f"/mcp/tools/get_project_map?project_id={proj_a_id}",
            cookies=cookies_b,
            headers=headers_b,
        )
        assert res_b_mcp.status_code == 401

        # Tenant B cria seu próprio projeto e gera chave MCP própria
        proj_b = await client_b.post(
            "/api/projects",
            json={"name": "Projeto Tenant B", "description": "Dados do B"},
            cookies=cookies_b,
            headers=headers_b,
        )
        assert proj_b.status_code == 200
        proj_b_id = proj_b.json()["id"]

        b_key_res = await client_b.post(
            "/api/mcp/keys",
            json={"name": "B MCP Key", "project_id": proj_b_id},
            cookies=cookies_b,
            headers=headers_b,
        )
        assert b_key_res.status_code == 200
        b_raw_key = b_key_res.json()["raw_key"]

        res_b_mcp_cross = await client_b.post(
            f"/mcp/tools/get_project_map?project_id={proj_a_id}",
            headers={"Authorization": f"Bearer {b_raw_key}"},
        )
        assert res_b_mcp_cross.status_code in [403, 404]


def test_crypto_fernet_roundtrip():
    """Valida criptografia Fernet em repouso e fallback seguro para chaves legadas."""
    raw_secret = "sk-ant-api03-sample-ai-provider-token-value-987654321"
    encrypted = encrypt_secret(raw_secret)
    assert encrypted != raw_secret
    assert encrypted.startswith("gAAAAA")

    decrypted = decrypt_secret(encrypted)
    assert decrypted == raw_secret

    # Fallback seguro com chave em texto puro pré-criptografia
    legacy = "sk-legacy-test-token"
    assert decrypt_secret(legacy) == legacy
