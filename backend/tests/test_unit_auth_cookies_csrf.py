"""Testes unitários (sem stack) dos cookies de sessão e da proteção CSRF.

Monta um app mínimo só com o router de autenticação e troca `get_db` por um
banco falso em memória: nada aqui precisa de PostgreSQL nem de `BASE_URL`.
"""

import uuid
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.sql import Delete, Select

from app import routes_auth
from app.auth import create_access_token, hash_password, hash_session_token
from app.database import get_db
from app.models import EmailSettings, Session, User
from app.timeutils import utcnow

PASSWORD = "senha_forte_123"
PASSWORD_HASH = hash_password(PASSWORD)  # bcrypt é lento: calcula uma vez só
SESSION_MAX_AGE = 60 * 60 * 24 * 7


# ---------------------------------------------------------------------------
# Banco falso
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class FakeDB:
    """Responde só às consultas que `register`, `login`, `logout` e
    `get_current_user` fazem, olhando a tabela da instrução."""

    def __init__(self, users=(), sessions=()):
        self.users = list(users)
        self.sessions = list(sessions)

    async def execute(self, stmt, *_args, **_kwargs):
        text = str(stmt)
        if isinstance(stmt, Delete):
            if "sessions" in text:
                self.sessions = []
            return _Result([])
        assert isinstance(stmt, Select), f"instrução inesperada: {text}"
        params = stmt.compile().params
        if "FROM sessions" in text:
            token_hash = next(iter(params.values()))
            return _Result([s for s in self.sessions if s.token == token_hash])
        if "FROM users" in text:
            value = next(iter(params.values()))
            return _Result([u for u in self.users if value in (u.id, u.email)])
        return _Result([])

    async def get(self, model, key):
        if model is EmailSettings:
            return EmailSettings(id="singleton", require_verification=False, provider="disabled")
        return None

    async def scalar(self, _stmt):
        return len(self.users)

    def add(self, obj):
        # O flush real aplica os defaults de coluna (id, created_at); aqui só o id importa.
        if getattr(obj, "id", "") is None:
            obj.id = str(uuid.uuid4())
        if isinstance(obj, User):
            obj.created_at = obj.created_at or utcnow()
            for name, default in (("is_active", True), ("email_verified", False), ("is_system_admin", False)):
                if getattr(obj, name) is None:
                    setattr(obj, name, default)
            self.users.append(obj)
        elif isinstance(obj, Session):
            self.sessions.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def refresh(self, _obj):
        pass

    async def close(self):
        pass


def make_user(**overrides) -> User:
    user = User(
        id=str(uuid.uuid4()),
        organization_id=str(uuid.uuid4()),
        email="ana@empresa.com",
        password_hash=PASSWORD_HASH,
        name="Ana",
        role="owner",
        is_active=True,
        is_system_admin=False,
        email_verified=False,
        created_at=utcnow(),
    )
    for key, value in overrides.items():
        setattr(user, key, value)
    return user


def make_session_for(user: User, csrf_token: str) -> tuple[str, Session]:
    token = create_access_token({"sub": user.id, "org_id": user.organization_id, "role": user.role})
    session = Session(
        user_id=user.id,
        token=hash_session_token(token),
        csrf_token=csrf_token,
        expires_at=utcnow() + timedelta(days=7),
    )
    return token, session


def make_client(db: FakeDB, base_url: str = "http://testserver") -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(routes_auth.router)

    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


def parse_set_cookie(response: httpx.Response) -> dict[str, dict]:
    """Devolve {nome: {"value": ..., "flags": {atributo_em_minúsculas: valor|True}}}."""
    cookies = {}
    for header in response.headers.get_list("set-cookie"):
        name, _, rest = header.partition("=")
        value, _, attrs = rest.partition(";")
        flags = {}
        for attr in (a.strip() for a in attrs.split(";") if a.strip()):
            key, sep, val = attr.partition("=")
            flags[key.lower()] = val if sep else True
        cookies[name] = {"value": value, "flags": flags}
    return cookies


async def do_login(client: httpx.AsyncClient, **headers) -> httpx.Response:
    return await client.post("/api/auth/login", json={"email": "ana@empresa.com", "password": PASSWORD}, headers=headers)


async def do_register(client: httpx.AsyncClient, **headers) -> httpx.Response:
    return await client.post(
        "/api/auth/register",
        json={"name": "Bia", "email": "bia@empresa.com", "password": PASSWORD, "organization_name": "Empresa"},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Flags dos cookies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["login", "register"])
