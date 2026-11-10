import pytest
import httpx
import secrets
import os

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_full_project_duplication_and_secure_invites():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Registra proprietário
        owner_email = f"owner_dup_{secrets.token_hex(4)}@empresa.com"
        pwd = "OwnerPassword123!"
        reg = await client.post("/api/auth/register", json={
            "email": owner_email,
            "password": pwd,
            "name": "Owner Duplicator",
            "organization_name": f"Org Dup {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200, reg.text
        csrf = client.cookies.get("mockbird_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        # 2. Cria projeto original visível na organização
        orig_proj_res = await client.post("/api/projects", json={
            "name": "Projeto Base com Scenarios",
            "description": "Projeto para teste de duplicação profunda",
            "visibility": "org"
        }, headers=headers)
        assert orig_proj_res.status_code == 200, orig_proj_res.text
        orig_proj = orig_proj_res.json()
        orig_id = orig_proj["id"]
        orig_screen_id = orig_proj["entry_screen_id"]

        # 3. Duplica o projeto
        dup_res = await client.post(f"/api/projects/{orig_id}/duplicate", headers=headers)
        assert dup_res.status_code == 200, dup_res.text
        dup_proj = dup_res.json()
        assert dup_proj["id"] != orig_id
        assert "Cópia" in dup_proj["name"]
        dup_screen_id = dup_proj["entry_screen_id"]
        assert dup_screen_id != orig_screen_id

        # 4. Verifica histórico de revisões da tela duplicada
        revs_res = await client.get(f"/api/screens/{dup_screen_id}/revisions")
        assert revs_res.status_code == 200, revs_res.text
        revs = revs_res.json()
        assert len(revs) >= 1
        assert revs[0]["change_summary"] == "Duplicação de projeto"

        # 5. Fluxo de convite seguro de membro
        invitee_email = f"invitee_{secrets.token_hex(4)}@empresa.com"
        inv_res = await client.post("/api/org/members/invite", json={
            "email": invitee_email,
            "name": "Convidado Especial",
            "role": "editor"
        }, headers=headers)
        assert inv_res.status_code == 200, inv_res.text
        inv_data = inv_res.json()
        token = inv_data.get("invite_token")
        assert token is not None and len(token) > 10
        assert f"/accept-invite?token={token}" in inv_data.get("invite_url")

    # 6. Convidado aceita o convite definindo sua própria senha (sessão não autenticada)
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as guest_client:
        invitee_pwd = "NewInviteePassword987!"
        accept_res = await guest_client.post("/api/org/members/accept-invite", json={
            "token": token,
            "password": invitee_pwd,
            "name": "Convidado Ativo"
        })
        assert accept_res.status_code == 200, accept_res.text
        assert accept_res.json()["status"] == "success"

        # 7. Convidado faz login com a senha que acabou de definir
        login_res = await guest_client.post("/api/auth/login", json={
            "email": invitee_email,
            "password": invitee_pwd
        })
        assert login_res.status_code == 200, login_res.text
        guest_csrf = guest_client.cookies.get("mockbird_csrf")
        guest_headers = {"X-CSRF-Token": guest_csrf} if guest_csrf else {}

        # 8. Como editor, convidado pode listar e ler o projeto
        guest_projs = await guest_client.get("/api/projects")
        assert guest_projs.status_code == 200
        proj_ids = [p["id"] for p in guest_projs.json()]
        assert orig_id in proj_ids

        # 9. Tentar reutilizar o mesmo token de convite -> Deve falhar com 400
        reuse_res = await guest_client.post("/api/org/members/accept-invite", json={
            "token": token,
            "password": "OutraSenhaTentativa123!"
        })
        assert reuse_res.status_code == 400, "Token reutilizado deveria ser rejeitado!"

