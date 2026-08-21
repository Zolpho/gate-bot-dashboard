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
    gate_bot_control_file: Path = Path("/run/secrets/gate_bot_control.json")

    # Spot Trading is deliberately isolated from Monitor,
    # Bot Control and Treasury credentials.
    gate_trading_file: Path = Path("/run/secrets/gate_trading.json")

    # Merely provisioning a Spot read-write credential must
    # never enable live order placement.
    trading_limit_orders_enabled: bool = False
    trading_limit_order_confirmation_text: str = "LIMIT ORDER"

    # Persistent Spot order submission rate limits.
    trading_rate_limit_enabled: bool = True
    trading_limit_order_user_limit: int = 5
    trading_limit_order_user_window_seconds: int = 600
    trading_limit_order_account_limit: int = 10
    trading_limit_order_account_window_seconds: int = 600

    # Absolute Gate request expiry is calculated immediately
    # before the future POST. The POST is never retried.
    trading_order_exptime_ms: int = 5000

    # Treasury is deliberately isolated from Monitor and Bot Control.
    # Treasury uses its own read-only credential mount.
    gate_treasury_file: Path = Path("/run/secrets/gate_treasury.json")
    treasury_main_account: str = "zolnode"

    # Live internal Treasury transfers are independently armed.
    # External withdrawals remain a separate future phase.
    treasury_transfers_live_armed: bool = False
    treasury_transfers_live_accounts: str = ""
    treasury_transfer_confirmation_text: str = "LIVE TRANSFER"

    # Dashboard user-to-user transfers move real available
    # Gate spot balances between explicitly assigned accounts.
    # Keep independently disabled until live execution is ready.
    treasury_user_transfers_enabled: bool = False
    treasury_user_transfer_confirmation_text: str = (
        "USER TRANSFER"
    )

    # External withdrawals have their own independent
    # live arm. Enabling internal Treasury transfers must
    # never enable an external withdrawal.
    treasury_withdrawals_live_armed: bool = False
    treasury_withdrawals_live_accounts: str = ""

    # Must mirror Gate:
    # API Withdrawal Settings.
    #
    # verification_free:
    #   saved address must have Gate verified=1.
    #
    # address_book:
    #   exact Gate Address Book membership is enough.
    #
    # Default remains fail-closed.
    treasury_withdrawal_address_policy: str = (
        "verification_free"
    )

    # Persistent Treasury operation rate limiting.
    treasury_rate_limit_enabled: bool = True

    treasury_execute_user_limit: int = 3
    treasury_execute_user_window_seconds: int = 600

    treasury_execute_account_limit: int = 5
    treasury_execute_account_window_seconds: int = 600

    # Account-scoped Gate transfers between registered
    # dashboard accounts. These are financially sensitive
    # mutations and have their own rate limits.
    treasury_user_transfer_user_limit: int = 10
    treasury_user_transfer_user_window_seconds: int = 600

    treasury_user_transfer_account_limit: int = 20
    treasury_user_transfer_account_window_seconds: int = 600

    treasury_reconcile_user_limit: int = 20
    treasury_reconcile_user_window_seconds: int = 600

    treasury_lock_release_user_limit: int = 2
    treasury_lock_release_user_window_seconds: int = 1800

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
    bot_stop_simulation: bool = False
    bot_stop_confirmation_text: str = "STOP"
    bot_stop_duplicate_cooldown_seconds: int = 300

    allow_bot_create: bool = False
    bot_create_simulation: bool = False
    bot_create_confirmation_text: str = "CREATE"
    bot_create_duplicate_cooldown_seconds: int = 600

    # Live Bot Control requires an additional explicit arm.
    #
    # Accounts may be a comma-separated list or "*".
    # There is deliberately NO permanent market allowlist
    # and NO static investment cap. Spot Grid investment
    # is bounded dynamically by the available balance of
    # the market's quote currency.
    bot_control_live_armed: bool = False
    bot_control_live_accounts: str = ""

    bot_control_live_create_confirmation_text: str = "LIVE CREATE"
    bot_control_live_stop_confirmation_text: str = "LIVE STOP"

    # Persistent Bot Control rate limiting.
    bot_control_rate_limit_enabled: bool = True

    bot_control_create_user_limit: int = 5
    bot_control_create_user_window_seconds: int = 600

    bot_control_stop_user_limit: int = 5
    bot_control_stop_user_window_seconds: int = 600

    bot_control_reconcile_user_limit: int = 20
    bot_control_reconcile_user_window_seconds: int = 600

    bot_control_lock_release_user_limit: int = 3
    bot_control_lock_release_user_window_seconds: int = 1800

    bot_control_account_mutation_limit: int = 10
    bot_control_account_mutation_window_seconds: int = 600

    # Recover Bot Control operations abandoned by
    # a previous application process.
    #
    # Recovery NEVER retries Gate writes and NEVER
    # automatically releases operation locks.
    bot_control_startup_recovery_enabled: bool = True

    # Optional legacy super-admin credentials. They no longer protect public GET routes.
    dashboard_username: str = ""
    dashboard_password: str = ""

    # Comma-separated browser origins allowed to call the API.
    cors_origins: str = "https://zolpho.github.io"

    default_drawdown_alert_pct: float = 12.0
    default_loss_alert_usdt: float = 100.0
    default_liquidation_distance_pct: float = 10.0
    alert_cooldown_seconds: int = 3600

    @field_validator("treasury_main_account")
    @classmethod
    def normalize_treasury_main_account(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError(
                "TREASURY_MAIN_ACCOUNT cannot be empty"
            )
        return normalized

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
    def bot_control_live_account_list(self) -> set[str]:
        return {
            item.strip()
            for item in self.bot_control_live_accounts.split(",")
            if item.strip()
        }

    def bot_control_live_account_allowed(
        self,
        account_id: str,
    ) -> bool:
        allowed = self.bot_control_live_account_list

        return (
            "*" in allowed
            or account_id in allowed
        )

    @property
    def treasury_transfers_live_account_list(
        self,
    ) -> set[str]:
        return {
            item.strip().lower()
            for item in (
                self.treasury_transfers_live_accounts
                .split(",")
            )
            if item.strip()
        }

    def treasury_transfers_live_account_allowed(
        self,
        account_id: str,
    ) -> bool:
        allowed = (
            self.treasury_transfers_live_account_list
        )

        account_id = account_id.strip().lower()

        return (
            "*" in allowed
            or account_id in allowed
        )


    @property
    def treasury_withdrawals_live_account_list(
        self,
    ) -> set[str]:
        return {
            item.strip().lower()
            for item in (
                self.treasury_withdrawals_live_accounts
                .split(",")
            )
            if item.strip()
        }

    def treasury_withdrawals_live_account_allowed(
        self,
        account_id: str,
    ) -> bool:
        allowed = (
            self.treasury_withdrawals_live_account_list
        )

        account_id = account_id.strip().lower()

        return (
            "*" in allowed
            or account_id in allowed
        )

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
