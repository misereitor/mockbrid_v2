import os
import secrets
import httpx
import pytest

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_scenarios_lifecycle_and_public_presentation():
    pwd = "PasswordStrong123!"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as client:
        # 1. Registro e autenticação
        reg = await client.post(
            "/api/auth/register",
            json={
                "email": f"scenario_{secrets.token_hex(4)}@empresa.com",
                "password": pwd,
                "name": "Dev Backend",
                "organization_name": f"Org Scenarios {secrets.token_hex(3)}",
            },
        )
        assert reg.status_code == 200, reg.text
        csrf = client.cookies.get("mockbird_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        # 2. Criação do projeto
        proj = await client.post("/api/projects", json={"name": "SaaS Demo Mock"}, headers=headers)
        assert proj.status_code == 200, proj.text
        data = proj.json()
        project_id = data["id"]
        slug = data["slug"]

        # 3. GET /scenarios inicializa os cenários padrão
        scen_res = await client.get(f"/api/projects/{project_id}/scenarios", headers=headers)
        assert scen_res.status_code == 200, scen_res.text
        scenarios = scen_res.json()
        assert len(scenarios) >= 3
        names = [s["name"] for s in scenarios]
        assert "Cenário Sucesso" in names
        assert "Cenário Vazio" in names
        assert "Cenário Erro" in names

        # 4. POST /scenarios cria um cenário novo
        custom_payload = {
            "name": "Black Friday VIP",
            "mock_data": {
                "user": {"name": "Carlos VIP", "role": "Premium"},
                "stats": {"revenue": "R$ 145.000", "orders": 850},
                "items": ["Plano Pro Anual", "Suporte 24/7"]
            }
        }
        create_res = await client.post(
            f"/api/projects/{project_id}/scenarios",
            json=custom_payload,
            headers=headers
        )
        assert create_res.status_code == 200, create_res.text
        created_scen = create_res.json()
        assert created_scen["name"] == "Black Friday VIP"
        assert created_scen["mock_data"]["user"]["name"] == "Carlos VIP"
        custom_id = created_scen["id"]

        # 5. Publicar projeto e checar se o endpoint público de apresentação traz os cenários
        pub_res = await client.post(f"/api/projects/{project_id}/publish", headers=headers)
        assert pub_res.status_code == 200, pub_res.text

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as anon:
            public_res = await anon.get(f"/api/public/p/{slug}")
            assert public_res.status_code == 200, public_res.text
            public_data = public_res.json()
            assert "scenarios" in public_data
            pub_scenarios = public_data["scenarios"]
            assert len(pub_scenarios) >= 4
            pub_names = [s["name"] for s in pub_scenarios]
            assert "Black Friday VIP" in pub_names

        # 6. DELETE /scenarios/{id} remove o cenário
        del_res = await client.delete(f"/api/projects/{project_id}/scenarios/{custom_id}", headers=headers)
        assert del_res.status_code == 200, del_res.text

        # 7. Verifica se foi removido
        after_del = await client.get(f"/api/projects/{project_id}/scenarios", headers=headers)
        assert after_del.status_code == 200
        after_names = [s["name"] for s in after_del.json()]
        assert "Black Friday VIP" not in after_names
