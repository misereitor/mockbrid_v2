"""Testes unitários (sem stack) do endurecimento de `app.config`.

Cobrem `validate_production_secrets` (uma regra por teste), o CORS sem localhost
em produção, a origem do WebSocket (que reutiliza a lista de CORS) e o
`/api/health` anônimo sem o campo `environment`.
"""

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.config import Settings

# Chave de 52 caracteres, sem nenhum dos marcadores de exemplo.
STRONG_SECRET_KEY = "k3Y-a1B2c3D4e5F6g7H8-a1B2c3D4e5F6g7H8-a1B2c3D4e5F6"
STRONG_DB_URL = "postgresql+asyncpg://mockbird:S3nhaDeProducaoForte@db_prod:5432/mockbird_v2"
STRONG_DB_URL_SYNC = "postgresql://mockbird:S3nhaDeProducaoForte@db_prod:5432/mockbird_v2"


def make_settings(**overrides) -> Settings:
    """Settings de produção válidas; `overrides` quebra uma regra por vez.

    `_env_file=None` e valores explícitos para todos os campos validados isolam
    o teste do `.env` e das variáveis do processo.
    """
    values = dict(
        ENVIRONMENT="production",
        SECRET_KEY=STRONG_SECRET_KEY,
        ENCRYPTION_KEY=Fernet.generate_key().decode(),
        DATABASE_URL=STRONG_DB_URL,
        DATABASE_URL_SYNC=STRONG_DB_URL_SYNC,
        COOKIE_SECURE=False,
        ALLOW_ORIGINS="https://app.empresa.com",
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def problems_of(settings: Settings) -> str:
    with pytest.raises(RuntimeError) as exc:
        settings.validate_production_secrets()
    return str(exc.value)


# ---------------------------------------------------------------------------
# Ambiente padrão
# ---------------------------------------------------------------------------


def test_environment_defaults_to_production(monkeypatch):
    """Esquecer a variável não pode ligar o modo frouxo."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert Settings(_env_file=None).ENVIRONMENT == "production"


def test_defaults_without_declared_environment_fail_validation(monkeypatch):
    """Sem declarar o ambiente, os segredos de exemplo caem na validação de produção."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with pytest.raises(RuntimeError):
        Settings(_env_file=None).validate_production_secrets()


def test_valid_production_settings_pass():
    make_settings().validate_production_secrets()


@pytest.mark.parametrize("environment", ["homologation", "development", "test"])
def test_non_production_environments_skip_validation(environment):
    """Fora de produção os valores de exemplo continuam funcionando."""
    settings = Settings(_env_file=None, ENVIRONMENT=environment)
    assert settings.COOKIE_SECURE is None
    assert settings.ENCRYPTION_KEY == ""
    settings.validate_production_secrets()


# ---------------------------------------------------------------------------
# SECRET_KEY
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("length", [0, 1, 31])
def test_secret_key_shorter_than_32_chars_is_rejected(length):
    message = problems_of(make_settings(SECRET_KEY="x" * length))
    assert "SECRET_KEY deve ter no mínimo 32 caracteres" in message


def test_secret_key_with_exactly_32_chars_is_accepted():
    make_settings(SECRET_KEY="aZ9" * 10 + "qw").validate_production_secrets()


@pytest.mark.parametrize(
    "marker",
    ["homolog", "super_secure", "super_segura", "CHANGE_ME", "changeme", "sua_chave"],
)
def test_secret_key_with_example_marker_is_rejected(marker):
    """Os valores de exemplo (compose, .env.example) não podem ir para produção,
    mesmo com 32+ caracteres e independentemente de maiúsculas."""
    secret_key = f"Zq8-{marker}-Zq8-Zq8-Zq8-Zq8-Zq8-Zq8"
    assert len(secret_key) >= 32
    assert "SECRET_KEY de exemplo/padrão detectada" in problems_of(make_settings(SECRET_KEY=secret_key))


def test_default_secret_key_of_the_repo_is_rejected():
    default_secret = Settings.model_fields["SECRET_KEY"].default
    assert "SECRET_KEY de exemplo/padrão detectada" in problems_of(make_settings(SECRET_KEY=default_secret))


# ---------------------------------------------------------------------------
# DATABASE_URL e DATABASE_URL_SYNC
# ---------------------------------------------------------------------------


def test_default_database_password_is_rejected_in_async_url():
    default_url = Settings.model_fields["DATABASE_URL"].default
    message = problems_of(make_settings(DATABASE_URL=default_url))
    assert "DATABASE_URL usa a senha de banco de dados padrão" in message
    assert "DATABASE_URL_SYNC" not in message


def test_default_database_password_is_rejected_in_sync_url():
    """O Alembic usa a URL síncrona: ela também precisa ser checada."""
    default_url = Settings.model_fields["DATABASE_URL_SYNC"].default
    message = problems_of(make_settings(DATABASE_URL_SYNC=default_url))
    assert "DATABASE_URL_SYNC usa a senha de banco de dados padrão" in message
    assert "DATABASE_URL usa" not in message


# ---------------------------------------------------------------------------
# ENCRYPTION_KEY
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["", "   "])
def test_missing_encryption_key_is_rejected(value):
    """Sem derivação silenciosa a partir do SECRET_KEY, mesmo com SECRET_KEY forte."""
    assert "ENCRYPTION_KEY é obrigatória" in problems_of(make_settings(ENCRYPTION_KEY=value))