async def test_session_cookies_have_httponly_samesite_and_max_age(monkeypatch, action):
    monkeypatch.setattr(routes_auth.settings, "COOKIE_SECURE", False)
    async with make_client(FakeDB(users=[make_user()])) as client:
        response = await (do_login(client) if action == "login" else do_register(client))
    assert response.status_code == 200, response.text

    cookies = parse_set_cookie(response)
    assert set(cookies) == {"mockbird_token", "mockbird_csrf"}

    token = cookies["mockbird_token"]["flags"]
    assert token.get("httponly") is True, "o JWT de sessão não pode ser legível por JS"
    assert str(token.get("samesite")).lower() == "lax"
    assert token.get("max-age") == str(SESSION_MAX_AGE)
    assert token.get("path") == "/"

    # O cookie CSRF precisa ser legível pelo JS (vira cabeçalho X-CSRF-Token).
    csrf = cookies["mockbird_csrf"]["flags"]
    assert "httponly" not in csrf
    assert str(csrf.get("samesite")).lower() == "lax"
    assert csrf.get("max-age") == str(SESSION_MAX_AGE)


@pytest.mark.parametrize("action", ["login", "register"])
async def test_cookie_secure_true_forces_secure_flag_over_plain_http(monkeypatch, action):
    monkeypatch.setattr(routes_auth.settings, "COOKIE_SECURE", True)
    async with make_client(FakeDB(users=[make_user()]), base_url="http://testserver") as client:
        response = await (do_login(client) if action == "login" else do_register(client))
    cookies = parse_set_cookie(response)
    assert cookies["mockbird_token"]["flags"].get("secure") is True
    assert cookies["mockbird_csrf"]["flags"].get("secure") is True


async def test_cookie_secure_false_is_respected_even_behind_https_proxy(monkeypatch):
    """Produção também é acessada por HTTP (VPN): `false` explícito vale sempre."""
    monkeypatch.setattr(routes_auth.settings, "COOKIE_SECURE", False)
    async with make_client(FakeDB(users=[make_user()]), base_url="https://testserver") as client:
        response = await do_login(client, **{"X-Forwarded-Proto": "https"})
    cookies = parse_set_cookie(response)
    assert "secure" not in cookies["mockbird_token"]["flags"]
    assert "secure" not in cookies["mockbird_csrf"]["flags"]


@pytest.mark.parametrize(
    ("base_url", "forwarded_proto", "expect_secure"),
    [
        ("http://testserver", None, False),
        ("https://testserver", None, True),
        ("http://testserver", "https", True),
        ("http://testserver", "https, http", True),  # primeiro valor da cadeia manda
        ("http://testserver", "http", False),
    ],
)
async def test_cookie_secure_unset_follows_request_scheme(monkeypatch, base_url, forwarded_proto, expect_secure):
    monkeypatch.setattr(routes_auth.settings, "COOKIE_SECURE", None)
    headers = {"X-Forwarded-Proto": forwarded_proto} if forwarded_proto else {}
    async with make_client(FakeDB(users=[make_user()]), base_url=base_url) as client:
        response = await do_login(client, **headers)
    cookies = parse_set_cookie(response)
    for name in ("mockbird_token", "mockbird_csrf"):
        assert (cookies[name]["flags"].get("secure") is True) is expect_secure, name


async def test_login_cookie_csrf_matches_the_value_stored_in_the_session(monkeypatch):
    monkeypatch.setattr(routes_auth.settings, "COOKIE_SECURE", False)
    db = FakeDB(users=[make_user()])
    async with make_client(db) as client:
        response = await do_login(client)
    cookies = parse_set_cookie(response)
    assert len(db.sessions) == 1
    assert db.sessions[0].csrf_token == cookies["mockbird_csrf"]["value"]
    # O banco guarda só o hash do JWT, nunca o token em claro.
    assert db.sessions[0].token == hash_session_token(cookies["mockbird_token"]["value"])


async def test_logout_clears_both_cookies():
    user = make_user()
    token, session = make_session_for(user, "csrf-ok")
    db = FakeDB(users=[user], sessions=[session])
    async with make_client(db) as client:
        response = await client.post(
            "/api/auth/logout",
            headers={"Cookie": f"mockbird_token={token}; mockbird_csrf=csrf-ok", "X-CSRF-Token": "csrf-ok"},
        )
    assert response.status_code == 200
    cookies = parse_set_cookie(response)
    assert set(cookies) == {"mockbird_token", "mockbird_csrf"}
    for cookie in cookies.values():
        assert cookie["flags"].get("max-age") == "0"
    assert db.sessions == []


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------

