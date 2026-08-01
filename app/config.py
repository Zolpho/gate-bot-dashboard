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
    gate_api_key: str = ""
    gate_api_secret: str = ""
    gate_language: str = "en-US"
    gate_request_timeout_seconds: float = 20.0
    gate_bot_page_size: int = 50
    gate_details_concurrency: int = 4

    poll_seconds: int = 60
    stale_after_minutes: int = 5
    missing_bot_grace_syncs: int = 2
    snapshot_retention_days: int = 365

    demo_mode: bool = False
    demo_seed: int = 42

    allow_bot_stop: bool = False
    bot_stop_confirmation_text: str = "STOP"

    dashboard_username: str = ""
    dashboard_password: str = ""

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

    @field_validator("poll_seconds")
    @classmethod
    def validate_poll_seconds(cls, value: int) -> int:
        return max(15, value)

    @property
    def gate_configured(self) -> bool:
        return bool(self.gate_api_key and self.gate_api_secret)

    @property
    def auth_enabled(self) -> bool:
        return bool(self.dashboard_username and self.dashboard_password)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
