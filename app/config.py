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
from typing import Annotated, List

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    allowed_origins: Annotated[List[str], NoDecode] = Field(
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
    # Email OTP login (AWS SES) — off by default
    # -------------------------------------------------------------------------
    # SES, not SNS SMS, powers login: SES has a real free tier (62,000
    # emails/month sending from an EC2 instance); SNS SMS is pay-per-message
    # with no free tier, which is why order notifications (SNS) and login
    # (SES) deliberately use different AWS services.
    ses_enabled: bool = Field(
        default=False,
        description="Master switch for sending real OTP emails via AWS SES. "
                    "Off by default: the OTP is logged (and, outside "
                    "production, returned in the API response) instead of "
                    "emailed — lets you build/test the login flow with zero "
                    "AWS setup. No AWS access keys are read here — on EC2, "
                    "boto3 uses the instance's IAM role.",
    )
    ses_sender_email: str = Field(
        default="",
        description="Verified SES sender identity, e.g. no-reply@yourdomain.com. "
                    "Required when SES_ENABLED=true.",
    )
    otp_expiry_minutes: int = Field(default=10, ge=1, le=60)
    otp_max_attempts: int = Field(default=5, ge=1, le=10)
    otp_request_cooldown_seconds: int = Field(
        default=60, ge=0,
        description="Minimum time between two OTP requests for the same email.",
    )

    # -------------------------------------------------------------------------
    # JWT session tokens (issued after OTP verification)
    # -------------------------------------------------------------------------
    jwt_secret_key: str = Field(
        default="dev-only-insecure-secret-change-me",
        description="HMAC signing key for access tokens. MUST be overridden "
                    "in production — enforced by _check_production_secrets below.",
    )
    jwt_expiry_minutes: int = Field(
        default=10080,  # 7 days — a customer-facing site, so a long session is fine
        ge=5,
        description="How long an issued access token stays valid.",
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
        """Split a comma-separated .env string into a list.

        Requires the `Annotated[List[str], NoDecode]` type on the field
        above — without NoDecode, pydantic-settings tries to JSON-decode
        any string value for a List[str] field before validators ever run,
        so a plain comma-separated string (e.g. "a,b") raises a
        SettingsError instead of reaching this method at all. (Found the
        hard way: this validator was silently dead code until NoDecode was
        added — comma-separated ALLOWED_ORIGINS in .env failed outright.)
        """
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

    @model_validator(mode="after")
    def _check_production_secrets(self) -> "Settings":
        """Fail fast at startup if production is misconfigured — same
        philosophy as db_password having no default."""
        if self.is_production and self.jwt_secret_key == "dev-only-insecure-secret-change-me":
            raise ValueError(
                "JWT_SECRET_KEY must be set to a strong random value in production. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if self.is_production and self.ses_enabled and not self.ses_sender_email:
            raise ValueError("SES_SENDER_EMAIL must be set when SES_ENABLED=true.")
        return self


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
