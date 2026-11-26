"""Link público de apresentação: só share links abrem, com permissões editáveis."""

import os
import secrets

import httpx
import pytest

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")
PWD = "PasswordStrong123!"


async def _register(client: httpx.AsyncClient, prefix: str, org: str | None = None) -> dict:
    res = await client.post(
        "/api/auth/register",
        json={
            "email": f"{prefix}_{secrets.token_hex(4)}@empresa.com",
            "password": PWD,
            "name": prefix.title(),
            "organization_name": org or f"Org {prefix} {secrets.token_hex(3)}",
        },
    )
    assert res.status_code == 200, res.text
    csrf = client.cookies.get("mockbird_csrf")
    return {"X-CSRF-Token": csrf} if csrf else {}


async def _new_project(owner: httpx.AsyncClient, headers: dict) -> dict:
    res = await owner.post("/api/projects", json={"name": "Projeto Privado"}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _code(res: httpx.Response) -> str | None:
    detail = res.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


@pytest.mark.asyncio
async def test_project_slug_never_opens_public_presentation():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as owner:
        headers = await _register(owner, "slug")
        project = await _new_project(owner, headers)

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as anon:
            res = await anon.get(f"/api/public/p/{project['slug']}")
            assert res.status_code == 404, res.text

        # A publicação permanente foi descontinuada: não liga mais nada.
        pub = await owner.post(f"/api/projects/{project['id']}/publish", headers=headers)
        assert pub.status_code == 410, pub.text
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as anon:
            assert (await anon.get(f"/api/public/p/{project['slug']}")).status_code == 404


@pytest.mark.asyncio
async def test_share_link_password_lifecycle_and_revocation():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as owner:
        headers = await _register(owner, "share")
        project = await _new_project(owner, headers)

        link_res = await owner.post(
            f"/api/projects/{project['id']}/share-links",
            json={"password": "segredo123", "expires_in_days": 1, "allow_comments": True, "label": "CEO"},
            headers=headers,
        )
        assert link_res.status_code == 200, link_res.text
        link = link_res.json()
        assert link["has_password"] is True
        assert link["access_mode"] == "anyone"
        assert link["label"] == "CEO"
        assert len(link["slug"]) >= 16  # token aleatório, não o slug curto do projeto

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as anon:
            url = f"/api/public/p/{link['slug']}"

            no_pwd = await anon.get(url)
            assert no_pwd.status_code == 401, no_pwd.text
            assert _code(no_pwd) == "password_required"

            wrong = await anon.get(url, headers={"X-Share-Password": "errada"})
            assert wrong.status_code == 403, wrong.text
            assert _code(wrong) == "password_invalid"

            # A senha na query string NÃO vale mais (vazaria em log e histórico).
            in_query = await anon.get(url, params={"password": "segredo123"})
            assert in_query.status_code == 401, in_query.text

            ok = await anon.get(url, headers={"X-Share-Password": "segredo123"})
            assert ok.status_code == 200, ok.text
            assert ok.json()["allow_comments"] is True

        revoke = await owner.delete(
            f"/api/projects/{project['id']}/share-links/{link['id']}", headers=headers
        )
        assert revoke.status_code == 200, revoke.text
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as anon:
            gone = await anon.get(
                f"/api/public/p/{link['slug']}", headers={"X-Share-Password": "segredo123"}
            )
            assert gone.status_code == 404, gone.text


@pytest.mark.asyncio
async def test_patch_changes_permissions_without_changing_the_url():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as owner:
        headers = await _register(owner, "patch")
        project = await _new_project(owner, headers)
        base = f"/api/projects/{project['id']}/share-links"

        link = (await owner.post(base, json={}, headers=headers)).json()
        url = f"/api/public/p/{link['slug']}"
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as anon:
            assert (await anon.get(url)).status_code == 200  # aberto: anyone, sem senha

            # anyone -> org: o anônimo perde o acesso na hora, com o mesmo link.
            org = await owner.patch(f"{base}/{link['id']}", json={"access_mode": "org"}, headers=headers)
            assert org.status_code == 200, org.text
            assert org.json()["slug"] == link["slug"]
            assert org.json()["access_mode"] == "org"
            blocked = await anon.get(url)
            assert blocked.status_code == 401, blocked.text
            assert _code(blocked) == "login_required"

        # O dono (membro da organização) continua vendo.
        assert (await owner.get(url)).status_code == 200

        # Define e depois remove a senha; senha vazia remove.
        with_pwd = await owner.patch(f"{base}/{link['id']}", json={"access_mode": "anyone", "password": "abc12345"}, headers=headers)
        assert with_pwd.json()["has_password"] is True
        no_pwd = await owner.patch(f"{base}/{link['id']}", json={"password": ""}, headers=headers)
        assert no_pwd.json()["has_password"] is False

        # Campo ausente mantém o valor atual.
        kept = await owner.patch(f"{base}/{link['id']}", json={"label": "Diretoria"}, headers=headers)
        assert kept.json()["label"] == "Diretoria"
        assert kept.json()["access_mode"] == "anyone"

        invalid = await owner.patch(f"{base}/{link['id']}", json={"access_mode": "publico"}, headers=headers)
        assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_org_link_denies_other_tenants_and_private_preview_needs_access():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as owner, httpx.AsyncClient(
        base_url=BASE_URL, timeout=20.0
    ) as intruder:
        headers = await _register(owner, "org")
        await _register(intruder, "intruso")
        project = await _new_project(owner, headers)

        link = (
            await owner.post(
                f"/api/projects/{project['id']}/share-links",
                json={"access_mode": "org"},
                headers=headers,
            )
        ).json()
        url = f"/api/public/p/{link['slug']}"

        # Logado em OUTRA organização: 404, sem confirmar que o projeto existe.
        denied = await intruder.get(url)
        assert denied.status_code == 404, denied.text
        assert _code(denied) == "not_found"

        # Pré-visualização privada: só quem tem acesso ao projeto.
        preview = await owner.get(f"/api/projects/{project['id']}/presentation")
        assert preview.status_code == 200, preview.text
        assert preview.json()["allow_comments"] is False
        assert (await intruder.get(f"/api/projects/{project['id']}/presentation")).status_code in (403, 404)
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as anon:
            assert (await anon.get(f"/api/projects/{project['id']}/presentation")).status_code == 401

        # Pré-visualizar não cria link nem conta visualização.
        links = (await owner.get(f"/api/projects/{project['id']}/share-links")).json()
        assert len(links) == 1
        assert links[0]["view_count"] == 0

        # Outro tenant não lê, edita nem revoga.
        base = f"/api/projects/{project['id']}/share-links"
        assert (await intruder.get(base)).status_code in (403, 404)
        intruder_csrf = intruder.cookies.get("mockbird_csrf")
        ih = {"X-CSRF-Token": intruder_csrf} if intruder_csrf else {}
        assert (await intruder.patch(f"{base}/{link['id']}", json={"access_mode": "anyone"}, headers=ih)).status_code in (403, 404)
        assert (await intruder.delete(f"{base}/{link['id']}", headers=ih)).status_code in (403, 404)


@pytest.mark.asyncio
async def test_unsigned_asset_is_public_only_for_open_links():
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9b\xcb\xab\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as owner:
        headers = await _register(owner, "asset")
        project = await _new_project(owner, headers)
        up = await owner.post(
            f"/api/projects/{project['id']}/assets",
            files={"file": ("logo.png", png, "image/png")},
            headers=headers,
        )
        assert up.status_code == 200, up.text
        unsigned = f"/api/assets/{up.json()['id']}"
        base = f"/api/projects/{project['id']}/share-links"

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as anon:
            assert (await anon.get(unsigned)).status_code == 404  # sem link nenhum

            # Link com senha NÃO abre asset avulso.
            with_pwd = (await owner.post(base, json={"password": "segredo123"}, headers=headers)).json()
            assert (await anon.get(unsigned)).status_code == 404

            # Link restrito à organização também não.
            await owner.delete(f"{base}/{with_pwd['id']}", headers=headers)
            org_link = (await owner.post(base, json={"access_mode": "org"}, headers=headers)).json()
            assert (await anon.get(unsigned)).status_code == 404

            # Só um link realmente aberto (anyone, sem senha) libera.
            await owner.delete(f"{base}/{org_link['id']}", headers=headers)
            await owner.post(base, json={}, headers=headers)
            assert (await anon.get(unsigned)).status_code == 200
            # A URL assinada que o sistema grava no HTML continua valendo sempre.
            assert (await anon.get(up.json()["url"])).status_code == 200