MUTATING_METHODS = ["POST", "PUT", "PATCH", "DELETE"]


@pytest.fixture
def authed():
    """Usuário com sessão ativa por cookie. Devolve (client_factory, token, csrf, db)."""
    user = make_user()
    token, session = make_session_for(user, "csrf-da-sessao-a")
    other_user = make_user(email="bruno@empresa.com")
    _, other_session = make_session_for(other_user, "csrf-da-sessao-b")
    db = FakeDB(users=[user, other_user], sessions=[session, other_session])
    return db, token, "csrf-da-sessao-a", "csrf-da-sessao-b"


async def _logout(client, token, **headers):
    return await client.post("/api/auth/logout", headers={"Cookie": f"mockbird_token={token}", **headers})


async def test_cookie_auth_with_correct_csrf_is_accepted(authed):
    db, token, csrf, _ = authed
    async with make_client(db) as client:
        response = await _logout(client, token, **{"X-CSRF-Token": csrf})
    assert response.status_code == 200


@pytest.mark.parametrize("wrong", ["token-errado", "0" * 32, "csrf-da-sessao-a ", "CSRF-DA-SESSAO-A"])
async def test_cookie_auth_with_wrong_csrf_token_is_rejected(authed, wrong):
    db, token, _, _ = authed
    async with make_client(db) as client:
        response = await _logout(client, token, **{"X-CSRF-Token": wrong})
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
    assert len(db.sessions) == 2, "uma requisição rejeitada não pode ter efeito colateral"


async def test_cookie_auth_with_csrf_token_of_another_session_is_rejected(authed):
    """Token CSRF válido, mas de outra sessão/usuário."""
    db, token, _, csrf_of_other_session = authed
    async with make_client(db) as client:
        response = await _logout(client, token, **{"X-CSRF-Token": csrf_of_other_session})
    assert response.status_code == 403
    assert len(db.sessions) == 2


async def test_cookie_auth_without_csrf_header_is_rejected(authed):
    db, token, _, _ = authed
    async with make_client(db) as client:
        response = await _logout(client, token)
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


async def test_csrf_value_in_the_cookie_alone_is_not_enough(authed):
    """O cookie `mockbird_csrf` viaja sozinho em requisições cross-site; só o
    cabeçalho (que o atacante não consegue definir) prova a origem."""
    db, token, csrf, _ = authed
    async with make_client(db) as client:
        response = await client.post(
            "/api/auth/logout", headers={"Cookie": f"mockbird_token={token}; mockbird_csrf={csrf}"}
        )
    assert response.status_code == 403


async def test_csrf_check_does_not_apply_to_safe_methods(authed):
    db, token, _, _ = authed
    async with make_client(db) as client:
        response = await client.get("/api/auth/me", headers={"Cookie": f"mockbird_token={token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "ana@empresa.com"


@pytest.mark.parametrize("method", MUTATING_METHODS)
async def test_csrf_is_enforced_on_every_mutating_method(authed, method):
    """Usa a dependência `get_current_user` direto, sem depender de uma rota por método."""
    db, token, csrf, _ = authed
    app = FastAPI()

    @app.api_route("/probe", methods=[method])
    async def probe(user: User = routes_auth.Depends(routes_auth.get_current_user)):
        return {"ok": True, "email": user.email}

    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        cookie = {"Cookie": f"mockbird_token={token}"}
        assert (await client.request(method, "/probe", headers=cookie)).status_code == 403
        assert (await client.request(method, "/probe", headers={**cookie, "X-CSRF-Token": "errado"})).status_code == 403
        ok = await client.request(method, "/probe", headers={**cookie, "X-CSRF-Token": csrf})
    assert ok.status_code == 200


async def test_bearer_auth_does_not_need_csrf(authed):
    """CSRF só existe para autenticação por cookie; Bearer não é enviado pelo navegador sozinho."""
    db, token, _, _ = authed
    async with make_client(db) as client:
        response = await client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


async def test_unknown_session_is_rejected_before_csrf_is_considered(authed):
    db, _, csrf, _ = authed
    user = db.users[0]
    forged_token = create_access_token({"sub": user.id})  # JWT válido, sem sessão no banco
    async with make_client(db) as client:
        response = await _logout(client, forged_token, **{"X-CSRF-Token": csrf})
    assert response.status_code == 401
