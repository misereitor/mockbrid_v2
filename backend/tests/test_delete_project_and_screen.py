import pytest
import httpx
import secrets

BASE_URL = "http://127.0.0.1:8082"


@pytest.mark.asyncio
async def test_delete_project_and_screen():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Cria usuário
        email = f"del_tester_{secrets.token_hex(4)}@empresa.com"
        pwd = "PassWord123!#"
        reg = await client.post("/api/auth/register", json={
            "email": email,
            "password": pwd,
            "name": "Delete Tester",
            "organization_name": f"Org Del {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200

        # 2. Cria projeto de teste
        proj_res = await client.post("/api/projects", json={
            "name": "Projeto Para Deletar",
            "description": "Teste de exclusão"
        })
        assert proj_res.status_code == 200
        proj_id = proj_res.json()["id"]

        # 3. Cria tela secundária no projeto
        screen_res = await client.post(f"/api/projects/{proj_id}/screens", json={
            "name": "Tela Secundária"
        })
        assert screen_res.status_code == 200
        screen_id = screen_res.json()["id"]

        # 4. Deleta a tela secundária
        del_screen = await client.delete(f"/api/screens/{screen_id}")
        assert del_screen.status_code == 200
        assert del_screen.json()["screen_id"] == screen_id

        # Verifica que a tela não existe mais
        get_screen = await client.get(f"/api/screens/{screen_id}")
        assert get_screen.status_code == 404

        # 5. Deleta o projeto
        del_proj = await client.delete(f"/api/projects/{proj_id}")
        assert del_proj.status_code == 200
        assert del_proj.json()["project_id"] == proj_id

        # Verifica que o projeto não existe mais
        get_proj = await client.get(f"/api/projects/{proj_id}")
        assert get_proj.status_code == 404

