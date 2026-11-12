from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.authz import ACTION_MIN_ROLE, ROLE_HIERARCHY
from app.quotas import enforce_ai_quota, extract_usage
from app.rate_limit import RULES, RateLimitMiddleware


def _user(**kw):
    base = dict(tokens_used_month=0, monthly_token_limit=1000, role="editor")
    base.update(kw)
    return SimpleNamespace(**base)


def test_quota_allows_within_limit():
    enforce_ai_quota(_user(), None)


def test_quota_blocks_user_over_limit():
    with pytest.raises(HTTPException) as exc:
        enforce_ai_quota(_user(tokens_used_month=1000), None)
    assert exc.value.status_code == 429


def test_quota_blocks_provider_over_limit():
    prov = SimpleNamespace(provider_type="openai", tokens_used_month=10, monthly_token_limit=10)
    with pytest.raises(HTTPException) as exc:
        enforce_ai_quota(_user(), prov)
    assert exc.value.status_code == 429


def test_usage_extraction_supports_both_shapes():
    assert extract_usage({"usage": {"prompt_tokens": 3, "completion_tokens": 4}}) == (3, 4)
    assert extract_usage({"usage": {"input_tokens": 5, "output_tokens": 6}}) == (5, 6)
    assert extract_usage({}) == (0, 0)


def test_role_hierarchy_is_strictly_ordered():
    roles = ["viewer", "commenter", "editor", "admin", "owner"]
    levels = [ROLE_HIERARCHY[r] for r in roles]
    assert levels == sorted(levels)
    assert ACTION_MIN_ROLE["edit"] == "editor"


async def _ok(request):
    return PlainTextResponse("ok")


def _app() -> Starlette:
    app = Starlette(routes=[Route("/api/auth/login", _ok, methods=["POST"])])
    app.add_middleware(RateLimitMiddleware)
    return app


@pytest.mark.asyncio
async def test_login_rate_limit_returns_429():
    limit = RULES[("POST", "/api/auth/login")][0]
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        statuses = [(await client.post("/api/auth/login")).status_code for _ in range(limit + 1)]
    assert statuses[:limit] == [200] * limit
    assert statuses[limit] == 429
