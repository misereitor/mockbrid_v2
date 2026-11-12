import os
import secrets

import httpx
import pytest

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_private_project_is_not_public_until_published_or_shared():
    pwd = "PasswordStrong123!"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as owner:
        reg = await owner.post(
            "/api/auth/register",
            json={
                "email": f"share_{secrets.token_hex(4)}@empresa.com",
                "password": pwd,
                "name": "Owner Share",
                "organization_name": f"Org Share {secrets.token_hex(3)}",
            },
        )
        assert reg.status_code == 200, reg.text
        csrf = owner.cookies.get("mockbird_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        proj = await owner.post("/api/projects", json={"name": "Projeto Privado"}, headers=headers)
        assert proj.status_code == 200, proj.text
        data = proj.json()
        project_id, slug = data["id"], data["slug"]

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as anon:
            # 1. Projeto privado não é acessível publicamente, mesmo com o slug
            private = await anon.get(f"/api/public/p/{slug}")
            assert private.status_code == 404, private.text

            # 2. Publicar habilita o link
            pub = await owner.post(f"/api/projects/{project_id}/publish", headers=headers)
            assert pub.status_code == 200, pub.text
            public_ok = await anon.get(f"/api/public/p/{slug}")
            assert public_ok.status_code == 200, public_ok.text
            assert public_ok.json()["project_name"] == "Projeto Privado"

            # 3. Despublicar volta a bloquear
            unpub = await owner.request("DELETE", f"/api/projects/{project_id}/publish", headers=headers)
            assert unpub.status_code == 200, unpub.text
            blocked = await anon.get(f"/api/public/p/{slug}")
            assert blocked.status_code == 404, blocked.text

        # 4. Share link com senha e expiração
        link_res = await owner.post(
            f"/api/projects/{project_id}/share-links",
            json={"password": "segredo123", "expires_in_days": 1, "allow_comments": True},
            headers=headers,
        )
        assert link_res.status_code == 200, link_res.text
        link = link_res.json()
        assert link["has_password"] is True

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as anon:
            no_pwd = await anon.get(f"/api/public/p/{link['slug']}")
            assert no_pwd.status_code == 401, no_pwd.text

            wrong = await anon.get(f"/api/public/p/{link['slug']}", params={"password": "errada"})
            assert wrong.status_code == 403, wrong.text

            ok = await anon.get(f"/api/public/p/{link['slug']}", params={"password": "segredo123"})
            assert ok.status_code == 200, ok.text
            assert ok.json()["allow_comments"] is True

        # 5. Revogar o link derruba o acesso
        revoke = await owner.delete(
            f"/api/projects/{project_id}/share-links/{link['id']}", headers=headers
        )
        assert revoke.status_code == 200, revoke.text
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as anon:
            gone = await anon.get(f"/api/public/p/{link['slug']}", params={"password": "segredo123"})
            assert gone.status_code == 404, gone.text

        # 6. Outro tenant não consegue ler nem revogar recursos do projeto
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as other:
            other_reg = await other.post(
                "/api/auth/register",
                json={
                    "email": f"intruso_{secrets.token_hex(4)}@empresa.com",
                    "password": pwd,
                    "name": "Intruso",
                    "organization_name": f"Org Intrusa {secrets.token_hex(3)}",
                },
            )
            assert other_reg.status_code == 200, other_reg.text
            other_csrf = other.cookies.get("mockbird_csrf")
            other_headers = {"X-CSRF-Token": other_csrf} if other_csrf else {}

            assert (await other.get(f"/api/projects/{project_id}/share-links", headers=other_headers)).status_code in (403, 404)
            assert (
                await other.post(f"/api/projects/{project_id}/publish", headers=other_headers)
            ).status_code in (403, 404)