@pytest.mark.parametrize(
    "value",
    [
        "x" * 31,
        "a" * 40,  # 32+ caracteres, mas fora do formato Fernet: antes caía na derivação
        "x" * 44,  # 44 caracteres, mas não decodifica para 32 bytes
        "mockbird_homolog_32_byte_secret_key_sample=",  # exemplo do .env.example
        STRONG_SECRET_KEY,  # reaproveitar o SECRET_KEY não é uma chave Fernet
    ],
)
def test_encryption_key_must_be_a_valid_fernet_key(value):
    message = problems_of(make_settings(ENCRYPTION_KEY=value))
    assert "ENCRYPTION_KEY não é uma chave Fernet válida" in message
    # A mensagem orienta o operador, mas não ecoa o segredo informado.
    assert value not in message


def test_valid_fernet_key_is_accepted_even_with_surrounding_whitespace():
    make_settings(ENCRYPTION_KEY=f"  {Fernet.generate_key().decode()}\n").validate_production_secrets()


# ---------------------------------------------------------------------------
# COOKIE_SECURE
# ---------------------------------------------------------------------------


def test_cookie_secure_must_be_declared_in_production():
    assert "COOKIE_SECURE deve ser definido explicitamente" in problems_of(make_settings(COOKIE_SECURE=None))


@pytest.mark.parametrize("value", [True, False])
def test_cookie_secure_is_not_forced_to_true(value):
    """A produção é acessada por HTTP (VPN) e HTTPS (proxy): `false` é válido."""
    make_settings(COOKIE_SECURE=value).validate_production_secrets()


# ---------------------------------------------------------------------------
# Mensagem agregada
# ---------------------------------------------------------------------------


def test_all_problems_are_reported_together_without_leaking_secrets():
    settings = make_settings(
        SECRET_KEY="curta-homolog",
        ENCRYPTION_KEY="",
        DATABASE_URL=Settings.model_fields["DATABASE_URL"].default,
        DATABASE_URL_SYNC=Settings.model_fields["DATABASE_URL_SYNC"].default,
        COOKIE_SECURE=None,
    )
    message = problems_of(settings)
    for expected in (
        "SECRET_KEY deve ter no mínimo 32 caracteres",
        "SECRET_KEY de exemplo/padrão detectada",
        "DATABASE_URL usa a senha de banco de dados padrão",
        "DATABASE_URL_SYNC usa a senha de banco de dados padrão",
        "ENCRYPTION_KEY é obrigatória",
        "COOKIE_SECURE deve ser definido explicitamente",
    ):
        assert expected in message
    assert "curta-homolog" not in message
    assert "mockbird_homolog_secret" not in message


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

LOCAL_ORIGINS = {
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8082",
    "http://127.0.0.1:8082",
}


