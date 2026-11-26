from pydantic_settings import BaseSettings
from typing import List

from cryptography.fernet import Fernet

# Origens locais acrescentadas automaticamente fora de produção (frontend de
# desenvolvimento, stack de homologação). Em produção só vale `ALLOW_ORIGINS`.
LOCAL_DEV_ORIGINS = (
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8082",
    "http://127.0.0.1:8082",
)

# Valores de exemplo/padrão que nunca podem chegar à produção (comparação em
# minúsculas, por trecho).
PLACEHOLDER_SECRET_MARKERS = (
    "homolog",
    "super_secure",
    "super_segura",
    "change_me",
    "changeme",
    "sua_chave",
)
DEFAULT_DB_PASSWORD = "mockbird_homolog_secret"
MIN_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    PROJECT_NAME: str = "Mockbird v2"
    # "production" é o padrão (estrito): quem sobe sem declarar a variável recebe
    # a validação de produção, nunca uma configuração frouxa. homologation,
    # development e test precisam ser declarados de forma explícita.
    ENVIRONMENT: str = "production"
    DATABASE_URL: str = "postgresql+asyncpg://mockbird:mockbird_homolog_secret@127.0.0.1:5434/mockbird_v2"
    DATABASE_URL_SYNC: str = "postgresql://mockbird:mockbird_homolog_secret@127.0.0.1:5434/mockbird_v2"
    SECRET_KEY: str = "mockbird_v2_homolog_secret_jwt_key_super_secure_987654321"
    ENCRYPTION_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 dias
    # None = decide pelo esquema da requisição (HTTPS direto ou X-Forwarded-Proto).
    # Em produção a variável é obrigatória (ver validate_production_secrets): a
    # produção é acessada por HTTP (VPN) e por HTTPS (proxy), então o valor certo
    # é uma decisão consciente do operador e não é forçado aqui.
    COOKIE_SECURE: bool | None = None
    ALLOW_ORIGINS: str = "http://localhost:8082,http://127.0.0.1:8082,http://localhost:5173"
    ASSETS_DIR: str = "/app/assets_storage"
    # URL pública usada nos links de e-mail (reset, verificação, convite).
    # Pode ser sobrescrita por administrador em Configurações → E-mail.
    APP_BASE_URL: str = ""
    # E-mail que sempre recebe o papel de administrador do sistema. Útil em
    # instâncias que já tinham contas antes deste recurso existir.
    SYSTEM_ADMIN_EMAIL: str = ""
    MAX_ASSET_BYTES: int = 5 * 1024 * 1024

    # Timeouts e limites das chamadas de LLM. Valores generosos por padrão:
    # modelos locais (llama.cpp/Ollama) levam minutos apenas no prefill do prompt.
    AI_LLM_CONNECT_TIMEOUT: float = 10.0
    AI_LLM_READ_TIMEOUT: float = 900.0
    AI_LLM_MAX_TOKENS: int = 8192
    AI_SECTION_MAX_TOKENS: int = 2600
    AI_LLM_MAX_ATTEMPTS: int = 2
    AI_AGENT_MAX_REPAIRS: int = 1
    # Motor autônomo: habilitado por padrão, com fallback determinístico para
    # modelos que não entendem o protocolo de ferramentas.
    AI_AGENT_DYNAMIC: bool = True
    AI_AGENT_MAX_ITERATIONS: int = 10
    # Refino visual: precisa devolver a tela inteira, mas sem estourar o
    # tempo de resposta de modelos locais mais lentos.
    AI_VISION_MAX_TOKENS: int = 2400
    # Modelos de raciocínio em endpoints locais: desativa o thinking para o
    # orçamento de tokens ir para o HTML (llama.cpp/Qwen3).
    AI_DISABLE_THINKING: bool = True

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def cors_origins(self) -> List[str]:
        origins = [origin.strip() for origin in self.ALLOW_ORIGINS.split(",") if origin.strip()]
        if self.is_production:
            # Produção: só o que foi declarado em ALLOW_ORIGINS.
            return origins
        for local_origin in LOCAL_DEV_ORIGINS:
            if local_origin not in origins:
                origins.append(local_origin)
        return origins

    class Config:
        env_file = ".env"
        extra = "ignore"

    def validate_production_secrets(self):
        """Bloqueia a inicialização em produção se segredos padrão ou ausentes estiverem ativos.

        Reúne todos os problemas encontrados numa só mensagem para o operador
        corrigir de uma vez.
        """
        if not self.is_production:
            return

        problems: list[str] = []

        secret_key = self.SECRET_KEY or ""
        if len(secret_key) < MIN_SECRET_KEY_LENGTH:
            problems.append(f"SECRET_KEY deve ter no mínimo {MIN_SECRET_KEY_LENGTH} caracteres")
        if any(marker in secret_key.lower() for marker in PLACEHOLDER_SECRET_MARKERS):
            problems.append("SECRET_KEY de exemplo/padrão detectada")

        for name in ("DATABASE_URL", "DATABASE_URL_SYNC"):
            if DEFAULT_DB_PASSWORD in (getattr(self, name) or ""):
                problems.append(f"{name} usa a senha de banco de dados padrão")

        encryption_key = (self.ENCRYPTION_KEY or "").strip()
        if not encryption_key:
            problems.append("ENCRYPTION_KEY é obrigatória (chave Fernet)")
        else:
            # Sem derivação silenciosa a partir do SECRET_KEY: a chave precisa
            # ser uma chave Fernet válida (32 bytes em base64 url-safe).
            try:
                Fernet(encryption_key)
            except (ValueError, TypeError):
                problems.append(
                    "ENCRYPTION_KEY não é uma chave Fernet válida (gere com "
                    "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`)"
                )

        if self.COOKIE_SECURE is None:
            problems.append(
                "COOKIE_SECURE deve ser definido explicitamente (true/false); não é inferido em produção"
            )

        if problems:
            details = "\n".join(f" - {problem}" for problem in problems)
            raise RuntimeError(
                "ERRO CRÍTICO: configuração insegura em ambiente de produção "
                "(ENVIRONMENT=production é o padrão quando a variável não é declarada):\n" + details
            )


settings = Settings()
settings.validate_production_secrets()
