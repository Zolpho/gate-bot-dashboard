from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Gate Bot Dashboard"
    app_env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    database_url: str = "sqlite:////data/gate_bots.db"
    frontend_dir: Path = Field(default=Path(__file__).resolve().parent.parent / "frontend")

    gate_base_url: str = "https://api.gateio.ws/api/v4"
    gate_accounts_file: Path = Path("/run/secrets/gate_accounts.json")
    dashboard_users_file: Path = Path("/run/secrets/dashboard_users.json")
    dashboard_users_backup_dir: Path = Path("/data/dashboard-user-backups")
    dashboard_users_backup_keep: int = 20

    # Legacy single-account variables remain supported for a one-account install.
    # When GATE_ACCOUNTS_FILE exists and contains accounts, it takes precedence.
    gate_api_key: str = ""
    gate_api_secret: str = ""
    gate_account_id: str = "default"
    gate_account_name: str = "Default account"
    gate_account_type: str = "subaccount"
    gate_uid: str = ""

    gate_language: str = "en-US"
    gate_request_timeout_seconds: float = 20.0
    gate_bot_page_size: int = 50
    gate_details_concurrency: int = 4
    gate_account_concurrency: int = 4
    balance_cache_seconds: int = 30
    balance_dust_usdt: float = 0.01
    deposit_catalog_cache_seconds: int = 900
    deposit_address_cache_seconds: int = 300
    deposit_favorites: str = "USDT,EQTY,BTC,ETH"
    deposit_history_sync_enabled: bool = True
    deposit_initial_lookback_days: int = 30
    deposit_sync_overlap_seconds: int = 3600
    deposit_reconcile_hours: int = 24
    deposit_page_limit: int = 100
    deposit_max_records_per_sync: int = 500

    poll_seconds: int = 60
    stale_after_minutes: int = 5
    missing_bot_grace_syncs: int = 2
    snapshot_retention_days: int = 365
    purge_demo_data_on_live: bool = True

    demo_mode: bool = False
    demo_seed: int = 42

    allow_bot_stop: bool = False
    bot_stop_confirmation_text: str = "STOP"

    # Optional legacy super-admin credentials. They no longer protect public GET routes.
    dashboard_username: str = ""
    dashboard_password: str = ""

    # Comma-separated browser origins allowed to call the API.
    cors_origins: str = "https://zolpho.github.io"

    default_drawdown_alert_pct: float = 12.0
    default_loss_alert_usdt: float = 100.0
    default_liquidation_distance_pct: float = 10.0
    alert_cooldown_seconds: int = 3600

    @field_validator("gate_base_url")
    @classmethod
    def normalize_gate_base_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("gate_bot_page_size")
    @classmethod
    def validate_page_size(cls, value: int) -> int:
        return max(1, min(value, 50))

    @field_validator("gate_details_concurrency", "gate_account_concurrency")
    @classmethod
    def validate_concurrency(cls, value: int) -> int:
        return max(1, min(value, 20))

    @field_validator("dashboard_users_backup_keep")
    @classmethod
    def validate_dashboard_users_backup_keep(cls, value: int) -> int:
        return max(1, min(value, 100))

    @field_validator("balance_cache_seconds")
    @classmethod
    def validate_balance_cache_seconds(cls, value: int) -> int:
        return max(0, min(value, 300))

    @field_validator("balance_dust_usdt")
    @classmethod
    def validate_balance_dust_usdt(cls, value: float) -> float:
        return max(0.0, min(value, 100.0))

    @field_validator(
        "deposit_catalog_cache_seconds",
        "deposit_address_cache_seconds",
    )
    @classmethod
    def validate_deposit_cache_seconds(cls, value: int) -> int:
        return max(0, min(value, 3600))

    @field_validator("deposit_initial_lookback_days")
    @classmethod
    def validate_deposit_lookback_days(cls, value: int) -> int:
        return max(1, min(value, 30))

    @field_validator("deposit_sync_overlap_seconds")
    @classmethod
    def validate_deposit_overlap_seconds(cls, value: int) -> int:
        return max(0, min(value, 86400))

    @field_validator("deposit_reconcile_hours")
    @classmethod
    def validate_deposit_reconcile_hours(cls, value: int) -> int:
        return max(1, min(value, 24 * 30))

    @field_validator("deposit_page_limit")
    @classmethod
    def validate_deposit_page_limit(cls, value: int) -> int:
        return max(1, min(value, 100))

    @field_validator("deposit_max_records_per_sync")
    @classmethod
    def validate_deposit_history_limits(cls, value: int) -> int:
        return max(1, min(value, 500))

    @field_validator("poll_seconds")
    @classmethod
    def validate_poll_seconds(cls, value: int) -> int:
        return max(15, value)

    @property
    def legacy_gate_configured(self) -> bool:
        return bool(self.gate_api_key and self.gate_api_secret)

    @property
    def legacy_admin_enabled(self) -> bool:
        return bool(self.dashboard_username and self.dashboard_password)

    @property
    def auth_enabled(self) -> bool:
        return self.legacy_admin_enabled or self.dashboard_users_file.exists()

    @property
    def deposit_favorite_list(self) -> list[str]:
        return [
            item.strip().upper()
            for item in self.deposit_favorites.split(",")
            if item.strip()
        ]

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
