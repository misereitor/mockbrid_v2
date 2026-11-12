"""Contratos de segurança e validação dos fluxos de e-mail/administração.

Não envia e-mail de verdade: cobre autorização, formato das respostas e tokens
inválidos, que são determinísticos em qualquer ambiente.
"""

import os
import secrets

import httpx
import pytest

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_email_endpoints_require_valid_tokens_and_system_admin():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        email = f"email_flow_{secrets.token_hex(4)}@empresa.com"
        res = await client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "SecureEmailPass123!",
                "name": "Email Flow",
                "organization_name": f"Email Org {secrets.token_hex(3)}",
            },
        )
        assert res.status_code == 200, res.text
        user = res.json()
        assert user["email"] == email
        assert user["is_system_admin"] is False
        assert user["email_verified"] is False

        csrf = client.cookies.get("mockbird_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        status = await client.get("/api/auth/email-status")
        assert status.status_code == 200
        body = status.json()
        assert set(body) == {"configured", "require_verification", "email_verified"}
        assert body["email_verified"] is False

        # Usuário comum nunca acessa a configuração global de e-mail.
        admin_read = await client.get("/api/admin/email-settings")
        assert admin_read.status_code == 403
        admin_write = await client.put(
            "/api/admin/email-settings",
            headers=headers,
            json={"provider": "disabled"},
        )
        assert admin_write.status_code == 403

        # Tokens inválidos falham com 400, não com erro interno.
        bad_reset = await client.post(
            "/api/auth/reset-password",
            headers=headers,
            json={"token": "token-invalido-123456", "new_password": "NovaSenhaForte123!"},
        )
        assert bad_reset.status_code == 400
        bad_verify = await client.post(
            "/api/auth/verify-email",
            headers=headers,
            json={"token": "token-invalido-123456"},
        )
        assert bad_verify.status_code == 400
        bad_invite = await client.post(
            "/api/org/members/accept-invite",
            headers=headers,
            json={"token": "convite-invalido-123456", "password": "NovaSenhaForte123!"},
        )
        assert bad_invite.status_code == 400

        # E-mail com formato inválido é rejeitado pelo schema.
        invalid = await client.post(
            "/api/auth/forgot-password",
            headers=headers,
            json={"email": "nao-e-email"},
        )
        assert invalid.status_code == 422
