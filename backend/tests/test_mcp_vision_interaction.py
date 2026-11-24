import os
import secrets
import pytest
import httpx

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_mcp_render_screenshot_and_interaction():
    """Valida as ferramentas MCP de renderização headless e interação remota com comprovação visual."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Registrar usuário e obter cookies/auth
        email = f"mcp_vision_{secrets.token_hex(4)}@empresa.com"
        reg = await client.post("/api/auth/register", json={
            "email": email,
            "password": "Password123!",
            "name": "MCP Vision Tester",
            "organization_name": f"Org Vision {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf

        # 2. Criar projeto e tela com elementos interativos e mock navigation
        proj_res = await client.post("/api/projects", json={
            "name": "Projeto Visual MCP",
            "description": "Teste de equivalência visual e cliques"
        })
        assert proj_res.status_code == 200
        proj_data = proj_res.json()
        project_id = proj_data["id"]

        sample_html = """
        <div class="p-8 max-w-md mx-auto bg-slate-900 rounded-xl shadow-md text-white">
          <h1 data-mb-id="title-heading" class="text-2xl font-bold mb-4">Painel de Controle</h1>
          <p id="status-text" class="text-slate-400 mb-6">Aguardando ação...</p>
          <button
            data-mb-id="btn-login"
            data-mb-nav="dashboard"
            onclick="document.getElementById('status-text').innerText = 'Acesso Autorizado!'; document.body.className = 'logged-in bg-emerald-950';"
            class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded font-medium"
          >
            Entrar no Sistema
          </button>
        </div>
        """

        screen_res = await client.post(f"/api/projects/{project_id}/screens", json={
            "name": "Tela Interativa",
            "html_content": sample_html,
            "viewport": "desktop"
        })
        assert screen_res.status_code == 200
        screen_id = screen_res.json()["id"]

        # 3. Criar chave MCP associada ao projeto
        key_res = await client.post("/api/mcp/keys", json={
            "name": "Chave MCP Vision",
            "project_ids": [project_id],
            "scopes": ["project:read", "screen:read", "screen:write"]
        })
        assert key_res.status_code == 200
        raw_key = key_res.json()["raw_key"]
        mcp_headers = {"Authorization": f"Bearer {raw_key}"}

        # 4. Testar Endpoint REST de Renderização de Screenshot: POST /mcp/tools/render_screen_screenshot
        shot_res = await client.post(
            "/mcp/tools/render_screen_screenshot",
            headers=mcp_headers,
            json={
                "screen_id": screen_id,
                "viewport": "desktop",
                "theme": "dark",
                "full_page": False
            }
        )
        assert shot_res.status_code == 200
        shot_data = shot_res.json()
        assert shot_data["screen_id"] == screen_id
        assert shot_data["viewport"] == "desktop"
        assert shot_data["theme"] == "dark"
        assert shot_data["width"] == 1440
        assert shot_data["size_bytes"] > 1000
        assert "image_base64" in shot_data
        assert shot_data["image_data_uri"].startswith("data:image/png;base64,")

        # 5. Testar Endpoint REST de Interação Remota: POST /mcp/tools/interact_screen_element
        interact_res = await client.post(
            "/mcp/tools/interact_screen_element",
            headers=mcp_headers,
            json={
                "screen_id": screen_id,
                "element_mb_id": "btn-login",
                "action": "click",
                "capture_screenshot": True
            }
        )
        assert interact_res.status_code == 200
        interact_data = interact_res.json()
        assert interact_data["status"] == "success"
        assert interact_data["action"] == "click"
        assert interact_data["target"]["has_onclick"] is True
        assert interact_data["target"]["nav_destination"] == "dashboard"
        assert interact_data["dom_effects"]["navigation_triggered"] is True
        assert interact_data["dom_effects"]["navigation_target"] == "dashboard"
        assert "logged-in" in interact_data["dom_effects"]["body_classes"]
        assert interact_data["screenshot_base64"] is not None

        # 6. Testar Protocolo JSON-RPC 2.0 padrão (/mcp) com render_screen_screenshot
        rpc_shot_payload = {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/call",
            "params": {
                "name": "render_screen_screenshot",
                "arguments": {
                    "screen_id": screen_id,
                    "viewport": "mobile",
                    "theme": "light"
                }
            }
        }
        rpc_shot_res = await client.post("/mcp", headers=mcp_headers, json=rpc_shot_payload)
        assert rpc_shot_res.status_code == 200
        rpc_shot_data = rpc_shot_res.json()
        assert rpc_shot_data["id"] == 101
        assert "result" in rpc_shot_data
        content = rpc_shot_data["result"]["content"]
        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image"
        assert content[1]["mimeType"] == "image/png"
        assert len(content[1]["data"]) > 500

        # 7. Testar Protocolo JSON-RPC 2.0 padrão (/mcp) com interact_screen_element
        rpc_act_payload = {
            "jsonrpc": "2.0",
            "id": 102,
            "method": "tools/call",
            "params": {
                "name": "interact_screen_element",
                "arguments": {
                    "screen_id": screen_id,
                    "element_mb_id": "btn-login",
                    "action": "click",
                    "capture_screenshot": True
                }
            }
        }
        rpc_act_res = await client.post("/mcp", headers=mcp_headers, json=rpc_act_payload)
        assert rpc_act_res.status_code == 200
        rpc_act_data = rpc_act_res.json()
        assert rpc_act_data["id"] == 102
        assert "result" in rpc_act_data
        act_content = rpc_act_data["result"]["content"]
        assert any(c["type"] == "image" for c in act_content)
        assert any(c["type"] == "text" and "dashboard" in c["text"] for c in act_content)
