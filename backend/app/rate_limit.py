"""Rate limiting em memória (janela deslizante) para endpoints sensíveis.

Sem dependência externa e suficiente para uma instância. Para múltiplas
réplicas, trocar o backend por Redis mantendo a mesma interface.
"""

import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# (método, caminho) -> (limite, janela em segundos)
# Limites por IP (janela de 60s). Registro é mais permissivo porque uma
# organização atrás de NAT compartilha o mesmo IP.
RULES: Dict[Tuple[str, str], Tuple[int, int]] = {
    ("POST", "/api/auth/login"): (30, 60),
    ("POST", "/api/auth/register"): (60, 60),
    ("POST", "/api/auth/change-password"): (5, 60),
    ("POST", "/api/auth/forgot-password"): (5, 60),
    ("POST", "/api/auth/reset-password"): (10, 60),
    ("POST", "/api/auth/verify-email"): (10, 60),
    ("POST", "/api/auth/resend-verification"): (5, 60),
}

# Prefixos com limite por minuto, aplicados a qualquer método mutante.
AI_PREFIX = "/api/ai/"
AI_LIMIT = 30
MCP_PREFIX = "/mcp"
MCP_LIMIT = 120
PUBLIC_COMMENT_LIMIT = 20

MAX_TRACKED_KEYS = 20_000


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def _client_key(self, scope: Scope) -> str:
        client = scope.get("client")
        return client[0] if client else "unknown"

    def _rule_for(self, method: str, path: str) -> Tuple[int, int]:
        if method == "POST" and (method, path) in RULES:
            return RULES[(method, path)]
        if path.startswith(AI_PREFIX) and method == "POST":
            return (AI_LIMIT, 60)
        if path.startswith(MCP_PREFIX):
            return (MCP_LIMIT, 60)
        if (
            method == "POST"
            and path.startswith("/api/public/p/")
            and path.endswith("/comments")
        ):
            return (PUBLIC_COMMENT_LIMIT, 60)
        return (0, 0)

    def _prune(self, now: float) -> None:
        if len(self._hits) <= MAX_TRACKED_KEYS:
            return
        stale = [key for key, hits in self._hits.items() if not hits or now - hits[-1] > 60]
        for key in stale:
            self._hits.pop(key, None)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "")
        limit, window = self._rule_for(method, path)

        if not limit:
            await self.app(scope, receive, send)
            return

        now = time.monotonic()
        self._prune(now)
        key = f"{self._client_key(scope)}:{method}:{path}"
        hits = self._hits[key]
        while hits and now - hits[0] > window:
            hits.popleft()

        if len(hits) >= limit:
            retry_after = max(1, int(window - (now - hits[0])) + 1)
            response = JSONResponse(
                {"detail": "Muitas requisições. Tente novamente em instantes."},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        hits.append(now)
        await self.app(scope, receive, send)