def test_production_cors_uses_only_allow_origins():
    origins = make_settings(ALLOW_ORIGINS="https://app.empresa.com").cors_origins
    assert origins == ["https://app.empresa.com"]
    assert not LOCAL_ORIGINS & set(origins)


def test_production_cors_does_not_require_https_and_ignores_blanks():
    """O .env.prod lista origens http:// de propósito (VPN)."""
    settings = make_settings(ALLOW_ORIGINS=" http://10.8.0.7:8083 , ,https://app.empresa.com,")
    assert settings.cors_origins == ["http://10.8.0.7:8083", "https://app.empresa.com"]


def test_production_cors_empty_allow_origins_means_no_origin():
    assert make_settings(ALLOW_ORIGINS="").cors_origins == []


def test_production_cors_does_not_add_localhost_even_when_allow_origins_has_localhost_5173():
    """O que o operador declara é respeitado; só os acréscimos automáticos somem."""
    origins = make_settings(ALLOW_ORIGINS="http://localhost:5173").cors_origins
    assert origins == ["http://localhost:5173"]


@pytest.mark.parametrize("environment", ["development", "homologation", "test"])
def test_non_production_cors_adds_local_origins(environment):
    settings = Settings(_env_file=None, ENVIRONMENT=environment, ALLOW_ORIGINS="https://app.empresa.com")
    origins = settings.cors_origins
    assert origins[0] == "https://app.empresa.com"
    assert LOCAL_ORIGINS <= set(origins)


def test_non_production_cors_has_no_duplicates():
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="homologation",
        ALLOW_ORIGINS="http://localhost:8082,http://127.0.0.1:8082",
    )
    assert len(settings.cors_origins) == len(set(settings.cors_origins))


# ---------------------------------------------------------------------------
# Origem do WebSocket (reutiliza settings.cors_origins)
# ---------------------------------------------------------------------------


def _websocket(origin):
    headers = {} if origin is None else {"origin": origin}
    return SimpleNamespace(headers=headers)


def test_websocket_origin_rejects_localhost_in_production(monkeypatch):
    from app import routes_ws

    monkeypatch.setattr(routes_ws, "settings", make_settings(ALLOW_ORIGINS="https://app.empresa.com"))
    assert routes_ws._origin_allowed(_websocket("https://app.empresa.com")) is True
    assert routes_ws._origin_allowed(_websocket("https://app.empresa.com/")) is True
    assert routes_ws._origin_allowed(_websocket("http://localhost:8082")) is False
    assert routes_ws._origin_allowed(_websocket("http://127.0.0.1:8082")) is False
    assert routes_ws._origin_allowed(_websocket("https://evil.example")) is False


def test_websocket_origin_accepts_local_stack_outside_production(monkeypatch):
    from app import routes_ws

    homolog = Settings(_env_file=None, ENVIRONMENT="homologation", ALLOW_ORIGINS="http://10.8.0.7:8082")
    monkeypatch.setattr(routes_ws, "settings", homolog)
    assert routes_ws._origin_allowed(_websocket("http://localhost:8082")) is True
    assert routes_ws._origin_allowed(_websocket("https://evil.example")) is False


def test_websocket_without_origin_header_is_still_allowed(monkeypatch):
    """Clientes nativos (MCP/CLI) não enviam Origin; a autenticação segue valendo."""
    from app import routes_ws

    monkeypatch.setattr(routes_ws, "settings", make_settings())
    assert routes_ws._origin_allowed(_websocket(None)) is True


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, fail):
        self._fail = fail

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *_args, **_kwargs):
        if self._fail:
            raise ConnectionRefusedError("banco fora do ar: postgres://user:senha@host/db")


@pytest.mark.parametrize("db_fails", [False, True])
async def test_health_does_not_expose_environment(monkeypatch, db_fails):
    from app import database
    from app.main import health_check

    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSession(db_fails))
    payload = await health_check()

    assert "environment" not in payload
    assert payload["database"] == ("unavailable" if db_fails else "connected")
    assert payload["status"] == ("degraded" if db_fails else "healthy")
    # Nem o detalhe da exceção (que pode conter credenciais) vai para o endpoint anônimo.
    assert "senha" not in str(payload)
