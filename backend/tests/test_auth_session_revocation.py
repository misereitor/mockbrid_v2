import os
import pytest
import httpx
import secrets

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_logout_must_revoke_token_immediately():
    """Valida se após o logout ou revogação, o token antigo é estritamente rejeitado com 401."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client:
        email = f"revoc_tester_{secrets.token_hex(4)}@empresa.com"
        pwd = "PasswordStrong123!"
        reg = await client.post("/api/auth/register", json={
            "email": email,
            "password": pwd,
            "name": "Revocation Tester",
            "organization_name": f"Org Revoc {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200
        cookies = reg.cookies
        csrf = cookies.get("mockbird_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        # 1. Verifica que /api/auth/me funciona com a sessão ativa
        me_res = await client.get("/api/auth/me", cookies=cookies)
        assert me_res.status_code == 200

        # 2. Executa logout
        logout_res = await client.post("/api/auth/logout", cookies=cookies, headers=headers)
        assert logout_res.status_code == 200

        # 3. Tenta usar o mesmo cookie de token anterior após o logout
        # DEVE FALHAR com 401 Unauthorized porque a sessão foi revogada no banco
        reused_res = await client.get("/api/auth/me", cookies=cookies)
        assert reused_res.status_code == 401, (
            f"Esperava 401 Unauthorized após logout, mas recebeu {reused_res.status_code}: {reused_res.text}"
        )
