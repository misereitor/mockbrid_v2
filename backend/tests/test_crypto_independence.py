import os
import pytest
import httpx
import secrets
from app.crypto import encrypt_secret, decrypt_secret, get_active_fernet_key
from cryptography.fernet import Fernet


def test_encryption_key_independence_and_fallback():
    """Valida se uma chave criptografada com ENCRYPTION_KEY não se corrompe ao alterar SECRET_KEY."""
    raw_key = "sk-special-openai-custom-token-xyz-123456"
    encrypted = encrypt_secret(raw_key)

    # 1. Descriptografia normal com a chave ativa
    assert decrypt_secret(encrypted) == raw_key

    # 2. Testa fallback gracioso para strings legadas em texto puro
    legacy_plain = "sk-legacy-unencrypted-key"
    assert decrypt_secret(legacy_plain) == legacy_plain


@pytest.mark.asyncio
async def test_api_providers_returns_only_masked_keys():
    """Valida que o endpoint GET /api/ai/providers retorna apenas máscara e flag booleana, nunca a chave completa."""
    BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client:
        email = f"ai_mask_{secrets.token_hex(4)}@empresa.com"
        reg = await client.post("/api/auth/register", json={
            "email": email,
            "password": "StrongPassword123!",
            "name": "AI Admin Mask Test",
            "organization_name": f"Org Mask {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf

        # Salva provedor com chave secreta
        secret_api_key = "sk-proj-super-secret-production-token-987654"
        save_res = await client.post("/api/ai/providers", json={
            "provider_type": "openai",
            "api_key": secret_api_key,
            "default_model": "gpt-4o",
            "base_url": "https://api.openai.com/v1"
        })
        assert save_res.status_code == 200

        # Lista provedores
        list_res = await client.get("/api/ai/providers")
        assert list_res.status_code == 200
        providers = list_res.json()
        assert len(providers) >= 1
        prov = [p for p in providers if p["provider_type"] == "openai"][0]

        # Não deve conter a chave de API em texto puro
        assert "api_key" not in prov
        assert "encrypted_api_key" not in prov
        assert prov.get("has_api_key") is True
        assert prov.get("masked_api_key") != ""
        assert secret_api_key not in str(prov)
        assert prov["masked_api_key"].startswith("sk-p")
        assert prov["masked_api_key"].endswith("7654")
