import os
import pytest
import httpx
import secrets

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_screen_revision_and_revert():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        email = f"rev_tester_{secrets.token_hex(4)}@empresa.com"
        pwd = "PassWord123!#"
        reg = await client.post("/api/auth/register", json={
            "email": email,
            "password": pwd,
            "name": "Revert Tester",
            "organization_name": f"Org Rev {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf

        # Cria projeto
        proj = await client.post("/api/projects", json={
            "name": "Projeto Reversão",
            "description": "Teste de checkpoints"
        })
        assert proj.status_code == 200
        proj_data = proj.json()
        entry_screen_id = proj_data["entry_screen_id"]

        # 1. Pega estado inicial
        initial_screen = await client.get(f"/api/screens/{entry_screen_id}")
        assert initial_screen.status_code == 200
        orig_html = initial_screen.json()["html_content"]

        # 2. Aplica alteração simulada da IA
        new_html = "<div class='p-8 bg-black text-white'><h1>Versão IA 1</h1></div>"
        update_res = await client.put(f"/api/screens/{entry_screen_id}", json={
            "html_content": new_html
        })
        assert update_res.status_code == 200
        assert update_res.json()["html_content"] == new_html

        # 3. Simula reversão (Undo) para o HTML original
        revert_res = await client.put(f"/api/screens/{entry_screen_id}", json={
            "html_content": orig_html
        })
        assert revert_res.status_code == 200
        assert revert_res.json()["html_content"] == orig_html

