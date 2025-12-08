from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, SecretStr, AliasChoices, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
print("ROOT", ROOT)


def _env_files_for(active_env: str) -> list[str]:
    """
    Layered .env resolution, lower precedence first.
    Final precedence across the whole app:
      process env > .env.{env}.local > .env.{env} > .env (this file chain)
    """
    candidates = [
        ROOT / ".env",
        ROOT / ".env.local",
        ROOT / f".env.{active_env}",
        ROOT / f".env.{active_env}.local",
    ]
    return [str(p) for p in candidates if p.exists()]


# ── Base with consistent behavior ──────────────────────────────────────────────
class _Base(BaseSettings):
    """
    Common behavior for all settings groups:
      - case-insensitive env vars
      - UTF-8 dotenv files
      - ignore unknown keys
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=False,
        env_file_encoding="utf-8",
    )


# ── Group: APP_* ───────────────────────────────────────────────────────────────
class AppSettings(_Base):
    model_config = SettingsConfigDict(
        env_prefix="APP_",
        extra="ignore",
        case_sensitive=False,
        env_file_encoding="utf-8",
    )

    # Accept ENV from multiple names (CI/CD or PaaS differences)
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("APP_ENV", "ENVIRONMENT", "APP_ENVIRONMENT"),
    )
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    log_level: str = "INFO"
    name: str = "data360-chat-api"
    version: str = "0.1.0"

    # LLM
    openai_model: str = "gpt-4.1-mini"
    llm_provider: str = "openai"

    # Extract from DB after seeding from db/configs/llm.yaml
    conversation_llm_prompt_id: str
    conversation_llm_config_id: str
    chat_llm_prompt_id: str
    chat_llm_config_id: str

    # Logging
    log_dir: str = "logs"
    log_config: str = "logging.yaml"


# ── Group: DB_* ────────────────────────────────────────────────────────────────
class DBSettings(_Base):
    model_config = SettingsConfigDict(
        env_prefix="DB_",
        extra="ignore",
        case_sensitive=False,
        env_file_encoding="utf-8",
    )

    # Either provide DB_URL, or fill individual parts (driver/user/password/etc.)
    url: Optional[str] = None

    driver: str = "postgresql+psycopg"
    user: str = Field(
        default="postgres", validation_alias=AliasChoices("DB_USER", "POSTGRES_USER")
    )
    password: SecretStr = Field(
        default=SecretStr("postgres"),
        validation_alias=AliasChoices("DB_PASSWORD", "POSTGRES_PASSWORD"),
    )
    host: str = Field(
        default="db", validation_alias=AliasChoices("DB_HOST", "POSTGRES_HOST")
    )
    port: int = Field(
        default=5432, validation_alias=AliasChoices("DB_PORT", "POSTGRES_PORT")
    )
    name: str = Field(
        default="data360_chat", validation_alias=AliasChoices("DB_NAME", "POSTGRES_DB")
    )

    # Allow secret-from-file pattern (e.g., DB_PASSWORD_FILE=/run/secrets/db_password)
    def _maybe_from_file(self, var: str) -> Optional[str]:
        path = os.getenv(f"{var}_FILE")
        if not path:
            return None
        p = Path(path)
        return p.read_text(encoding="utf-8").strip() if p.exists() else None

    def model_post_init(self, __context) -> None:  # pydantic v2 hook
        # If DB_URL is set via *_FILE, read it
        url_from_file = self._maybe_from_file("DB_URL")
        if url_from_file and not self.url:
            self.url = url_from_file

        # If DB_PASSWORD is provided via file, apply it
        pwd_from_file = self._maybe_from_file("DB_PASSWORD")
        if pwd_from_file:
            self.password = SecretStr(pwd_from_file)

    @computed_field  # type: ignore[misc]
    @property
    def dsn(self) -> str:
        """Final SQLAlchemy URL used by the app and Alembic."""
        if self.url:
            return self.url
        pwd = self.password.get_secret_value()
        return f"{self.driver}://{self.user}:{pwd}@{self.host}:{self.port}/{self.name}"


# ── Group: SECRETS_* ───────────────────────────────────────────────────────────
class SecretsSettings(_Base):
    model_config = SettingsConfigDict(
        env_prefix="SECRETS_",
        extra="ignore",
        case_sensitive=False,
        env_file_encoding="utf-8",
    )

    # OpenAI
    openai_api_key: SecretStr | None = None

    # Anthropic
    anthropic_api_key: SecretStr | None = None

    # HF
    hf_token: SecretStr | None = None

    def model_post_init(self, __context) -> None:
        # Ensure that at least one of the API keys is set
        if self.openai_api_key is None and self.anthropic_api_key is None:
            raise ValueError("At least one of the API keys must be set")


# ── Root Settings (compose groups) ─────────────────────────────────────────────
class Settings(_Base):
    """
    One object your app imports: `from app.core.settings import settings`
    """

    app: AppSettings
    db: DBSettings
    secrets: SecretsSettings

    @computed_field  # type: ignore[misc]
    @property
    def llm_key(self) -> str:
        if self.app.llm_provider == "openai":
            assert self.secrets.openai_api_key, "OpenAI API key is not set"
            return f"{self.secrets.openai_api_key.get_secret_value()}"
        elif self.app.llm_provider == "anthropic":
            assert self.secrets.anthropic_api_key, "Anthropic API key is not set"
            return f"{self.secrets.anthropic_api_key.get_secret_value()}"
        else:
            raise ValueError(f"Unsupported provider: {self.app.llm_provider}")


@lru_cache
def get_settings() -> Settings:
    # Choose environment before loading .env files
    active_env = (
        os.getenv("ENVIRONMENT")
        or os.getenv("APP_ENV")
        or os.getenv("APP_ENVIRONMENT")
        or "development"
    )
    env_files = _env_files_for(active_env)
    print("env_files", env_files)

    # Build each group from the SAME layered env files;
    # process env always overrides env_file
    app = AppSettings(_env_file=env_files)
    db = DBSettings(_env_file=env_files)
    secrets = SecretsSettings(_env_file=env_files)

    return Settings(app=app, db=db, secrets=secrets)


# Convenience singleton
settings = get_settings()
