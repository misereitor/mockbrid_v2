import io
import os
import base64
import secrets
import zipfile
import pytest
import httpx

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_mcp_advanced_feedback_suite():
    """Valida todas as ferramentas e otimizações criadas a partir do feedback do agente MCP."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=40.0) as client:
        # 1. Registrar usuário e obter cookies/CSRF
        email = f"adv_agent_{secrets.token_hex(4)}@empresa.com"
        reg = await client.post("/api/auth/register", json={
            "email": email,
            "password": "Password123!",
            "name": "Advanced MCP Agent Tester",
            "organization_name": f"Org Adv {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf

        # 2. Criar projeto de teste
        proj_res = await client.post("/api/projects", json={
            "name": "Projeto Feedback Suite",
            "description": "Validação de render_state, restore_revision, diagnose, validate e import_zip"
        })
        assert proj_res.status_code == 200
        project_id = proj_res.json()["id"]

        # Criar tela com revisão inicial
        s_res = await client.post(f"/api/projects/{project_id}/screens", json={
            "name": "Tela Chat Principal",
            "html_content": """
            <div id='chat-app' class='p-4'>
                <h1 id='title'>Canal Geral</h1>
                <button id='toggle-btn' data-action='toggle-group' class='btn-group'>Abrir Grupo</button>
                <div id='group-panel' class='hidden group-content'>Membros do Grupo</div>
            </div>
            """,
            "viewport": "desktop"
        })
        assert s_res.status_code == 200
        screen_id = s_res.json()["id"]

        # 3. Gerar chave MCP
        key_res = await client.post("/api/mcp/keys", json={
            "name": "Chave MCP Advanced Suite",
            "project_ids": [project_id],
            "scopes": ["project:read", "project:write", "screen:read", "screen:write"]
        })
        assert key_res.status_code == 200
        raw_key = key_res.json()["raw_key"]
        mcp_headers = {"Authorization": f"Bearer {raw_key}"}

        # 4. MCP JSON-RPC: Testar get_project_map com summary_only=True e include_tokens=False
        rpc_map = await client.post("/mcp", headers=mcp_headers, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_project_map",
                "arguments": {
                    "project_id": project_id,
                    "summary_only": True,
                    "include_tokens": False
                }
            }
        })
        assert rpc_map.status_code == 200
        map_body = rpc_map.json()["result"]["content"][0]["text"]
        import json
        map_data = json.loads(map_body)
        assert "tokens" not in map_data
        assert len(map_data["canvases"]) > 0
        assert any(s["id"] == screen_id for c in map_data["canvases"] for s in c["screens"])

        # 5. MCP JSON-RPC: Testar get_screen com include_html=False e fields selecionados
        rpc_screen_filter = await client.post("/mcp", headers=mcp_headers, json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_screen",
                "arguments": {
                    "screen_id": screen_id,
                    "fields": ["id", "name", "current_revision"]
                }
            }
        })
        assert rpc_screen_filter.status_code == 200
        screen_filter_data = json.loads(rpc_screen_filter.json()["result"]["content"][0]["text"])
        assert set(screen_filter_data.keys()) == {"id", "name", "current_revision"}
        assert screen_filter_data["current_revision"] == 1

        # 6. Atualizar a tela gerando revisão 2
        update_res = await client.post("/mcp", headers=mcp_headers, json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "update_screen_html",
                "arguments": {
                    "screen_id": screen_id,
                    "html_content": "<div class='rev-2'>Conteúdo da Revisão 2</div>",
                    "change_summary": "Alteração para revisão 2"
                }
            }
        })
        assert update_res.status_code == 200

        # 7. MCP JSON-RPC: Testar restore_screen_revision para voltar para revisão 1
        restore_res = await client.post("/mcp", headers=mcp_headers, json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "restore_screen_revision",
                "arguments": {
                    "screen_id": screen_id,
                    "revision": 1
                }
            }
        })
        assert restore_res.status_code == 200
        print("RESTORE RES BODY:", restore_res.json())
        restore_data = json.loads(restore_res.json()["result"]["content"][0]["text"])
        assert restore_data["status"] == "success"
        assert restore_data["restored_from_revision"] == 1
        assert restore_data["new_current_revision"] == 3

        # Confirma que o HTML voltou ao da revisão 1
        check_screen = await client.post("/mcp", headers=mcp_headers, json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "get_screen",
                "arguments": {"screen_id": screen_id}
            }
        })
        screen_content = json.loads(check_screen.json()["result"]["content"][0]["text"])
        assert "toggle-btn" in screen_content["html_content"]

        # 8. MCP JSON-RPC: Testar diagnose_screen
        diag_res = await client.post("/mcp", headers=mcp_headers, json={
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "diagnose_screen",
                "arguments": {"screen_id": screen_id}
            }
        })
        assert diag_res.status_code == 200
        diag_data = json.loads(diag_res.json()["result"]["content"][0]["text"])
        assert diag_data["status"] == "success"
        assert "interactive_elements" in diag_data
        assert diag_data["interactive_elements"]["count"] >= 1
        assert diag_data["interactive_elements"]["elements"][0]["id"] == "toggle-btn"

        # 9. MCP JSON-RPC: Testar validate_screen
        val_res = await client.post("/mcp", headers=mcp_headers, json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "validate_screen",
                "arguments": {"screen_id": screen_id}
            }
        })
        assert val_res.status_code == 200
        val_data = json.loads(val_res.json()["result"]["content"][0]["text"])
        assert "overall_status" in val_data
        assert "checks" in val_data
        assert "interactivity" in val_data["checks"]
        assert val_data["checks"]["interactivity"]["has_buttons"] is True

        # 10. MCP JSON-RPC: Testar render_screen_state com sequência de ações
        state_rpc = await client.post("/mcp", headers=mcp_headers, json={
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "render_screen_state",
                "arguments": {
                    "screen_id": screen_id,
                    "actions": [
                        {"action": "click", "selector": "#toggle-btn"},
                        {"action": "wait", "ms": 100}
                    ],
                    "viewport": "desktop",
                    "theme": "light"
                }
            }
        })
        assert state_rpc.status_code == 200
        state_body = state_rpc.json()["result"]
        # Deve ter o bloco de imagem PNG e o bloco de texto explicativo
        assert any(c.get("type") == "image" for c in state_body["content"])
        state_text = [c["text"] for c in state_body["content"] if c.get("type") == "text"][0]
        state_json = json.loads(state_text)
        assert state_json["status"] == "success"
        assert len(state_json["actions_executed"]) == 2

        # 11. MCP JSON-RPC: Testar import_project_zip atualizando o projeto via base64
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("design/tokens.css", ":root { --color-primary: #6366f1; }")
            zf.writestr("design/Principal/Chat.html", "<div class='chat-updated'>Chat atualizado via MCP ZIP</div>")
        zip_buf.seek(0)
        zip_b64 = base64.b64encode(zip_buf.getvalue()).decode("ascii")

        zip_rpc = await client.post("/mcp", headers=mcp_headers, json={
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "import_project_zip",
                "arguments": {
                    "project_id": project_id,
                    "zip_base64": zip_b64,
                    "change_summary": "Importação em lote de design via Base64 ZIP"
                }
            }
        })
        print("ZIP RPC RESPONSE:", zip_rpc.json())
        assert zip_rpc.status_code == 200
        zip_res_data = json.loads(zip_rpc.json()["result"]["content"][0]["text"])
        assert zip_res_data["status"] == "success"
        assert zip_res_data["project_id"] == project_id
        assert zip_res_data["screens"] >= 1
