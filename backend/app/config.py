"""Runtime configuration, from environment variables.

Every value has a default that works for local development against eu-west-1.
In the deployed stack, Terraform sets these as Lambda environment variables.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- AWS ---------------------------------------------------------------
    aws_region: str = "eu-west-1"

    # eu-west-1 does not serve current Claude models on a bare model ID: an
    # on-demand call must go through a cross-Region inference profile, hence the
    # `eu.` prefix. A bare ID fails with "on-demand throughput isn't supported".
    bedrock_model_id: str = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"

    # --- Guardrail ---------------------------------------------------------
    guardrail_id: str = ""
    guardrail_version: str = "DRAFT"
    guardrail_enabled: bool = True

    # --- HTTP --------------------------------------------------------------
    # Comma-separated list, or "*" for local development.
    cors_allow_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    # Guard against a runaway prompt being forwarded to Bedrock.
    max_input_chars: int = 2000

    @property
    def cors_origins(self) -> list[str]:
        raw = self.cors_allow_origins.strip()
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def guardrail_active(self) -> bool:
        return bool(self.guardrail_enabled and self.guardrail_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
