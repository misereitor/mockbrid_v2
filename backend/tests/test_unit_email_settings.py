"""Testes unitários do envio de e-mail configurável e dos tokens de auth."""

import aiosmtplib
import pytest

from app import mailer
from app.auth_tokens import (
    RESET_PASSWORD,
    TOKEN_TTL,
    VERIFY_EMAIL,
    hash_auth_token,
)
from app.crypto import encrypt_secret
from app.models import EmailSettings


def _row(**overrides) -> EmailSettings:
    row = EmailSettings(
        provider="smtp",
        from_email="nao-responda@empresa.com",
        from_name="Mockbird",
        reply_to="",
        app_base_url="https://app.empresa.com/",
        require_verification=True,
        smtp_host="smtp.empresa.com",
        smtp_port=587,
        smtp_username="user",
        encrypted_smtp_password=encrypt_secret("segredo"),
        smtp_security="starttls",
        encrypted_resend_api_key="",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def test_provider_ready_requires_credentials():
    assert mailer.provider_ready(_row()) is True
    assert mailer.provider_ready(_row(provider="disabled")) is False
    assert mailer.provider_ready(_row(smtp_host="")) is False

    resend = _row(provider="resend", encrypted_resend_api_key="")
    assert mailer.provider_ready(resend) is False
    resend.encrypted_resend_api_key = encrypt_secret("re_123")
    assert mailer.provider_ready(resend) is True


def test_build_link_normalizes_slashes():
    assert mailer.build_link(_row(), "/reset-password?token=x") == (
        "https://app.empresa.com/reset-password?token=x"
    )
    assert mailer.build_link(_row(), "verify") == "https://app.empresa.com/verify"


def test_build_link_requires_url(monkeypatch):
    monkeypatch.setattr(mailer.settings, "APP_BASE_URL", "")
    with pytest.raises(mailer.EmailNotConfigured):
        mailer.build_link(_row(app_base_url=""), "/verify")


@pytest.mark.asyncio
async def test_send_email_refuses_when_disabled(monkeypatch):
    row = _row(provider="disabled")

    async def fake_settings(_db):
        return row

    monkeypatch.setattr(mailer, "get_email_settings", fake_settings)
    with pytest.raises(mailer.EmailNotConfigured):
        await mailer.send_email(None, to="a@b.com", subject="x", text="y")


@pytest.mark.asyncio
async def test_smtp_dispatch_uses_starttls_and_from_header(monkeypatch):
    row = _row()
    captured = {}

    async def fake_send(message, **kwargs):
        captured["message"] = message
        captured["kwargs"] = kwargs

    monkeypatch.setattr(aiosmtplib, "send", fake_send)

    await mailer._send_smtp(
        row, row.from_email, row.from_name, "dest@empresa.com", "Assunto", "texto", "<b>html</b>"
    )

    assert captured["message"]["Subject"] == "Assunto"
    assert "Mockbird <nao-responda@empresa.com>" == captured["message"]["From"]
    assert captured["kwargs"]["hostname"] == "smtp.empresa.com"
    assert captured["kwargs"]["start_tls"] is True
    assert captured["kwargs"]["use_tls"] is False
    assert captured["kwargs"]["password"] == "segredo"


class _FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


@pytest.mark.asyncio
async def test_resend_dispatch_payload(monkeypatch):
    row = _row(provider="resend", encrypted_resend_api_key=encrypt_secret("re_key"))
    captured = {}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, url, headers=None, json=None):
            captured.update({"url": url, "headers": headers, "json": json})
            return _FakeResponse(200)

    monkeypatch.setattr(mailer.httpx, "AsyncClient", FakeClient)

    await mailer._send_resend(
        row, row.from_email, row.from_name, "dest@empresa.com", "Oi", "texto", "<b>html</b>"
    )

    assert captured["url"] == mailer.RESEND_ENDPOINT
    assert captured["headers"]["Authorization"] == "Bearer re_key"
    assert captured["json"]["to"] == ["dest@empresa.com"]
    assert captured["json"]["html"] == "<b>html</b>"


@pytest.mark.asyncio
async def test_resend_error_becomes_delivery_error(monkeypatch):
    row = _row(provider="resend", encrypted_resend_api_key=encrypt_secret("re_key"))

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, *_args, **_kwargs):
            return _FakeResponse(422, "domínio não verificado")

    monkeypatch.setattr(mailer.httpx, "AsyncClient", FakeClient)

    with pytest.raises(mailer.EmailDeliveryError) as exc:
        await mailer._send_resend(
            row, row.from_email, row.from_name, "dest@empresa.com", "Oi", "texto", None
        )
    assert "422" in str(exc.value)


def test_auth_token_hash_is_stable_and_secret():
    raw = "token-super-secreto"
    assert hash_auth_token(raw) == hash_auth_token(raw)
    assert hash_auth_token(raw) != raw
    assert len(hash_auth_token(raw)) == 64


def test_token_ttl_definitions():
    assert TOKEN_TTL[RESET_PASSWORD].total_seconds() == 3600
    assert TOKEN_TTL[VERIFY_EMAIL].total_seconds() == 48 * 3600
