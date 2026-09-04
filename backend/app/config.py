"""Runtime configuration, from environment variables.

Every value has a default that works for local development against eu-west-1.
In the deployed stack, Terraform sets these as Lambda environment variables.
"""
import pathlib
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- AWS ---------------------------------------------------------------
    aws_region: str = "eu-west-1"

    # eu-west-1 does not serve current Claude models on a bare model ID: an
    # on-demand call must go through a cross-Region inference profile. A bare ID
    # fails with "on-demand throughput isn't supported" (validation log V-08).
    #
    # `global.` rather than `eu.` is deliberate. Both are ACTIVE in eu-west-1, but
    # they differ in where inference actually runs:
    #   eu.      fans out across six EU Regions, and picks one per request
    #   global.  resolves to eu-west-1 only
    # A profile whose Region you do not control can route into a Region your
    # organisation denies by SCP, which fails intermittently and reports a Region
    # you never asked for. Pinning to a single-Region profile makes the request's
    # Region predictable — see validation log V-09 and V-11, and ADR decision 10.
    bedrock_model_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

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

    # When the model cannot be invoked — an organisation SCP, absent model access,
    # or a throttle — substitute a bulletin-grounded canned answer for stage 2 so
    # stages 1 and 3 still run live against the real guardrail. The response is
    # labelled as a fallback and reports model_invoked=false, so nothing claims a
    # model ran. Set to false to make a model failure a hard error instead.
    answer_fallback: bool = True

    # --- Replay_Mode -------------------------------------------------------
    # Serve every stage from fixtures recorded against live AWS. Under replay no
    # boto3 client is constructed, so the pipeline completes with no credentials
    # and no network — which is the point: a presenter whose account fails live
    # can finish the session. Every replayed stage carries its capture date and
    # Region, so a recorded result is never shown as though it were live.
    replay_mode: bool = False
    replay_dir: str = ""

    # Which tier's fixtures to prefer where a prompt is recorded under both, and
    # the tier the application reports. Terraform sets GUARDRAIL_TIER on the
    # Lambda and in the `local_env_file` output, both from its own
    # `guardrail_tier` variable — it did not until V-34, so a STANDARD stack
    # described itself as CLASSIC and preferred the wrong tier's fixtures.
    guardrail_tier: str = "CLASSIC"

    @property
    def replay_path(self) -> pathlib.Path:
        if self.replay_dir:
            return pathlib.Path(self.replay_dir)
        return pathlib.Path(__file__).resolve().parent / "fixtures" / "replay"

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
