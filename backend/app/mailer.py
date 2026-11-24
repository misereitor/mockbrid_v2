"""Envio de e-mail transacional configurável pelo administrador.

Dois transportes suportados, ambos configurados pela tela de administração:

- ``smtp``   -> qualquer provedor SMTP (Gmail, SES, Postmark, Mailgun, Zoho...)
- ``resend`` -> API HTTP da Resend (https://resend.com)

As credenciais ficam cifradas com Fernet no banco (``crypto.py``). Quando nada
está configurado, ``EmailNotConfigured`` é levantado com uma mensagem clara para
a UI — nunca há envio silencioso.
"""

import html as html_lib
import logging
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.crypto import decrypt_secret
from app.models import EmailSettings
from app.timeutils import utcnow

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"


class EmailNotConfigured(RuntimeError):
    """Nenhum transporte de e-mail foi configurado pelo administrador."""


class EmailDeliveryError(RuntimeError):
    """O provedor recusou ou não respondeu ao envio."""


def _resolve_settings_url(row: EmailSettings) -> str:
    url = (row.app_base_url or "").strip() or (settings.APP_BASE_URL or "").strip()
    return url.rstrip("/")


async def get_email_settings(db: AsyncSession) -> EmailSettings:
    """Retorna a linha única de configuração (singleton), criando-a se ainda não existir."""
    row = await db.get(EmailSettings, "singleton")
    if row:
        return row
    res = await db.execute(select(EmailSettings).order_by(EmailSettings.updated_at.desc()))
    row = res.scalars().first()
    if row:
        if row.id != "singleton":
            row.id = "singleton"
            await db.commit()
            await db.refresh(row)
        return row
    row = EmailSettings(id="singleton")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def provider_ready(row: EmailSettings) -> bool:
    if row.provider == "smtp":
        return bool(row.from_email and row.smtp_host)
    if row.provider == "resend":
        return bool(row.from_email and decrypt_secret(row.encrypted_resend_api_key))
    return False


def public_base_url(row: EmailSettings) -> str:
    return _resolve_settings_url(row)


def build_link(row: EmailSettings, path: str) -> str:
    base = _resolve_settings_url(row)
    if not base:
        raise EmailNotConfigured(
            "Defina a URL pública do app nas configurações de e-mail."
        )
    return f"{base}{path if path.startswith('/') else '/' + path}"


def _render_branded(title: str, intro: str, cta_label: str, cta_url: str) -> tuple[str, str]:
    safe_title = html_lib.escape(title)
    safe_intro = html_lib.escape(intro)
    safe_label = html_lib.escape(cta_label)
    safe_url = html_lib.escape(cta_url, quote=True)
    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><body style="margin:0;background:#09090b;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#e4e4e7">
  <div style="max-width:520px;margin:0 auto;padding:40px 24px">
    <div style="font-size:15px;font-weight:700;color:#fff;margin-bottom:28px">Mockbird</div>
    <div style="background:#121215;border:1px solid #27272a;border-radius:12px;padding:32px">
      <h1 style="font-size:20px;margin:0 0 12px;color:#fff">{safe_title}</h1>
      <p style="font-size:14px;line-height:1.6;color:#a1a1aa;margin:0 0 24px">{safe_intro}</p>
      <a href="{safe_url}" style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;font-size:14px;font-weight:600;padding:11px 20px;border-radius:8px">{safe_label}</a>
      <p style="font-size:12px;line-height:1.6;color:#71717a;margin:24px 0 0">Se o botão não funcionar, copie e cole este link no navegador:<br><span style="color:#a1a1aa;word-break:break-all">{safe_url}</span></p>
    </div>
    <p style="font-size:11px;color:#52525b;margin:20px 0 0">Você recebeu este e-mail porque uma ação foi solicitada na sua conta Mockbird.</p>
  </div>
