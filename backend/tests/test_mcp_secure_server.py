import pytest
import httpx
import secrets
import os

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_secure_mcp_api_keys_and_jsonrpc_protocol():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Registra usuário e cria projeto
        email = f"mcp_tester_{secrets.token_hex(4)}@empresa.com"
        pwd = "PassMcpSec123!"
        reg = await client.post("/api/auth/register", json={
            "email": email,
            "password": pwd,
            "name": "MCP Tester",
            "organization_name": f"Org MCP {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        # Cria projeto
        proj_res = await client.post("/api/projects", json={
            "name": "Projeto com MCP",
            "description": "Projeto para teste de agentes externos"
        }, headers=headers)
        assert proj_res.status_code == 200
        proj = proj_res.json()
        proj_id = proj["id"]
        screen_id = proj["entry_screen_id"]

        # Adiciona um elemento com data-mb-id na tela principal
        initial_html = (
            "<div class='p-8'>"
            "  <h1 class='text-2xl font-bold'>Título Principal</h1>"
            "  <button data-mb-id='btn-checkout' class='bg-blue-600 text-white px-4 py-2 rounded'>Comprar</button>"
            "</div>"
        )
        up_screen = await client.put(f"/api/screens/{screen_id}", json={
            "html_content": initial_html
        }, headers=headers)
        assert up_screen.status_code == 200

        # 2. Rejeição de chamada sem autenticação no MCP -> 401
        no_auth = await client.post(f"/mcp/tools/get_project_map?project_id={proj_id}")
        assert no_auth.status_code == 401, f"Sem auth deve dar 401: {no_auth.status_code}"

        # 3. Rejeição de token JWT de sessão de usuário nas rotas MCP -> 401
        # O cliente 'client' possui o cookie/token JWT de sessão. Passar Bearer com jwt comum deve ser rejeitado
        user_jwt = client.cookies.get("mockbird_token")
        bad_jwt_res = await client.post(
            f"/mcp/tools/get_project_map?project_id={proj_id}",
            headers={"Authorization": f"Bearer {user_jwt}"}
        )
        assert bad_jwt_res.status_code == 401, "JWT de usuário não deve ser aceito no servidor MCP"
        assert "tokens de sessão de usuário não são aceitos" in bad_jwt_res.json()["detail"].lower()

        # 4. Gera uma chave MCP real (mb_live_...) vinculada ao projeto
        key_res = await client.post("/api/mcp/keys", json={
            "name": "Cursor Agent Chave",
            "project_id": proj_id,
            "scopes": ["project:read", "screen:write", "export:read"]
        }, headers=headers)
        assert key_res.status_code == 200, key_res.text
        key_data = key_res.json()
        mcp_key_id = key_data["id"]
        raw_mcp_key = key_data["raw_key"]
        assert raw_mcp_key.startswith("mb_live_")

    # 5. Agente Externo conecta usando a chave MCP
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as mcp_client:
        mcp_headers = {"Authorization": f"Bearer {raw_mcp_key}"}

        # A. Handshake JSON-RPC 'initialize'
        init_res = await mcp_client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {}
        }, headers=mcp_headers)
        assert init_res.status_code == 200
        init_data = init_res.json()
        assert init_data["result"]["serverInfo"]["name"] == "mockbird-mcp-server"

        # B. Listagem de ferramentas JSON-RPC 'tools/list'
        tools_res = await mcp_client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }, headers=mcp_headers)
        assert tools_res.status_code == 200
        tools_list = tools_res.json()["result"]["tools"]
        tool_names = [t["name"] for t in tools_list]
        assert "get_project_map" in tool_names
        assert "patch_screen_element" in tool_names
        assert "get_implementation_bundle" in tool_names

        # C. Execução da tool 'patch_screen_element' via JSON-RPC
        patch_res = await mcp_client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "patch_screen_element",
                "arguments": {
                    "screen_id": screen_id,
                    "element_mb_id": "btn-checkout",
                    "new_html_snippet": "<button data-mb-id='btn-checkout' class='bg-emerald-600 text-white font-bold px-6 py-3 rounded-xl shadow-lg'>Finalizar Pedido Agora</button>",
                    "change_summary": "Botão de checkout aprimorado com design token esmeralda"
                }
            }
        }, headers=mcp_headers)
        assert patch_res.status_code == 200
        patch_data = patch_res.json()
        assert "Finalizar Pedido Agora" in str(patch_data)

    # 6. Verifica no app que a revisão foi salva com o autor da chave MCP
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as verify_client:
        # Login como o usuário
        await verify_client.post("/api/auth/login", json={"email": email, "password": pwd})
        v_csrf = verify_client.cookies.get("mockbird_csrf")
        v_headers = {"X-CSRF-Token": v_csrf} if v_csrf else {}

        rev_res = await verify_client.get(f"/api/screens/{screen_id}/revisions")
        assert rev_res.status_code == 200
        revs = rev_res.json()
        latest_rev = revs[0]
        assert latest_rev["actor"] == "mcp:Cursor Agent Chave"
        assert "Finalizar Pedido Agora" in latest_rev["html_content"]

        # 7. Revogação de chave MCP
        del_key = await verify_client.delete(f"/api/mcp/keys/{mcp_key_id}", headers=v_headers)
        assert del_key.status_code == 200

    # 8. Chave revogada é rejeitada imediatamente -> 401
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as revoked_client:
        revoked_call = await revoked_client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/list",
            "params": {}
        }, headers={"Authorization": f"Bearer {raw_mcp_key}"})
        assert revoked_call.status_code == 401, f"Chave revogada deve dar 401: {revoked_call.status_code}"

