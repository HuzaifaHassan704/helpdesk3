from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_SECRET = "dev-only-insecure-key-change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Helpdesk API"
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    DEBUG: bool = False
    ENABLE_DOCS: bool = True  # set false to hide /docs, /redoc and /openapi.json

    # --- database ---
    DATABASE_URL: str = "sqlite+aiosqlite:///./helpdesk.db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    # Dev-only shortcut. Real deployments use `alembic upgrade head`.
    AUTO_CREATE_TABLES: bool = False

    # --- auth ---
    SECRET_KEY: str = _DEFAULT_SECRET
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    BCRYPT_ROUNDS: int = 12

    # --- logging ---
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True  # false = human-friendly console output for local dev

    # --- HTTP hardening ---
    # Comma-separated. Empty = CORS disabled (same-origin only).
    CORS_ORIGINS: str = ""
    # Comma-separated Host header allow-list. "*" = allow any.
    ALLOWED_HOSTS: str = "*"

    # --- rate limiting (slowapi / limits syntax: "5/minute", "10/hour") ---
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_STORAGE_URI: str = "memory://"  # use redis://host:6379/0 with multiple workers
    RATE_LIMIT_LOGIN: str = "5/minute"
    RATE_LIMIT_REGISTER: str = "10/hour"
    RATE_LIMIT_CREATE_TICKET: str = "30/minute"

    # --- login throttling (per email + client IP; see LoginAttempt) ---
    LOGIN_MAX_ATTEMPTS: int = 5
    LOCKOUT_MINUTES: int = 15

    # --- email notifications (empty SMTP_HOST = log only) ---
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "helpdesk@localhost"
    SMTP_STARTTLS: bool = True

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [h.strip() for h in self.ALLOWED_HOSTS.split(",") if h.strip()] or ["*"]

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            if self.SECRET_KEY == _DEFAULT_SECRET or len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY must be set to a random value of 32+ characters in production")
            if "*" in self.cors_origins_list:
                raise ValueError("CORS_ORIGINS must list explicit origins in production (no wildcard)")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
