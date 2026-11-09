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
    ALLOW_ORIGINS: str = "http://localhost:8082,http://127.0.0.1:8082,http://localhost:5173"

    @property
    def cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.ALLOW_ORIGINS.split(",") if origin.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

