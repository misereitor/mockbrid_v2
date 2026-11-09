import os
import pytest
import httpx
import secrets

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_viewer_role_cannot_modify_screens_or_duplicate():
    """Valida se usuário com papel 'viewer' é impedido de mutações com 403 Forbidden."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as admin_client:
        # 1. Owner cria organização e projeto
        owner_email = f"owner_rbac_{secrets.token_hex(4)}@empresa.com"
        pwd = "PasswordStrong123!"
        reg = await admin_client.post("/api/auth/register", json={
            "email": owner_email,
            "password": pwd,
            "name": "Org Owner",
            "organization_name": f"Org RBAC {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200
        admin_csrf = admin_client.cookies.get("mockbird_csrf")
        admin_headers = {"X-CSRF-Token": admin_csrf} if admin_csrf else {}

        proj_res = await admin_client.post("/api/projects", json={
            "name": "Projeto RBAC",
            "description": "Teste de Permissões"
        }, headers=admin_headers)
        assert proj_res.status_code == 200
        proj_id = proj_res.json()["id"]
        screen_id = proj_res.json()["entry_screen_id"]

        # 2. Convida membro com papel 'viewer' com senha temporária
        viewer_email = f"viewer_{secrets.token_hex(4)}@empresa.com"
        inv_res = await admin_client.post("/api/org/members/invite", json={
            "email": viewer_email,
            "name": "Viewer Test",
            "role": "viewer",
            "temporary_password": pwd
        }, headers=admin_headers)
        assert inv_res.status_code == 200
        inv_data = inv_res.json()
        assert "invite_token" in inv_data

    # 3. Viewer faz login
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as viewer_client:
        login_res = await viewer_client.post("/api/auth/login", json={
            "email": viewer_email,
            "password": pwd
        })
        assert login_res.status_code == 200
        viewer_csrf = viewer_client.cookies.get("mockbird_csrf")
        viewer_headers = {"X-CSRF-Token": viewer_csrf} if viewer_csrf else {}

        # Viewer consegue ler projeto normalmente (200)
        read_proj = await viewer_client.get(f"/api/projects/{proj_id}")
        assert read_proj.status_code == 200

        # A. Viewer tenta duplicar projeto -> DEVE RETORNAR 403 Forbidden
        dup_proj = await viewer_client.post(f"/api/projects/{proj_id}/duplicate", headers=viewer_headers)
        assert dup_proj.status_code == 403, f"Viewer não pode duplicar projeto: {dup_proj.status_code}"

        # B. Viewer tenta editar tela -> DEVE RETORNAR 403 Forbidden
        edit_screen = await viewer_client.patch(f"/api/screens/{screen_id}", json={
            "html_content": "<p>Hacked by Viewer</p>"
        }, headers=viewer_headers)
        assert edit_screen.status_code == 403, f"Viewer não pode editar tela: {edit_screen.status_code}"

        # C. Viewer tenta duplicar tela -> DEVE RETORNAR 403 Forbidden
        dup_screen = await viewer_client.post(f"/api/screens/{screen_id}/duplicate", headers=viewer_headers)
        assert dup_screen.status_code == 403, f"Viewer não pode duplicar tela: {dup_screen.status_code}"
