"""Importação/exportação do corpus `design/` do Mockbird v1.

Roda contra a stack de homologação (skipped automaticamente sem ela), exercitando
o caminho real: ZIP do v1 -> projeto com canvases/telas/tokens -> export ->
reimportação do ZIP exportado.
"""

import io
import json
import secrets
import zipfile

import httpx
import pytest

BASE_URL = "http://127.0.0.1:8082"


def _build_corpus_zip() -> bytes:
    tokens = {
        "light": {
            "color": {
                "$type": "color",
                "bg": {"$value": "#f8fafc"},
                "primary": {"$value": "#0f766e"},
            },
            "space": {"4": {"$value": "16px"}},
        },
        "dark": {"color": {"primary": {"$value": "#2dd4bf"}}},
    }
    login_html = (
        '<!doctype html>\n<html lang="pt-BR"><head>'
        '<link rel="stylesheet" href="../design-system.css">'
        "</head><body>"
        '<main class="login-screen"><h1>Entrar</h1></main>'
        '<script src="../mock.js"></script>'
        "</body></html>"
    )
    cadastro_html = "<!doctype html><html><body><h1>Cadastro</h1></body></html>"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("design/tokens.json", json.dumps(tokens))
        archive.writestr("design/design-system.css", ".login-screen { padding: 16px; }")
        archive.writestr("design/mock.js", "window.__mock = true;")
        archive.writestr(
            "design/login/canvas.json",
            json.dumps(
                {
                    "title": "Acesso",
                    "screens": [
                        {
                            "id": "login",
                            "name": "Login",
                            "file": "01-login.html",
                            "device": "mobile",
                            "width": 390,
                            "height": 844,
                        },
                        {
                            "id": "cadastro",
                            "name": "Cadastro",
                            "file": "02-cadastro.html",
                            "device": "mobile",
                            "width": 390,
                            "height": 844,
                        },
                    ],
                }
            ),
        )
        archive.writestr("design/login/01-login.html", login_html)
        archive.writestr("design/login/02-cadastro.html", cadastro_html)
    return buffer.getvalue()


def _read_zip(blob: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


async def _register(client: httpx.AsyncClient) -> None:
    email = f"corpus_{secrets.token_hex(4)}@empresa.com"
    response = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "PassWord123!#",
            "name": "Corpus Tester",
            "organization_name": f"Org Corpus {secrets.token_hex(3)}",
        },
    )
    assert response.status_code == 200, response.text
    csrf = client.cookies.get("mockbird_csrf")
    if csrf:
        client.headers["X-CSRF-Token"] = csrf


@pytest.mark.asyncio
async def test_import_design_corpus_and_export_roundtrip():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        await _register(client)
        blob = _build_corpus_zip()

        imported = await client.post(
            "/api/projects/import/design",
            data={"name": "Corpus Antigo"},
            files={"file": ("design.zip", blob, "application/zip")},
        )
        assert imported.status_code == 200, imported.text
        body = imported.json()
        assert body["project"]["name"] == "Corpus Antigo"
        assert body["canvases"] == 1
        assert body["screens"] == 2
        project_id = body["project"]["id"]

        screens_res = await client.get(f"/api/projects/{project_id}/screens")
        assert screens_res.status_code == 200
        screens = screens_res.json()
        assert [s["name"] for s in screens] == ["Login", "Cadastro"]
        login = screens[0]
        assert login["device_type"] == "mobile"
        assert login["width"] == 390
        assert login["is_entry"] is True
        # CSS/JS relativos ao corpus são inlinados para renderizar no srcDoc.
        assert "padding: 16px" in login["html_content"]
        assert "window.__mock = true" in login["html_content"]
        assert "design-system.css" not in login["html_content"]

        tokens_res = await client.get(f"/api/tokens/{project_id}")
        assert tokens_res.status_code == 200
        tokens = tokens_res.json()
        assert tokens["light_tokens"]["color-primary"] == "#0f766e"
        assert tokens["light_tokens"]["space-4"] == "16px"
        assert tokens["dark_tokens"]["color-primary"] == "#2dd4bf"

        exported = await client.get(f"/api/projects/{project_id}/export/design")
        assert exported.status_code == 200
        assert exported.headers["content-type"] == "application/zip"
        files = _read_zip(exported.content)
        assert "design/tokens.json" in files
        canvas_path = next(name for name in files if name.endswith("canvas.json"))
        assert "Entrar" in "".join(
            content for name, content in files.items() if name.endswith(".html")
        )
        exported_tokens = json.loads(files["design/tokens.json"])
        assert exported_tokens["light"]["color"]["primary"]["$value"] == "#0f766e"

        # Round-trip: o ZIP exportado reimporta com as mesmas telas.
        reimported = await client.post(
            "/api/projects/import/design",
            data={"name": "Corpus Reimportado"},
            files={"file": ("design-export.zip", exported.content, "application/zip")},
        )
        assert reimported.status_code == 200, reimported.text
        assert reimported.json()["screens"] == 2
        assert reimported.json()["canvases"] == 1
        assert canvas_path.startswith("design/")


@pytest.mark.asyncio
async def test_import_rejects_invalid_archive():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        await _register(client)
        response = await client.post(
            "/api/projects/import/design",
            data={"name": "Inválido"},
            files={"file": ("design.zip", b"nao-e-um-zip", "application/zip")},
        )
        assert response.status_code == 400
        assert "zip" in response.json()["detail"].lower()
