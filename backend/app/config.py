from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    PROJECT_NAME: str = "Mockbird v2"
    ENVIRONMENT: str = "homologation"
    DATABASE_URL: str = "postgresql+asyncpg://mockbird:mockbird_homolog_secret@127.0.0.1:5434/mockbird_v2"
    DATABASE_URL_SYNC: str = "postgresql://mockbird:mockbird_homolog_secret@127.0.0.1:5434/mockbird_v2"
    SECRET_KEY: str = "mockbird_v2_homolog_secret_jwt_key_super_secure_987654321"
    ENCRYPTION_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 dias
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
    # Rate limit dos links públicos (GET /api/public/p/*). Desligado por padrão:
    # só ligue depois de confirmar que a aplicação enxerga o IP real do visitante
    # (FORWARDED_ALLOW_IPS). Atrás de um proxy mal configurado, todos os visitantes
    # dividiriam o mesmo contador e seriam bloqueados juntos.
    PUBLIC_RATE_LIMIT_ENABLED: bool = False

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
    def cors_origins(self) -> List[str]:
        origins = [origin.strip() for origin in self.ALLOW_ORIGINS.split(",") if origin.strip()]
        for local_origin in ["http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:8082", "http://127.0.0.1:8082"]:
            if local_origin not in origins:
                origins.append(local_origin)
        return origins

    class Config:
        env_file = ".env"
        extra = "ignore"

    def validate_production_secrets(self):
        """Bloqueia a inicialização em produção se segredos padrão ainda estiverem ativos."""
        if self.ENVIRONMENT == "production":
            if "homolog" in self.SECRET_KEY or "super_secure" in self.SECRET_KEY:
                raise RuntimeError("ERRO CRÍTICO: SECRET_KEY padrão detectada em ambiente de produção!")
            if "mockbird_homolog_secret" in self.DATABASE_URL:
                raise RuntimeError("ERRO CRÍTICO: Senha de banco de dados padrão detectada em ambiente de produção!")
            if not self.ENCRYPTION_KEY or len(self.ENCRYPTION_KEY.strip()) < 32:
                raise RuntimeError("ERRO CRÍTICO: ENCRYPTION_KEY obrigatória (mínimo 32 caracteres) em ambiente de produção!")


settings = Settings()
settings.validate_production_secrets()
