import os
import secrets
import httpx
import pytest

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_rename_project_endpoint():
    """Valida renomeação de projeto, restrições e segurança multitenant."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as client:
        email = f"renamer_{secrets.token_hex(4)}@empresa.com"
        reg = await client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "StrongPassword123!",
                "name": "Project Renamer",
                "organization_name": f"Org Renamer {secrets.token_hex(3)}",
            },
        )
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        # 1. Cria projeto
        proj_res = await client.post(
            "/api/projects",
            json={"name": "Projeto Original", "description": "Desc inicial"},
            headers=headers,
        )
        assert proj_res.status_code == 200
        proj_id = proj_res.json()["id"]

        # 2. Renomeia o projeto com PATCH
        patch_res = await client.patch(
            f"/api/projects/{proj_id}",
            json={"name": "Projeto Renomeado com Sucesso"},
            headers=headers,
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["name"] == "Projeto Renomeado com Sucesso"

        # 3. Valida no GET /api/projects/{id}
        get_res = await client.get(f"/api/projects/{proj_id}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["name"] == "Projeto Renomeado com Sucesso"

        # 4. Rejeita nome vazio -> 400
        bad_name_res = await client.patch(
            f"/api/projects/{proj_id}",
            json={"name": "   "},
            headers=headers,
        )
        assert bad_name_res.status_code == 400

        # 5. Outro usuário de outra org não pode renomear o projeto
        other_email = f"intruder_{secrets.token_hex(4)}@outra.com"
        await client.post(
            "/api/auth/register",
            json={
                "email": other_email,
                "password": "StrongPassword123!",
                "name": "Intruder",
                "organization_name": f"Org Intruder {secrets.token_hex(3)}",
            },
        )
        intruder_csrf = client.cookies.get("mockbird_csrf")
        intruder_headers = {"X-CSRF-Token": intruder_csrf} if intruder_csrf else {}

        hacked_res = await client.patch(
            f"/api/projects/{proj_id}",
            json={"name": "Hacked Name"},
            headers=intruder_headers,
        )
        assert hacked_res.status_code in (403, 404)
