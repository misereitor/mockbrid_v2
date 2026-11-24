import os
import secrets
import httpx
import pytest

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_mcp_key_multi_project_permissions_and_editing():
    """Valida:
    1. Criação de chave restrita a um projeto.
    2. Edição via PATCH para adicionar outro projeto.
    3. Edição via PATCH para remover um projeto.
    4. Garantia de bloqueio (403) para projeto não autorizado.
    5. Edição para Global ([]), permitindo acesso irrestrito.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        email = f"mcp_perm_{secrets.token_hex(4)}@empresa.com"
        reg = await client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "StrongPassword123!",
                "name": "MCP MultiProject Admin",
                "organization_name": f"Org Perm {secrets.token_hex(3)}",
            },
        )
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        # 1. Cria 3 projetos distintos
        p1 = (await client.post("/api/projects", json={"name": "Projeto Alpha"}, headers=headers)).json()
        p2 = (await client.post("/api/projects", json={"name": "Projeto Beta"}, headers=headers)).json()
        p3 = (await client.post("/api/projects", json={"name": "Projeto Gama"}, headers=headers)).json()

        # 2. Cria chave MCP restrita inicialmente apenas ao Projeto Alpha
        key_res = await client.post(
            "/api/mcp/keys",
            json={
                "name": "Agente Alpha",
                "project_ids": [p1["id"]],
                "scopes": ["project:read", "screen:write"],
            },
            headers=headers,
        )
        assert key_res.status_code == 200
        key_data = key_res.json()
        raw_key = key_data["raw_key"]
        key_id = key_data["id"]

        assert key_data["project_ids"] == [p1["id"]]
        assert len(key_data["projects"]) == 1
        assert key_data["projects"][0]["name"] == "Projeto Alpha"

        mcp_auth = {"Authorization": f"Bearer {raw_key}"}

        # Alpha tem acesso permitido
        alpha_map = await client.post(f"/mcp/tools/get_project_map?project_id={p1['id']}", headers=mcp_auth)
        assert alpha_map.status_code == 200

        # Beta deve ser bloqueado com 403
        beta_blocked = await client.post(f"/mcp/tools/get_project_map?project_id={p2['id']}", headers=mcp_auth)
        assert beta_blocked.status_code == 403

        # 3. Edita a chave para adicionar o Projeto Beta: project_ids = [Alpha, Beta]
        patch_res = await client.patch(
            f"/api/mcp/keys/{key_id}",
            json={"project_ids": [p1["id"], p2["id"]]},
            headers=headers,
        )
        assert patch_res.status_code == 200
        patched_data = patch_res.json()
        assert set(patched_data["project_ids"]) == {p1["id"], p2["id"]}
        assert len(patched_data["projects"]) == 2

        # Agora Beta tem acesso permitido!
        beta_allowed = await client.post(f"/mcp/tools/get_project_map?project_id={p2['id']}", headers=mcp_auth)
        assert beta_allowed.status_code == 200

        # Gama continua bloqueado
        gama_blocked = await client.post(f"/mcp/tools/get_project_map?project_id={p3['id']}", headers=mcp_auth)
        assert gama_blocked.status_code == 403

        # 4. Remove Alpha, deixando apenas Beta: project_ids = [Beta]
        patch_remove = await client.patch(
            f"/api/mcp/keys/{key_id}",
            json={"project_ids": [p2["id"]]},
            headers=headers,
        )
        assert patch_remove.status_code == 200
        assert patch_remove.json()["project_ids"] == [p2["id"]]

        # Alpha agora é bloqueado
        alpha_now_blocked = await client.post(f"/mcp/tools/get_project_map?project_id={p1['id']}", headers=mcp_auth)
        assert alpha_now_blocked.status_code == 403

        # Beta continua permitido
        beta_still_allowed = await client.post(f"/mcp/tools/get_project_map?project_id={p2['id']}", headers=mcp_auth)
        assert beta_still_allowed.status_code == 200

        # 5. Edita para Global (project_ids = []): todos os projetos passam a ser acessíveis
        patch_global = await client.patch(
            f"/api/mcp/keys/{key_id}",
            json={"project_ids": []},
            headers=headers,
        )
        assert patch_global.status_code == 200
        assert patch_global.json()["project_ids"] == []

        for p in [p1, p2, p3]:
            res = await client.post(f"/mcp/tools/get_project_map?project_id={p['id']}", headers=mcp_auth)
            assert res.status_code == 200
