"""Tokens de uso único para verificação de e-mail e redefinição de senha."""

import hashlib
import secrets
from datetime import timedelta
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models import AuthToken
from app.timeutils import utcnow

VERIFY_EMAIL = "verify_email"
RESET_PASSWORD = "reset_password"

TOKEN_TTL = {
    VERIFY_EMAIL: timedelta(hours=48),
    RESET_PASSWORD: timedelta(hours=1),
}


def hash_auth_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def issue_auth_token(db: AsyncSession, user_id: str, kind: str) -> str:
    """Cria um token novo, invalidando os anteriores do mesmo tipo."""
    await db.execute(delete(AuthToken).where(AuthToken.user_id == user_id, AuthToken.kind == kind))
    raw = secrets.token_urlsafe(32)
    token = AuthToken(
        user_id=user_id,
        kind=kind,
        token_hash=hash_auth_token(raw),
        expires_at=utcnow() + TOKEN_TTL.get(kind, timedelta(hours=1)),
    )
    db.add(token)
    await db.flush()
    return raw


async def consume_auth_token(
    db: AsyncSession, raw: str, kind: str
) -> Optional[AuthToken]:
    """Devolve o token válido (não usado, não expirado) ou None."""
    if not raw or not raw.strip():
        return None
    res = await db.execute(
        select(AuthToken).where(
            AuthToken.token_hash == hash_auth_token(raw.strip()),
            AuthToken.kind == kind,
            AuthToken.used_at.is_(None),
        )
    )
    token = res.scalars().first()
    if not token or token.expires_at < utcnow():
        return None
    return token
