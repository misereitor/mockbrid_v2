"""Endpoint WebSocket de colaboração por projeto."""

import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.future import select

from app.auth import decode_access_token, hash_session_token
from app.authz import authorize_project
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Session, User
from app.timeutils import utcnow
from app.ws import Participant, broadcaster

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

AUTH_CLOSE_CODE = 4401
FORBIDDEN_CLOSE_CODE = 4403


async def _authenticate(websocket: WebSocket) -> Optional[User]:
    token = websocket.query_params.get("token") or websocket.cookies.get("mockbird_token")
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    async with AsyncSessionLocal() as db:
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
        # Guarda referência simples; a sessão expira em seguida.
        return user


def _origin_allowed(websocket: WebSocket) -> bool:
    """Impede cross-site WebSocket hijacking com o cookie de sessão."""
    origin = websocket.headers.get("origin")
    if not origin:
        # Clientes nativos (MCP/CLI) não enviam Origin; a autenticação por token
        # explícito continua valendo.
        return True
    return origin.rstrip("/") in [o.rstrip("/") for o in settings.cors_origins]


@router.websocket("/api/ws/projects/{project_id}")
async def project_socket(websocket: WebSocket, project_id: str):
    if not _origin_allowed(websocket):
        await websocket.close(code=FORBIDDEN_CLOSE_CODE)
        return

    user = await _authenticate(websocket)
    if not user:
        await websocket.close(code=AUTH_CLOSE_CODE)
        return

    async with AsyncSessionLocal() as db:
        try:
            await authorize_project(project_id, user, "read", db)
        except Exception:
            await websocket.close(code=FORBIDDEN_CLOSE_CODE)
            return

    await websocket.accept()
    participant = Participant(websocket, user.id, user.name)
    await broadcaster.connect(project_id, participant)
    try:
        await websocket.send_json(
            {
                "type": "ready",
                "project_id": project_id,
                "self": participant.public(),
                "participants": broadcaster.participants(project_id),
            }
        )
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            if kind == "ping":
                await websocket.send_json({"type": "pong"})
            elif kind == "cursor":
                await broadcaster.broadcast(
                    project_id,
                    {
                        "type": "cursor",
                        "user_id": participant.user_id,
                        "name": participant.name,
                        "color": participant.color,
                        "screen_id": message.get("screen_id"),
                        "x": message.get("x"),
                        "y": message.get("y"),
                    },
                    exclude=participant,
                )
            elif kind == "screen_update":
                # Exige papel de edição para emitir atualizações em tempo real
                async with AsyncSessionLocal() as db:
                    try:
                        await authorize_project(project_id, user, "edit", db)
                    except Exception:
                        continue

                await broadcaster.broadcast(
                    project_id,
                    {
                        "type": "screen_updated",
                        "screen_id": message.get("screen_id"),
                        "origin": participant.user_id,
                        "html_content": message.get("html_content"),
                        "css_content": message.get("css_content"),
                        "js_content": message.get("js_content"),
                    },
                    exclude=participant,
                )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Erro no WebSocket do projeto %s", project_id)
    finally:
        await broadcaster.disconnect(project_id, participant)

