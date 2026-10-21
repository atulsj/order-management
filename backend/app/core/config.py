from functools import lru_cache

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "development"
    app_name: str = "Order Management System API"
    app_version: str = "1.0.0"
    api_prefix: str = "/api/v1"
    database_url: str = (
        "postgresql+psycopg://oms_user:local_dev_password@127.0.0.1:5432/order_management"
    )
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=200)
    database_pool_timeout: int = Field(default=30, ge=1, le=300)
    database_pool_recycle: int = Field(default=1800, ge=60)
    cors_origins: list[str] = ["http://localhost:4200", "http://localhost:8080"]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    keycloak_issuer: str = "http://localhost:8180/realms/oms"
    keycloak_audience: str = "oms-api"
    keycloak_jwks_url: str | None = None
    auth_disabled: bool = False
    payment_provider: str = "simulator"
    simulator_outcome: str = "SUCCEEDED"
    stripe_secret_key: SecretStr | None = None
    stripe_publishable_key: str | None = None
    stripe_webhook_secret: SecretStr | None = None
    payment_currency: str = "USD"
    reconciliation_deadline_hours: int = Field(default=24, ge=1, le=168)
    order_reservation_minutes: int = Field(default=30, ge=5, le=1440)
    broker_url: str = "amqp://oms:local_dev_password@localhost:5672//"
    result_backend: str = "redis://localhost:6379/1"
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = Field(default=120, ge=1, le=10000)
    payment_rate_limit_per_minute: int = Field(default=20, ge=1, le=1000)
    max_request_bytes: int = Field(default=1_048_576, ge=1024, le=20_971_520)
    log_level: str = "INFO"
    log_json: bool = True
    otel_exporter_otlp_endpoint: HttpUrl | None = None
    sentry_dsn: SecretStr | None = None
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_address: str = "oms@example.com"
    smtp_use_tls: bool = True

    @field_validator("payment_provider")
    @classmethod
    def validate_payment_provider(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"simulator", "stripe"}:
            raise ValueError("payment_provider must be simulator or stripe")
        return normalized

    @field_validator(
        "stripe_secret_key",
        "stripe_publishable_key",
        "stripe_webhook_secret",
        "otel_exporter_otlp_endpoint",
        "sentry_dsn",
        "smtp_host",
        "smtp_username",
        "smtp_password",
        mode="before",
    )
    @classmethod
    def blank_optional_value(cls, value):
        return None if value == "" else value

    @field_validator("payment_currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        normalized = value.upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("payment_currency must be a three-letter ISO currency")
        return normalized

    @property
    def jwks_url(self) -> str:
        return self.keycloak_jwks_url or f"{self.keycloak_issuer}/protocol/openid-connect/certs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
