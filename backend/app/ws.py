"""Colaboração em tempo real por WebSocket.

Cada projeto tem uma sala em memória nesta instância. As mensagens trafegadas:

- `presence` (servidor)      -> participantes conectados no momento
- `cursor`   (cliente/servidor) -> posição do cursor de um participante
- `screen_updated` (servidor) -> conteúdo novo de uma tela (após salvar)
- `comment_created` (servidor) -> comentário novo no projeto
- `ping`/`pong`             -> keep-alive

Para múltiplas réplicas, publique `broadcaster.broadcast` em Redis/Postgres
NOTIFY mantendo a mesma interface.
"""

import asyncio
import hashlib
import logging
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


def user_color(user_id: str) -> str:
    palette = [
        "#2563eb",
        "#db2777",
        "#16a34a",
        "#d97706",
        "#7c3aed",
        "#0891b2",
        "#dc2626",
        "#4f46e5",
    ]
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return palette[int(digest[:8], 16) % len(palette)]


class Participant:
    def __init__(self, websocket: WebSocket, user_id: str, name: str) -> None:
        self.websocket = websocket
        self.user_id = user_id
        self.name = name
        self.color = user_color(user_id)

    def public(self) -> Dict[str, str]:
        return {"user_id": self.user_id, "name": self.name, "color": self.color}


class Broadcaster:
    def __init__(self) -> None:
        self._rooms: Dict[str, Set[Participant]] = {}
        self._lock = asyncio.Lock()

    def participants(self, project_id: str) -> List[Dict[str, str]]:
        room = self._rooms.get(project_id, set())
        # Um usuário em duas abas aparece uma vez só.
        seen: Dict[str, Dict[str, str]] = {}
        for p in room:
            seen.setdefault(p.user_id, p.public())
        return list(seen.values())

    async def connect(self, project_id: str, participant: Participant) -> None:
        async with self._lock:
            self._rooms.setdefault(project_id, set()).add(participant)
        await self.broadcast(
            project_id, {"type": "presence", "participants": self.participants(project_id)}
        )

    async def disconnect(self, project_id: str, participant: Participant) -> None:
        async with self._lock:
            room = self._rooms.get(project_id)
            if room:
                room.discard(participant)
                if not room:
                    self._rooms.pop(project_id, None)
        await self.broadcast(
            project_id, {"type": "presence", "participants": self.participants(project_id)}
        )

    async def broadcast(
        self,
        project_id: str,
        message: Dict[str, Any],
        exclude: Optional[Participant] = None,
    ) -> None:
        room = list(self._rooms.get(project_id, set()))
        if not room:
            return
        dead = []
        for participant in room:
            if participant is exclude:
                continue
            try:
                await participant.websocket.send_json(message)
            except Exception:
                dead.append(participant)
        for participant in dead:
            await self.disconnect(project_id, participant)


broadcaster = Broadcaster()
