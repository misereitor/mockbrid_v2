import io
import os
import secrets
import zipfile
import pytest
import httpx

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")


@pytest.mark.asyncio
async def test_mcp_token_authorizes_standard_rest_and_batch_endpoints():
    """Valida que o token MCP autentica rotas REST normais (PUT/GET /api/screens) e endpoints de lote."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Registrar usuário
        email = f"batch_user_{secrets.token_hex(4)}@empresa.com"
        reg = await client.post("/api/auth/register", json={
            "email": email,
            "password": "Password123!",
            "name": "Batch User Tester",
            "organization_name": f"Org Batch {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf

        # 2. Criar projeto e telas iniciais
        proj_res = await client.post("/api/projects", json={
            "name": "Projeto Batch & MCP REST",
            "description": "Teste de autenticação REST com chave MCP e batch update"
        })
        assert proj_res.status_code == 200
        project_id = proj_res.json()["id"]

        s1_res = await client.post(f"/api/projects/{project_id}/screens", json={
            "name": "Dashboard",
            "html_content": "<h1>Dashboard Inicial</h1>",
            "viewport": "desktop"
        })
        assert s1_res.status_code == 200
        s1_id = s1_res.json()["id"]

        s2_res = await client.post(f"/api/projects/{project_id}/screens", json={
            "name": "Kanban",
            "html_content": "<h1>Kanban Inicial</h1>",
            "viewport": "desktop"
        })
        assert s2_res.status_code == 200
        s2_id = s2_res.json()["id"]

        # 3. Gerar chave MCP para o projeto
        key_res = await client.post("/api/mcp/keys", json={
            "name": "Chave MCP REST Agent",
            "project_ids": [project_id],
            "scopes": ["project:read", "project:write", "screen:read", "screen:write"]
        })
        assert key_res.status_code == 200
        raw_mcp_key = key_res.json()["raw_key"]
        mcp_auth_headers = {"Authorization": f"Bearer {raw_mcp_key}"}

        # 4. TESTE CRUCIAL: Usar o token MCP como Bearer em cliente HTTP puro sem cookies (simulando script local do agente)
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as mcp_client:
            # 4.1 GET /api/screens/{id} deve retornar 200 OK (resolvendo a reclamação do 401!)
            get_screen_res = await mcp_client.get(f"/api/screens/{s1_id}", headers=mcp_auth_headers)
            if get_screen_res.status_code != 200:
                print("ERRO GET SCREEN:", get_screen_res.status_code, get_screen_res.text)
            assert get_screen_res.status_code == 200
            assert get_screen_res.json()["name"] == "Dashboard"

            # 4.2 PUT /api/screens/{id} enviando HTML direto (resolvendo envio direto de arquivo via script!)
            new_html_content = "<div class='kanban-board'><p>Kanban Atualizado via REST com Chave MCP</p></div>"
            put_screen_res = await mcp_client.put(
                f"/api/screens/{s2_id}",
                headers=mcp_auth_headers,
                json={"html_content": new_html_content}
            )
            assert put_screen_res.status_code == 200
            assert put_screen_res.json()["html_content"] == new_html_content

            # 4.3 PUT /api/screens/project/{id}/batch - Atualização de múltiplas telas em lote via REST
            batch_rest_res = await mcp_client.put(
                f"/api/screens/project/{project_id}/batch",
                headers=mcp_auth_headers,
                json={
                    "screens": [
                        {
                            "screen_id": s1_id,
                            "html_content": "<div class='dash'>Dashboard via Batch REST</div>"
                        },
                        {
                            "screen_name": "Contatos",  # Criará nova tela no lote
                            "html_content": "<div class='contacts'>Lista de Contatos</div>",
                            "viewport": "desktop"
                        }
                    ]
                }
            )
            assert batch_rest_res.status_code == 200
            batch_data = batch_rest_res.json()
            assert batch_data["status"] == "success"
            assert len(batch_data["updated_screens"]) == 1
            assert len(batch_data["created_screens"]) == 1

            # 4.4 MCP JSON-RPC 2.0 tool: batch_update_screens
            mcp_rpc_res = await mcp_client.post(
                "/mcp",
                headers=mcp_auth_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 201,
                    "method": "tools/call",
                    "params": {
                        "name": "batch_update_screens",
                        "arguments": {
                            "project_id": project_id,
                            "screens": [
                                {
                                    "screen_id": s2_id,
                                    "html_content": "<div class='kanban'>Kanban via MCP Batch Tool</div>"
                                }
                            ]
                        }
                    }
                }
            )
            assert mcp_rpc_res.status_code == 200
            rpc_body = mcp_rpc_res.json()
            assert "result" in rpc_body
            assert "updated_screens" in rpc_body["result"]["content"][0]["text"]

        # 5. TESTE: Importação de ZIP em projeto existente (atualizando em vez de criar novo)
        # Cria ZIP em memória no formato corpus design/
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("design/tokens.css", ":root { --color-primary: #10b981; }")
            zf.writestr("design/Principal/Dashboard.html", "<div class='dash-zip'>Dashboard atualizado via ZIP</div>")
        zip_buf.seek(0)

        import_zip_res = await client.post(
            f"/api/projects/{project_id}/import/design",
            files={"file": ("design_update.zip", zip_buf.getvalue(), "application/zip")},
            data={"project_id": project_id}
        )
        assert import_zip_res.status_code == 200
        import_data = import_zip_res.json()
        assert import_data["project"]["id"] == project_id  # Mantém o mesmo projeto!

        # Confirma que a tela Dashboard foi atualizada pelo ZIP
        check_screen = await client.get(f"/api/screens/{s1_id}")
        assert check_screen.status_code == 200
        assert "Dashboard atualizado via ZIP" in check_screen.json()["html_content"]
