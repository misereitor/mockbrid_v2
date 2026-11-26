"""Resolve o usuário logado quando a rota também aceita visitantes anônimos.

Usado por rotas públicas que mudam de comportamento se houver sessão válida
(ex.: share link `org` e entrega de assets). Nunca levanta 401: devolve `None`.
"""

from typing import Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.auth import decode_access_token, hash_session_token
from app.models import Session, User
from app.timeutils import utcnow


async def get_optional_user(request: Request, db: AsyncSession) -> Optional[User]:
    token = request.cookies.get("mockbird_token")
    if not token:
        header = request.headers.get("Authorization") or ""
        if header.startswith("Bearer "):
            token = header[len("Bearer "):]
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    session_res = await db.execute(
        select(Session).where(Session.token == hash_session_token(token))
    )
    session = session_res.scalars().first()
    if not session or session.expires_at < utcnow():
        return None
    user_res = await db.execute(select(User).where(User.id == payload["sub"]))
    user = user_res.scalars().first()
    if not user or not user.is_active:
        return None
    return user
