import pytest
import httpx
import secrets
import os

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_private_project_isolation_and_member_permissions():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client_a:
        # 1. Registra Usuário A (Dono da Org 1)
        email_a = f"user_a_{secrets.token_hex(4)}@orgone.com"
        pwd = "PasswordOne123!"
        reg_a = await client_a.post("/api/auth/register", json={
            "email": email_a,
            "password": pwd,
            "name": "User Alpha",
            "organization_name": f"Org Alpha {secrets.token_hex(3)}"
        })
        assert reg_a.status_code == 200
        csrf_a = client_a.cookies.get("mockbird_csrf")
        headers_a = {"X-CSRF-Token": csrf_a} if csrf_a else {}

        # 2. Usuário A convida Usuário B para a Org 1 como 'editor' na organização
        email_b = f"user_b_{secrets.token_hex(4)}@orgone.com"
        inv_b = await client_a.post("/api/org/members/invite", json={
            "email": email_b,
            "name": "User Beta",
            "role": "editor",
            "temporary_password": pwd
        }, headers=headers_a)
        assert inv_b.status_code == 200
        user_b_id = inv_b.json()["id"]

        # 3. Usuário A cria um projeto PRIVADO (padrão)
        proj_res = await client_a.post("/api/projects", json={
            "name": "Projeto Ultra Secreto Alpha",
            "description": "Somente User Alpha deve ver inicialmente",
            "visibility": "private"
        }, headers=headers_a)
        assert proj_res.status_code == 200
        proj_a = proj_res.json()
        proj_id = proj_a["id"]
        assert proj_a["visibility"] == "private"

    # 4. Usuário B (mesma organização) tenta acessar o projeto privado de A
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client_b:
        login_b = await client_b.post("/api/auth/login", json={
            "email": email_b,
            "password": pwd
        })
        assert login_b.status_code == 200
        csrf_b = client_b.cookies.get("mockbird_csrf")
        headers_b = {"X-CSRF-Token": csrf_b} if csrf_b else {}

        # B não deve ver o projeto na listagem
        list_b = await client_b.get("/api/projects")
        assert list_b.status_code == 200
        projs_seen_by_b = [p["id"] for p in list_b.json()]
        assert proj_id not in projs_seen_by_b, "Usuário B não pode ver projeto privado de A na listagem"

        # B tenta acessar diretamente por ID -> 404 (evita enumeração IDOR)
        direct_b = await client_b.get(f"/api/projects/{proj_id}")
        assert direct_b.status_code == 404, f"Acesso direto a projeto privado alheio deve dar 404, deu: {direct_b.status_code}"

    # 5. Usuário C (de outra Organização 2) tenta acessar por ID -> 404
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client_c:
        email_c = f"user_c_{secrets.token_hex(4)}@orgtwo.com"
        await client_c.post("/api/auth/register", json={
            "email": email_c,
            "password": pwd,
            "name": "User Charlie",
            "organization_name": f"Org Charlie {secrets.token_hex(3)}"
        })
        direct_c = await client_c.get(f"/api/projects/{proj_id}")
        assert direct_c.status_code == 404, "Usuário de outra organização não pode ter acesso"

    # 6. Usuário A adiciona Usuário B como membro do projeto com papel 'viewer'
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client_a:
        login_a = await client_a.post("/api/auth/login", json={"email": email_a, "password": pwd})
        assert login_a.status_code == 200
        csrf_a = client_a.cookies.get("mockbird_csrf")
        headers_a = {"X-CSRF-Token": csrf_a} if csrf_a else {}

        add_mem = await client_a.post(f"/api/projects/{proj_id}/members", json={
            "user_id": user_b_id,
            "role": "viewer"
        }, headers=headers_a)
        assert add_mem.status_code == 200
        assert add_mem.json()["role"] == "viewer"

    # 7. Usuário B agora acessa o projeto como viewer
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client_b:
        login_b = await client_b.post("/api/auth/login", json={"email": email_b, "password": pwd})
        assert login_b.status_code == 200
        csrf_b = client_b.cookies.get("mockbird_csrf")
        headers_b = {"X-CSRF-Token": csrf_b} if csrf_b else {}

        # Agora B vê na listagem
        list_b = await client_b.get("/api/projects")
        assert list_b.status_code == 200
        assert proj_id in [p["id"] for p in list_b.json()]

        # B consegue ler o projeto
        read_b = await client_b.get(f"/api/projects/{proj_id}")
        assert read_b.status_code == 200

        # Como 'viewer' no projeto, B NÃO pode atualizar tokens -> 403
        up_tokens = await client_b.put(f"/api/tokens/{proj_id}", json={
            "light_tokens": {},
            "dark_tokens": {},
            "shared_tokens": {}
        }, headers=headers_b)
        assert up_tokens.status_code == 403, f"Viewer não pode alterar tokens: {up_tokens.status_code}"

    # 8. Usuário A altera papel de B para 'editor' no projeto
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client_a:
        login_a = await client_a.post("/api/auth/login", json={"email": email_a, "password": pwd})
        assert login_a.status_code == 200
        csrf_a = client_a.cookies.get("mockbird_csrf")
        headers_a = {"X-CSRF-Token": csrf_a} if csrf_a else {}

        up_mem = await client_a.post(f"/api/projects/{proj_id}/members", json={
            "user_id": user_b_id,
            "role": "editor"
        }, headers=headers_a)
        assert up_mem.status_code == 200
        assert up_mem.json()["role"] == "editor"

    # 9. Agora Usuário B consegue atualizar tokens do projeto com sucesso!
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client_b:
        login_b = await client_b.post("/api/auth/login", json={"email": email_b, "password": pwd})
        assert login_b.status_code == 200
        csrf_b = client_b.cookies.get("mockbird_csrf")
        headers_b = {"X-CSRF-Token": csrf_b} if csrf_b else {}

        up_tokens_ok = await client_b.put(f"/api/tokens/{proj_id}", json={
            "light_tokens": {"color-primary": "#10b981"},
            "dark_tokens": {"color-primary": "#059669"},
            "shared_tokens": {"font": "Inter"}
        }, headers=headers_b)
        assert up_tokens_ok.status_code == 200
        assert up_tokens_ok.json()["light_tokens"]["color-primary"] == "#10b981"

