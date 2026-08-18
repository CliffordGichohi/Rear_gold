from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Gold Market Intelligence Engine"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    api_cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    database_url: str = "postgresql+asyncpg://gold_intel:gold_intel_dev@localhost:5432/gold_intel"
    redis_url: str = "redis://localhost:6379/0"
    raw_store_path: Path = Path("data/raw")
    blind_replay_artifact_path: Path = Path(
        "../research_artifacts/gold_blind_discretionary_replay_v1"
    )
    blind_replay_v2_artifact_path: Path = Path(
        "../research_artifacts/gold_blind_synchronized_setup_replay_v2"
    )
    blind_replay_v3_artifact_path: Path = Path("../research_artifacts/gold_annotated_replay_v3")
    blind_replay_v3_ledger_path: Path = Path(
        "../research_artifacts/gold_annotated_replay_v3/ledgers/practice_event_ledger_v3.jsonl"
    )
    codex_operator_replay_artifact_path: Path = Path(
        "../research_artifacts/gold_blind_codex_operator_replay_v1"
    )
    codex_operator_replay_visible_ledger_path: Path = Path(
        "../research_artifacts/gold_blind_codex_operator_replay_v1/ledgers/codex_blind_visible_ledger.jsonl"
    )
    codex_operator_replay_outcome_ledger_path: Path = Path(
        "../research_artifacts/gold_blind_codex_operator_replay_v1/outcome_vault/codex_blind_outcome_ledger.jsonl"
    )
    matched_human_replay_artifact_path: Path = Path(
        "../research_artifacts/gold_matched_human_replay_v1"
    )
    matched_human_replay_visible_ledger_path: Path = Path(
        "../research_artifacts/gold_matched_human_replay_v1/ledgers/matched_human_visible_ledger.jsonl"
    )
    matched_human_replay_outcome_ledger_path: Path = Path(
        "../research_artifacts/gold_matched_human_replay_v1/outcome_vault/matched_human_outcome_ledger.jsonl"
    )

    ctrader_client_id: SecretStr | None = None
    ctrader_client_secret: SecretStr | None = None
    ctrader_environment: str = "demo"
    ctrader_scope: str = "accounts"
    ctrader_redirect_uri: str = "http://localhost:8000/api/v1/providers/ctrader/oauth/callback"
    ctrader_account_id: str | None = None
    provider_token_encryption_key: SecretStr | None = None
    oauth_state_ttl_seconds: int = Field(default=300, ge=60, le=900)
    fred_api_key: SecretStr | None = None
    bls_registration_key: SecretStr | None = None
    bea_api_key: SecretStr | None = None
    trading_economics_api_key: SecretStr | None = None
    cme_fedwatch_client_id: SecretStr | None = None
    cme_fedwatch_client_secret: SecretStr | None = None

    @property
    def ctrader_credentials_configured(self) -> bool:
        return bool(
            self.ctrader_client_id
            and self.ctrader_client_id.get_secret_value()
            and self.ctrader_client_secret
            and self.ctrader_client_secret.get_secret_value()
        )

    @property
    def provider_token_key_material(self) -> str | None:
        if (
            self.provider_token_encryption_key
            and self.provider_token_encryption_key.get_secret_value()
        ):
            return self.provider_token_encryption_key.get_secret_value()
        if self.app_env.lower() != "production" and self.ctrader_client_secret:
            return self.ctrader_client_secret.get_secret_value()
        return None

    @property
    def fred_api_key_configured(self) -> bool:
        return bool(self.fred_api_key and self.fred_api_key.get_secret_value())

    @property
    def trading_economics_api_key_configured(self) -> bool:
        return bool(
            self.trading_economics_api_key and self.trading_economics_api_key.get_secret_value()
        )

    @property
    def cme_fedwatch_credentials_configured(self) -> bool:
        return bool(
            self.cme_fedwatch_client_id
            and self.cme_fedwatch_client_id.get_secret_value()
            and self.cme_fedwatch_client_secret
            and self.cme_fedwatch_client_secret.get_secret_value()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
