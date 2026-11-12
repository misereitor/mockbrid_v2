"""Configurações globais da instância — restritas ao administrador do sistema."""

import logging
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.routes_auth import require_system_admin
from app.crypto import decrypt_secret, encrypt_secret
from app.database import get_db
from app.mailer import (
    EmailDeliveryError,
    EmailNotConfigured,
    get_email_settings,
    provider_ready,
    send_test_email,
)
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class EmailSettingsUpdate(BaseModel):
    provider: Literal["disabled", "smtp", "resend"] = "disabled"
    from_email: str = Field(default="", max_length=255)
    from_name: str = Field(default="Mockbird", max_length=120)
    reply_to: str = Field(default="", max_length=255)
    app_base_url: str = Field(default="", max_length=255)
    require_verification: bool = False

    smtp_host: str = Field(default="", max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = Field(default="", max_length=255)
    smtp_password: Optional[str] = Field(default=None, max_length=512)
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    clear_smtp_password: bool = False

    resend_api_key: Optional[str] = Field(default=None, max_length=512)
    clear_resend_api_key: bool = False


class EmailSettingsOut(BaseModel):
    provider: str
    from_email: str
    from_name: str
    reply_to: str
    app_base_url: str
    require_verification: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_security: str
    has_smtp_password: bool
    has_resend_api_key: bool
    configured: bool
    updated_at: datetime


def _to_out(row) -> EmailSettingsOut:
    return EmailSettingsOut(
        provider=row.provider,
        from_email=row.from_email,
        from_name=row.from_name,
        reply_to=row.reply_to,
        app_base_url=row.app_base_url,
        require_verification=row.require_verification,
        smtp_host=row.smtp_host,
        smtp_port=row.smtp_port,
        smtp_username=row.smtp_username,
        smtp_security=row.smtp_security,
        has_smtp_password=bool(decrypt_secret(row.encrypted_smtp_password)),
        has_resend_api_key=bool(decrypt_secret(row.encrypted_resend_api_key)),
        configured=provider_ready(row),
        updated_at=row.updated_at,
    )


def _validate(payload: EmailSettingsUpdate) -> None:
    if payload.provider != "disabled":
        if not payload.from_email.strip():
            raise HTTPException(status_code=400, detail="Informe o e-mail remetente.")
        if "@" not in payload.from_email:
            raise HTTPException(status_code=400, detail="E-mail remetente inválido.")
    if payload.reply_to and "@" not in payload.reply_to:
        raise HTTPException(status_code=400, detail="E-mail de resposta inválido.")
    if payload.app_base_url and not payload.app_base_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail="A URL pública deve começar com http:// ou https://",
        )
    if payload.provider == "smtp" and not payload.smtp_host.strip():
        raise HTTPException(status_code=400, detail="Informe o host SMTP.")


@router.get("/email-settings", response_model=EmailSettingsOut)
async def read_email_settings(
    _: User = Depends(require_system_admin),
    db: AsyncSession = Depends(get_db),
):
    return _to_out(await get_email_settings(db))


@router.put("/email-settings", response_model=EmailSettingsOut)
async def update_email_settings(
    payload: EmailSettingsUpdate,
    current_user: User = Depends(require_system_admin),
    db: AsyncSession = Depends(get_db),
):
    _validate(payload)
    row = await get_email_settings(db)

    row.provider = payload.provider
    row.from_email = payload.from_email.strip()
    row.from_name = payload.from_name.strip() or "Mockbird"
    row.reply_to = payload.reply_to.strip()
    row.app_base_url = payload.app_base_url.strip().rstrip("/")
    row.require_verification = payload.require_verification
    row.smtp_host = payload.smtp_host.strip()
    row.smtp_port = payload.smtp_port
    row.smtp_username = payload.smtp_username.strip()
    row.smtp_security = payload.smtp_security
    row.updated_by = current_user.id

    if payload.clear_smtp_password:
        row.encrypted_smtp_password = ""
    elif payload.smtp_password:
        row.encrypted_smtp_password = encrypt_secret(payload.smtp_password)

    if payload.clear_resend_api_key:
        row.encrypted_resend_api_key = ""
    elif payload.resend_api_key:
        row.encrypted_resend_api_key = encrypt_secret(payload.resend_api_key)

    await db.commit()
    await db.refresh(row)
    logger.info(
        "Configurações de e-mail atualizadas por %s (provider=%s, configured=%s)",
        current_user.email,
        row.provider,
        provider_ready(row),
    )
    return _to_out(row)


@router.post("/email-settings/test")
async def test_email_settings(
    current_user: User = Depends(require_system_admin),
    db: AsyncSession = Depends(get_db),
):
    """Envia um e-mail de teste para o próprio administrador."""
    try:
        await send_test_email(db, current_user.email)
    except EmailNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmailDeliveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "sent", "to": current_user.email}
