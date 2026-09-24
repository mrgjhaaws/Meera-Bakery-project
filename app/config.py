"""
config.py
=========
Application settings loaded from environment variables.

Local development  : values come from .env (loaded by python-dotenv)
EC2 / production   : values come from the systemd EnvironmentFile or are
                     exported from AWS Secrets Manager before process start.

The application code never calls boto3 / Secrets Manager directly.
It only reads os.environ via this Settings class.

Usage
-----
    from config import settings

    host = settings.db_host
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration for the Meera Bakery API.

    Values are read (in order of precedence):
      1. Real environment variables
      2. .env file in the working directory (local dev only)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Extra fields in .env are ignored rather than raising an error
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    db_host: str = Field(
        default="localhost",
        description="RDS endpoint DNS (production) or localhost (local dev)",
    )
    db_port: int = Field(default=3306, ge=1, le=65535)
    db_name: str = Field(default="meera_bakery")
    db_user: str = Field(default="meera_app")
    # DB_PASSWORD must be set — no default so a missing value fails fast at startup
    db_password: str = Field(
        ...,
        description="Database password. Set via environment or Secrets Manager. Never hardcode.",
    )
    db_pool_size: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Connection pool size per application instance. "
                    "Two EC2 instances × 5 = 10 total RDS connections.",
    )

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------
    app_env: str = Field(
        default="local",
        description="'local' or 'production'",
    )
    log_level: str = Field(
        default="DEBUG",
        description="Logging level: DEBUG | INFO | WARNING | ERROR",
    )
    app_port: int = Field(default=8000, ge=1, le=65535)

    # -------------------------------------------------------------------------
    # CORS
    # -------------------------------------------------------------------------
    allowed_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        description="Comma-separated list of allowed CORS origins",
    )

    # -------------------------------------------------------------------------
    # AWS SNS (order notifications) — off by default
    # -------------------------------------------------------------------------
    aws_region: str = Field(
        default="ap-south-1",
        description="AWS region for SNS (and any other AWS SDK calls).",
    )
    sns_notifications_enabled: bool = Field(
        default=False,
        description="Master switch for SNS notifications. Off by default so "
                    "local dev and the test suite never make real AWS calls. "
                    "No AWS access keys are read here — on EC2, boto3 uses "
                    "the instance's IAM role automatically.",
    )
    sns_admin_topic_arn: str = Field(
        default="",
        description="SNS topic ARN for bakery-admin alerts (e.g. low-stock). "
                    "Leave blank if you're not using topic-based notifications yet.",
    )

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------
    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, v: str) -> str:
        allowed = {"local", "production"}
        if v.lower() not in allowed:
            raise ValueError(f"app_env must be one of {allowed}, got '{v}'")
        return v.lower()

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got '{v}'")
        return upper

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, v: object) -> List[str]:
        """Accept either a list (from Python code) or a comma-separated string
        (from the .env file)."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v  # type: ignore[return-value]

    # -------------------------------------------------------------------------
    # Convenience properties
    # -------------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_local(self) -> bool:
        return self.app_env == "local"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings singleton.

    Using lru_cache means the .env file is read exactly once per process.
    In tests, call get_settings.cache_clear() before patching environment
    variables to force a fresh read.
    """
    return Settings()


# Module-level convenience alias used throughout the application
settings: Settings = get_settings()