</body></html>"""
    text = f"{title}\n\n{intro}\n\n{cta_label}: {cta_url}\n"
    return html, text


async def send_email(
    db: AsyncSession,
    *,
    to: str,
    subject: str,
    text: str,
    html: Optional[str] = None,
) -> None:
    row = await get_email_settings(db)
    if not provider_ready(row):
        raise EmailNotConfigured(
            "O envio de e-mail ainda não foi configurado. Peça ao administrador "
            "para preencher Configurações → E-mail."
        )

    from_email = row.from_email.strip()
    from_name = (row.from_name or "Mockbird").strip()

    if row.provider == "smtp":
        await _send_smtp(row, from_email, from_name, to, subject, text, html)
    elif row.provider == "resend":
        await _send_resend(row, from_email, from_name, to, subject, text, html)
    else:
        raise EmailNotConfigured("Provedor de e-mail inválido.")


async def _send_smtp(
    row: EmailSettings,
    from_email: str,
    from_name: str,
    to: str,
    subject: str,
    text: str,
    html: Optional[str],
) -> None:
    import aiosmtplib

    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to
    if row.reply_to:
        msg["Reply-To"] = row.reply_to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_email.split("@")[-1] or None)
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    security = (row.smtp_security or "starttls").lower()
    password = decrypt_secret(row.encrypted_smtp_password)
    try:
        await aiosmtplib.send(
            msg,
            hostname=row.smtp_host.strip(),
            port=int(row.smtp_port or 587),
            username=(row.smtp_username or None),
            password=(password or None),
            start_tls=(security == "starttls"),
            use_tls=(security == "ssl"),
            timeout=20,
        )
    except EmailNotConfigured:
        raise
    except Exception as exc:  # noqa: BLE001 - mensagem amigável para a UI
        logger.warning("Falha ao enviar e-mail via SMTP: %s", exc)
        raise EmailDeliveryError(f"Falha no SMTP: {exc}") from exc


async def _send_resend(
    row: EmailSettings,
    from_email: str,
    from_name: str,
    to: str,
    subject: str,
    text: str,
    html: Optional[str],
) -> None:
    api_key = decrypt_secret(row.encrypted_resend_api_key)
    payload = {
        "from": formataddr((from_name, from_email)),
        "to": [to],
        "subject": subject,
        "text": text,
    }
    if html:
        payload["html"] = html
    if row.reply_to:
        payload["reply_to"] = row.reply_to

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(
                RESEND_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as exc:
        logger.warning("Falha de rede ao enviar e-mail via Resend: %s", exc)
        raise EmailDeliveryError(f"Falha de rede ao falar com a Resend: {exc}") from exc

    if res.status_code >= 400:
        detail = res.text[:300]
        logger.warning("Resend recusou o envio (%s): %s", res.status_code, detail)
        raise EmailDeliveryError(f"Resend respondeu {res.status_code}: {detail}")


# --- Templates -------------------------------------------------------------


async def send_verification_email(db: AsyncSession, user, url: str) -> None:
    html, text = _render_branded(
        "Confirme seu e-mail",
        f"Olá, {user.name}. Confirme este endereço para garantir o acesso à sua conta Mockbird.",
        "Confirmar e-mail",
        url,
    )
    await send_email(
        db,
        to=user.email,
        subject="Confirme seu e-mail — Mockbird",
        text=text,
        html=html,
    )


async def send_password_reset_email(db: AsyncSession, user, url: str) -> None:
    html, text = _render_branded(
        "Redefinir sua senha",
        f"Olá, {user.name}. Recebemos um pedido para redefinir a senha da sua conta. "
        "O link expira em 1 hora e só pode ser usado uma vez.",
        "Criar nova senha",
        url,
    )
    await send_email(
        db,
        to=user.email,
        subject="Redefinição de senha — Mockbird",
        text=text,
        html=html,
    )


async def send_invite_email(
    db: AsyncSession,
    *,
    to: str,
    inviter_name: str,
    organization_name: str,
    role: str,
    url: str,
) -> None:
    html, text = _render_branded(
        f"Convite para {organization_name}",
        f"{inviter_name} convidou você para participar da organização "
        f"{organization_name} como {role}. O convite expira em 48 horas.",
        "Aceitar convite",
        url,
    )
    await send_email(
        db,
        to=to,
        subject=f"Convite para {organization_name} — Mockbird",
        text=text,
        html=html,
    )


async def send_test_email(db: AsyncSession, to: str) -> None:
    html, text = _render_branded(
        "Teste de configuração",
        "Se você recebeu este e-mail, o envio está funcionando. "
        f"Configuração validada em {utcnow().strftime('%d/%m/%Y %H:%M')} UTC.",
        "Abrir o Mockbird",
        build_link(await get_email_settings(db), "/dashboard"),
    )
    await send_email(
        db,
        to=to,
        subject="Teste de e-mail — Mockbird",
        text=text,
        html=html,
    )
