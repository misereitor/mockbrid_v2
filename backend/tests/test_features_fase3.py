import os
import pytest
import httpx
import secrets

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_screen_revisions_revert_and_duplicate():
    """Valida ciclo completo de revisões, reversão e duplicação de telas."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as client:
        email = f"fase3_{secrets.token_hex(4)}@empresa.com"
        reg = await client.post("/api/auth/register", json={
            "email": email,
            "password": "StrongPassword123!",
            "name": "Fase3 Tester",
            "organization_name": f"Org Fase3 {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf

        # 1. Cria Projeto
        proj = await client.post("/api/projects", json={
            "name": "Projeto com Revisões",
            "description": "Teste de versionamento"
        })
        assert proj.status_code == 200
        screen_id = proj.json()["entry_screen_id"]

        # 2. Faz primeira alteração na tela (cria revisão 2)
        upd1 = await client.patch(f"/api/screens/{screen_id}", json={
            "html_content": "<div class='v2'>Versão 2</div>"
        })
        assert upd1.status_code == 200
        assert upd1.json()["current_revision"] == 2

        # 3. Faz segunda alteração na tela (cria revisão 3)
        upd2 = await client.patch(f"/api/screens/{screen_id}", json={
            "html_content": "<div class='v3'>Versão 3 Errada</div>"
        })
        assert upd2.status_code == 200
        assert upd2.json()["current_revision"] == 3

        # 4. Lista revisões da tela
        revs_res = await client.get(f"/api/screens/{screen_id}/revisions")
        assert revs_res.status_code == 200
        revs = revs_res.json()
        assert len(revs) >= 2
        rev2 = [r for r in revs if r["revision_number"] == 2][0]

        # 5. Reverte para a revisão 2
        revert_res = await client.post(f"/api/screens/{screen_id}/revisions/{rev2['id']}/revert")
        assert revert_res.status_code == 200
        reverted_screen = revert_res.json()
        assert reverted_screen["html_content"] == "<div class='v2'>Versão 2</div>"
        assert reverted_screen["current_revision"] == 4

        # 6. Duplica a tela
        dup_screen = await client.post(f"/api/screens/{screen_id}/duplicate")
        assert dup_screen.status_code == 200
        dup_data = dup_screen.json()
        assert "Cópia" in dup_data["name"]
        assert dup_data["id"] != screen_id
        assert dup_data["html_content"] == "<div class='v2'>Versão 2</div>"

        # 7. Dev Mode Export da tela
        export_screen = await client.get(f"/api/screens/{screen_id}/export")
        assert export_screen.status_code == 200
        assert "react_jsx" in export_screen.json()


@pytest.mark.asyncio
async def test_project_duplicate_search_and_export():
    """Valida duplicação de projeto, busca e exportação de bundle consolidado."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as client:
        email = f"proj_fase3_{secrets.token_hex(4)}@empresa.com"
        reg = await client.post("/api/auth/register", json={
            "email": email,
            "password": "StrongPassword123!",
            "name": "Project Tester",
            "organization_name": f"Org Proj {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf

        # Cria projeto
        proj = await client.post("/api/projects", json={
            "name": "Projeto Alpha Exclusivo",
            "description": "Teste busca e duplicação"
        })
        assert proj.status_code == 200
        proj_id = proj.json()["id"]

        # Busca pelo nome
        search_res = await client.get("/api/projects?q=Alpha")
        assert search_res.status_code == 200
        assert len(search_res.json()) >= 1
        assert any(p["id"] == proj_id for p in search_res.json())

        # Duplica projeto inteiro
        dup_res = await client.post(f"/api/projects/{proj_id}/duplicate")
        assert dup_res.status_code == 200
        dup_proj = dup_res.json()
        assert "Cópia" in dup_proj["name"]
        assert dup_proj["id"] != proj_id
        assert dup_proj["entry_screen_id"] is not None

        # Exporta bundle consolidado do projeto
        bundle_res = await client.get(f"/api/projects/{proj_id}/export/bundle")
        assert bundle_res.status_code == 200
        bundle = bundle_res.json()
        assert "project" in bundle
        assert "tokens" in bundle
        assert "screens" in bundle
        assert len(bundle["screens"]) >= 1


@pytest.mark.asyncio
async def test_auth_profile_and_password_change():
    """Valida atualização de perfil e troca de senha segura."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as client:
        email = f"profile_{secrets.token_hex(4)}@empresa.com"
        pwd = "OldPassword123!"
        reg = await client.post("/api/auth/register", json={
            "email": email,
            "password": pwd,
            "name": "Nome Antigo",
            "organization_name": f"Org Profile {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf

        # Atualiza nome do perfil
        prof_res = await client.patch("/api/auth/profile", json={"name": "Nome Novo Atualizado"})
        assert prof_res.status_code == 200
        assert prof_res.json()["name"] == "Nome Novo Atualizado"

        # Troca de senha
        new_pwd = "BrandNewSecurePassword999!"
        chg_res = await client.post("/api/auth/change-password", json={
            "current_password": pwd,
            "new_password": new_pwd
        })
        assert chg_res.status_code == 200

        # Login com senha antiga deve falhar
        fail_login = await client.post("/api/auth/login", json={
            "email": email,
            "password": pwd
        })
        assert fail_login.status_code == 400

        # Login com senha nova deve ter sucesso
        success_login = await client.post("/api/auth/login", json={
            "email": email,
            "password": new_pwd
        })
        assert success_login.status_code == 200


@pytest.mark.asyncio
async def test_org_member_management():
    """Valida fluxo de convite, alteração de permissão e remoção de membros."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as client:
        owner_email = f"owner_{secrets.token_hex(4)}@empresa.com"
        reg = await client.post("/api/auth/register", json={
            "email": owner_email,
            "password": "OwnerPassword123!",
            "name": "Empresa Owner",
            "organization_name": f"Org Team {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf

        # 1. Convida novo membro editor
        member_email = f"designer_{secrets.token_hex(4)}@empresa.com"
        inv_res = await client.post("/api/org/members/invite", json={
            "email": member_email,
            "name": "UX Designer",
            "role": "editor"
        })
        assert inv_res.status_code == 200
        member_id = inv_res.json()["id"]
        assert inv_res.json()["role"] == "editor"

        # 2. Promove membro para admin
        promote_res = await client.patch(f"/api/org/members/{member_id}/role", json={
            "role": "admin"
        })
        assert promote_res.status_code == 200
        assert promote_res.json()["role"] == "admin"

        # 3. Lista membros
        list_res = await client.get("/api/org/members")
        assert list_res.status_code == 200
        members = list_res.json()
        assert len(members) >= 2

        # 4. Remove membro da organização
        del_res = await client.delete(f"/api/org/members/{member_id}")
        assert del_res.status_code == 200
        assert del_res.json()["member_id"] == member_id
