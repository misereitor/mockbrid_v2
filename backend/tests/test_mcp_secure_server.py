import pytest
import httpx
import secrets
import os
import json

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_secure_mcp_api_keys_and_jsonrpc_protocol():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Registra usuário e cria projeto
        email = f"mcp_tester_{secrets.token_hex(4)}@empresa.com"
        pwd = "PassMcpSec123!"
        reg = await client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": pwd,
                "name": "MCP Tester",
                "organization_name": f"Org MCP {secrets.token_hex(3)}",
            },
        )
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        # Cria projeto
        proj_res = await client.post(
            "/api/projects",
            json={
                "name": "Projeto com MCP",
                "description": "Projeto para teste de agentes externos",
            },
            headers=headers,
        )
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
        up_screen = await client.put(
            f"/api/screens/{screen_id}",
            json={"html_content": initial_html},
            headers=headers,
        )
        assert up_screen.status_code == 200

        # 2. Rejeição de chamada sem autenticação no MCP -> 401
        no_auth = await client.post(f"/mcp/tools/get_project_map?project_id={proj_id}")
        assert (
            no_auth.status_code == 401
        ), f"Sem auth deve dar 401: {no_auth.status_code}"

        # 3. Rejeição de token JWT de sessão de usuário nas rotas MCP -> 401
        user_jwt = client.cookies.get("mockbird_token")
        bad_jwt_res = await client.post(
            f"/mcp/tools/get_project_map?project_id={proj_id}",
            headers={"Authorization": f"Bearer {user_jwt}"},
        )
        assert (
            bad_jwt_res.status_code == 401
        ), "JWT de usuário não deve ser aceito no servidor MCP"
        assert (
            "tokens de sessão de usuário não são aceitos"
            in bad_jwt_res.json()["detail"].lower()
        )

        # 4. Gera uma chave MCP real (mb_live_...) vinculada ao projeto
        key_res = await client.post(
            "/api/mcp/keys",
            json={
                "name": "Cursor Agent Chave",
                "project_id": proj_id,
                "scopes": ["project:read", "screen:write", "export:read"],
            },
            headers=headers,
        )
        assert key_res.status_code == 200, key_res.text
        key_data = key_res.json()
        mcp_key_id = key_data["id"]
        raw_mcp_key = key_data["raw_key"]
        assert raw_mcp_key.startswith("mb_live_")

    # 5. Agente Externo conecta usando a chave MCP
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=25.0) as mcp_client:
        mcp_headers = {"Authorization": f"Bearer {raw_mcp_key}"}

        # A. Handshake JSON-RPC 'initialize'
        init_res = await mcp_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers=mcp_headers,
        )
        assert init_res.status_code == 200
        init_data = init_res.json()
        assert init_data["result"]["serverInfo"]["name"] == "mockbird-mcp-server"

        # B. Listagem de ferramentas JSON-RPC 'tools/list' (validação das 14 ferramentas nativas)
        tools_res = await mcp_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers=mcp_headers,
        )
        assert tools_res.status_code == 200
        tools_list = tools_res.json()["result"]["tools"]
        tool_names = [t["name"] for t in tools_list]

        expected_tools = [
            "list_projects",
            "get_project_map",
            "get_screen",
            "create_screen",
            "duplicate_screen",
            "delete_screen",
            "patch_screen_element",
            "update_screen_html",
            "update_design_tokens",
            "list_project_assets",
            "list_scenarios",
            "set_scenario_data",
            "validate_screen_html",
            "get_implementation_bundle",
        ]
        for exp in expected_tools:
            assert exp in tool_names, f"Ferramenta '{exp}' ausente do catálogo MCP"

        # C. Execução de 'list_projects'
        lp_res = await mcp_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "list_projects", "arguments": {}},
            },
            headers=mcp_headers,
        )
        assert lp_res.status_code == 200
        lp_data = json.loads(lp_res.json()["result"]["content"][0]["text"])
        assert len(lp_data) >= 1
        assert lp_data[0]["id"] == proj_id

        # D. Execução de 'get_screen'
        gs_res = await mcp_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "get_screen", "arguments": {"screen_id": screen_id}},
            },
            headers=mcp_headers,
        )
        assert gs_res.status_code == 200
        gs_data = json.loads(gs_res.json()["result"]["content"][0]["text"])
        assert gs_data["id"] == screen_id
        assert "btn-checkout" in gs_data["html_content"]

        # E. Execução de 'validate_screen_html'
        # 1. HTML Válido
        val_res = await mcp_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "validate_screen_html",
                    "arguments": {
                        "html_content": "<div class='card'><button data-mb-id='btn-action'>Clique</button></div>"
                    },
                },
            },
            headers=mcp_headers,
        )
        assert val_res.status_code == 200
        val_data = json.loads(val_res.json()["result"]["content"][0]["text"])
        assert val_data["valid"] is True
        assert "btn-action" in val_data["elements_with_mb_id"]

        # 2. HTML com erro sintático (tag não fechada)
        val_err_res = await mcp_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "validate_screen_html",
                    "arguments": {
                        "html_content": "<div class='broken'><span>Sem fechar span</div>"
                    },
                },
            },
            headers=mcp_headers,
        )
        assert val_err_res.status_code == 200
        val_err_data = json.loads(val_err_res.json()["result"]["content"][0]["text"])
        assert val_err_data["valid"] is False
        assert len(val_err_data["errors"]) > 0

        # F. Execução de 'create_screen'
        cs_res = await mcp_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "create_screen",
                    "arguments": {
                        "project_id": proj_id,
                        "name": "Tela de Perfil MCP",
                        "html_content": "<div class='p-6'><h2 data-mb-id='user-name'>Carlos Silva</h2></div>",
                    },
                },
            },
            headers=mcp_headers,
        )
        assert cs_res.status_code == 200
        cs_data = json.loads(cs_res.json()["result"]["content"][0]["text"])
        assert cs_data["status"] == "success"
        created_screen_id = cs_data["screen"]["id"]

        # G. Execução de 'duplicate_screen'
        dup_res = await mcp_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "duplicate_screen",
                    "arguments": {
                        "screen_id": created_screen_id,
                        "new_name": "Tela de Perfil MCP Cópia",
                    },
                },
            },
            headers=mcp_headers,
        )
        assert dup_res.status_code == 200
        dup_data = json.loads(dup_res.json()["result"]["content"][0]["text"])
        assert dup_data["status"] == "success"
        dup_screen_id = dup_data["new_screen"]["id"]

        # H. Execução de 'delete_screen' (exclui a tela duplicada)
        del_screen_res = await mcp_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "delete_screen",
                    "arguments": {"screen_id": dup_screen_id},
                },
            },
            headers=mcp_headers,
        )
        assert del_screen_res.status_code == 200
        del_screen_data = json.loads(
            del_screen_res.json()["result"]["content"][0]["text"]
        )
        assert del_screen_data["status"] == "success"

        # I. Execução de 'update_design_tokens'
        tok_res = await mcp_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "update_design_tokens",
                    "arguments": {
                        "project_id": proj_id,
                        "light_tokens": {"colors": {"primary": "#0066FF"}},
                        "dark_tokens": {"colors": {"primary": "#3388FF"}},
                    },
                },
            },
            headers=mcp_headers,
        )
        assert tok_res.status_code == 200
        tok_data = json.loads(tok_res.json()["result"]["content"][0]["text"])
        assert tok_data["status"] == "success"
        assert tok_data["tokens"]["light"]["colors"]["primary"] == "#0066FF"

        # J. Execução de 'set_scenario_data' e 'list_scenarios'
        set_scen = await mcp_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "set_scenario_data",
                    "arguments": {
                        "project_id": proj_id,
                        "name": "Cenário MCP VIP",
                        "mock_data": {"saldo": 15000, "plano": "Enterprise"},
                    },
                },
            },
            headers=mcp_headers,
        )
        assert set_scen.status_code == 200

        list_scen = await mcp_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {"name": "list_scenarios", "arguments": {"project_id": proj_id}},
            },
            headers=mcp_headers,
        )
        assert list_scen.status_code == 200
        scen_data = json.loads(list_scen.json()["result"]["content"][0]["text"])
        assert any(s["name"] == "Cenário MCP VIP" for s in scen_data)

        # K. Execução de 'list_project_assets'
        assets_res = await mcp_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {
                    "name": "list_project_assets",
                    "arguments": {"project_id": proj_id},
                },
            },
            headers=mcp_headers,
        )
        assert assets_res.status_code == 200
        assets_data = json.loads(assets_res.json()["result"]["content"][0]["text"])
        assert isinstance(assets_data, list)

        # L. Execução de 'patch_screen_element'
        patch_res = await mcp_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 14,
                "method": "tools/call",
                "params": {
                    "name": "patch_screen_element",
                    "arguments": {
                        "screen_id": screen_id,
                        "element_mb_id": "btn-checkout",
                        "new_html_snippet": "<button data-mb-id='btn-checkout' class='bg-emerald-600 text-white font-bold px-6 py-3 rounded-xl shadow-lg'>Finalizar Pedido Agora</button>",
                        "change_summary": "Botão de checkout aprimorado com design token esmeralda",
                    },
                },
            },
            headers=mcp_headers,
        )
        assert patch_res.status_code == 200
        patch_data = patch_res.json()
        assert "Finalizar Pedido Agora" in str(patch_data)

        # M. Execução de 'update_screen_html'
        full_up_res = await mcp_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 15,
                "method": "tools/call",
                "params": {
                    "name": "update_screen_html",
                    "arguments": {
                        "screen_id": screen_id,
                        "html_content": "<div class='container'><h1 data-mb-id='full-update'>Título Atualizado Completo</h1></div>",
                        "change_summary": "Revisão geral da tela via MCP",
                    },
                },
            },
            headers=mcp_headers,
        )
        assert full_up_res.status_code == 200
        full_up_data = json.loads(full_up_res.json()["result"]["content"][0]["text"])
        assert full_up_data["status"] == "success"

        # N. Execução de 'get_implementation_bundle'
        bundle_res = await mcp_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 16,
                "method": "tools/call",
                "params": {
                    "name": "get_implementation_bundle",
                    "arguments": {"screen_id": screen_id},
                },
            },
            headers=mcp_headers,
        )
        assert bundle_res.status_code == 200
        bundle_data = json.loads(bundle_res.json()["result"]["content"][0]["text"])
        assert "react_jsx" in bundle_data
        assert "Título Atualizado Completo" in bundle_data["react_jsx"]

    # 6. Verifica no app que a revisão foi salva com o autor da chave MCP
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as verify_client:
        await verify_client.post(
            "/api/auth/login", json={"email": email, "password": pwd}
        )
        v_csrf = verify_client.cookies.get("mockbird_csrf")
        v_headers = {"X-CSRF-Token": v_csrf} if v_csrf else {}

        rev_res = await verify_client.get(
            f"/api/screens/{screen_id}/revisions", headers=v_headers
        )
        assert rev_res.status_code == 200
        revs = rev_res.json()
        latest_rev = revs[0]
        assert latest_rev["actor"] == "mcp:Cursor Agent Chave"
        assert "Título Atualizado Completo" in latest_rev["html_content"]

        # 7. Revogação de chave MCP
        del_key = await verify_client.delete(
            f"/api/mcp/keys/{mcp_key_id}", headers=v_headers
        )
        assert del_key.status_code == 200

    # 8. Chave revogada é rejeitada imediatamente -> 401
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as revoked_client:
        revoked_call = await revoked_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/list",
                "params": {},
            },
            headers={"Authorization": f"Bearer {raw_mcp_key}"},
        )
        assert (
            revoked_call.status_code == 401
        ), f"Chave revogada deve dar 401: {revoked_call.status_code}"
