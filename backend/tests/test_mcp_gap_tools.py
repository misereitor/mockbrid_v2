import os
import json
import base64
import secrets
import pytest
import httpx

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_mcp_gap_tools_suite():
    """Valida as novas ferramentas MCP P0/P1/P2/P3:
    - search_screens
    - get_design_tokens / export_tokens
    - get_component_library / list_components
    - compare_screens (diff estrutural e pixel diff visual)
    - list_screen_revisions
    - get_canvas / list_canvases
    - upload_asset
    - get_screen_comments / add_comment
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        email = f"mcp_gaps_{secrets.token_hex(4)}@empresa.com"
        reg = await client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "Password123!",
                "name": "MCP Gap Tools Tester",
                "organization_name": f"Org Gaps {secrets.token_hex(3)}",
            },
        )
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf

        # Criar projeto de teste
        proj_res = await client.post(
            "/api/projects",
            json={
                "name": "OmniChat Design System",
                "description": "Projeto para validação das ferramentas MCP P0-P3",
            },
        )
        assert proj_res.status_code == 200
        project_id = proj_res.json()["id"]

        # Criar telas com parciais e data-mb-id
        html_v1 = """
        <!-- PARTIAL:sidebar -->
        <aside data-mb-component="sidebar" data-mb-id="omni-sidebar" class="w-64 bg-slate-900 text-white p-4">
          <nav data-mb-id="sidebar-links">OmniChat Nav</nav>
        </aside>
        <!-- /PARTIAL:sidebar -->
        <main data-mb-id="chat-inbox" class="p-6">
          <h1 data-mb-id="inbox-title" class="text-xl font-bold">Atendimento OmniChat</h1>
          <button data-mb-component="button" data-mb-id="btn-transfer" class="px-4 py-2 bg-indigo-600 text-white rounded">
            Transferir Ticket
          </button>
        </main>
        """
        s1_res = await client.post(
            f"/api/projects/{project_id}/screens",
            json={
                "name": "Inbox Atendimento",
                "html_content": html_v1,
                "viewport": "desktop",
            },
        )
        assert s1_res.status_code == 200
        screen_id = s1_res.json()["id"]

        # Gerar chave MCP
        key_res = await client.post(
            "/api/mcp/keys",
            json={
                "name": "Chave MCP OmniChat Gaps",
                "project_ids": [project_id],
                "scopes": ["project:read", "project:write", "screen:read", "screen:write", "export:read"],
            },
        )
        assert key_res.status_code == 200
        raw_key = key_res.json()["raw_key"]
        mcp_headers = {"Authorization": f"Bearer {raw_key}"}

        # 1. Testar search_screens (por query geral e por data-mb-id)
        search_rpc = await client.post(
            "/mcp",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "search_screens",
                    "arguments": {
                        "project_id": project_id,
                        "mb_id": "btn-transfer",
                        "limit": 10,
                    },
                },
            },
        )
        assert search_rpc.status_code == 200
        search_data = json.loads(search_rpc.json()["result"]["content"][0]["text"])
        assert search_data["total_matches"] == 1
        assert search_data["screens"][0]["id"] == screen_id
        assert "btn-transfer" in search_data["screens"][0]["mb_ids_sample"]

        # 2. Atualizar e ler tokens via get_design_tokens e export_tokens
        await client.post(
            "/mcp",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "update_design_tokens",
                    "arguments": {
                        "project_id": project_id,
                        "light_tokens": {"color-primary": "#4f46e5", "color-bg": "#ffffff"},
                        "dark_tokens": {"color-primary": "#818cf8", "color-bg": "#090d16"},
                        "shared_tokens": {"radius-md": "0.5rem"},
                    },
                },
            },
        )

        tok_rpc = await client.post(
            "/mcp",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "get_design_tokens",
                    "arguments": {"project_id": project_id, "format": "all"},
                },
            },
        )
        assert tok_rpc.status_code == 200
        tok_data = json.loads(tok_rpc.json()["result"]["content"][0]["text"])
        assert tok_data["tokens"]["light"]["color-primary"] == "#4f46e5"
        assert "--color-primary: #4f46e5;" in tok_data["css_variables"]
        assert "color" in tok_data["dtcg"]["light"]

        # 3. Testar get_component_library / list_components
        comp_rpc = await client.post(
            "/mcp",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {
                    "name": "get_component_library",
                    "arguments": {"project_id": project_id, "include_presets": True},
                },
            },
        )
        assert comp_rpc.status_code == 200
        comp_data = json.loads(comp_rpc.json()["result"]["content"][0]["text"])
        assert comp_data["total_components"] >= 2
        comp_ids = [c["id"] for c in comp_data["components"]]
        assert "sidebar" in comp_ids  # parcial extraída da tela!

        # 4. Atualizar tela para revisão 2 e testar list_screen_revisions + compare_screens
        html_v2 = html_v1.replace("Transferir Ticket", "Encerrar Atendimento").replace(
            "bg-indigo-600", "bg-rose-600"
        )
        await client.post(
            "/mcp",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 14,
                "method": "tools/call",
                "params": {
                    "name": "update_screen_html",
                    "arguments": {
                        "screen_id": screen_id,
                        "html_content": html_v2,
                        "change_summary": "Troca botão para Encerrar Atendimento em vermelho",
                    },
                },
            },
        )

        revs_rpc = await client.post(
            "/mcp",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 15,
                "method": "tools/call",
                "params": {
                    "name": "list_screen_revisions",
                    "arguments": {"screen_id": screen_id},
                },
            },
        )
        assert revs_rpc.status_code == 200
        revs_data = json.loads(revs_rpc.json()["result"]["content"][0]["text"])
        assert revs_data["current_revision"] == 2
        assert len(revs_data["revisions"]) == 2

        # Comparar revisão 1 vs revisão 2 via compare_screens
        cmp_rpc = await client.post(
            "/mcp",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 16,
                "method": "tools/call",
                "params": {
                    "name": "compare_screens",
                    "arguments": {
                        "screen_id": screen_id,
                        "revision_a": 1,
                        "revision_b": 2,
                        "include_visual_diff": True,
                    },
                },
            },
        )
        assert cmp_rpc.status_code == 200
        cmp_content = cmp_rpc.json()["result"]["content"]
        assert any(c["type"] == "image" for c in cmp_content)
        cmp_data = json.loads([c["text"] for c in cmp_content if c["type"] == "text"][0])
        assert cmp_data["structural_diff"]["html_changed"] is True
        assert "btn-transfer" in cmp_data["structural_diff"]["elements_diff"]["modified"]
        assert cmp_data["visual_diff"]["diff_pixels"] > 0

        # 5. Testar get_canvas, upload_asset, add_comment e get_screen_comments
        canvas_rpc = await client.post(
            "/mcp",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 17,
                "method": "tools/call",
                "params": {
                    "name": "get_canvas",
                    "arguments": {"project_id": project_id},
                },
            },
        )
        assert canvas_rpc.status_code == 200
        canvas_data = json.loads(canvas_rpc.json()["result"]["content"][0]["text"])
        assert canvas_data["total_canvases"] >= 1

        svg_b64 = base64.b64encode(
            b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><circle cx="20" cy="20" r="18" fill="#4f46e5"/></svg>'
        ).decode("ascii")
        up_rpc = await client.post(
            "/mcp",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 18,
                "method": "tools/call",
                "params": {
                    "name": "upload_asset",
                    "arguments": {
                        "project_id": project_id,
                        "filename": "omnichat-logo.svg",
                        "data_base64": svg_b64,
                        "content_type": "image/svg+xml",
                    },
                },
            },
        )
        assert up_rpc.status_code == 200
        up_data = json.loads(up_rpc.json()["result"]["content"][0]["text"])
        assert "/api/assets/" in up_data["asset"]["url"]

        cm_rpc = await client.post(
            "/mcp",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 19,
                "method": "tools/call",
                "params": {
                    "name": "add_comment",
                    "arguments": {
                        "screen_id": screen_id,
                        "element_mb_id": "btn-transfer",
                        "body": "Validado pelo agente QA: contraste adequado no tema escuro.",
                    },
                },
            },
        )
        assert cm_rpc.status_code == 200
        cm_list_rpc = await client.post(
            "/mcp",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tools/call",
                "params": {
                    "name": "get_screen_comments",
                    "arguments": {"screen_id": screen_id},
                },
            },
        )
        assert cm_list_rpc.status_code == 200
        cm_list_data = json.loads(cm_list_rpc.json()["result"]["content"][0]["text"])
        assert cm_list_data["total_comments"] == 1
        assert cm_list_data["comments"][0]["element_mb_id"] == "btn-transfer"
