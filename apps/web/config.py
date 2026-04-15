from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLAIMSMAN_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8811
    log_level: str = "info"
    env: str = "dev"

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 55432
    postgres_db: str = "claimsman"
    postgres_user: str = "claimsman"
    postgres_password: str = "claimsman"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_default_model: str = "gemma4:31b"

    storage_root: Path = Path.home() / ".claimsman" / "uploads"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
