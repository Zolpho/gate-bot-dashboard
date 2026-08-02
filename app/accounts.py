from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import Settings, get_settings

_ACCOUNT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class AccountConfigError(RuntimeError):
    """Raised when the local Gate account configuration is invalid."""


@dataclass(frozen=True, slots=True)
class GateAccountConfig:
    id: str
    name: str
    api_key: str
    api_secret: str
    enabled: bool = True
    account_type: str = "subaccount"
    gate_uid: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def safe_dict(self, *, include_uid: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "name": self.name,
            "account_type": self.account_type,
            "enabled": self.enabled,
            "configured": self.configured,
        }
        if include_uid:
            result["gate_uid"] = self.gate_uid
        return result


def _parse_bool(value: Any, *, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise AccountConfigError(f"Invalid boolean value: {value!r}")


def _clean_account(raw: Any, index: int) -> GateAccountConfig:
    if not isinstance(raw, dict):
        raise AccountConfigError(f"Account entry {index} must be a JSON object")

    account_id = str(raw.get("id", "")).strip().lower()
    if not _ACCOUNT_ID_RE.fullmatch(account_id):
        raise AccountConfigError(
            f"Invalid account id at entry {index}: use 1-64 lowercase letters, numbers, '_' or '-'"
        )

    name = str(raw.get("name") or account_id).strip()
    if not name:
        raise AccountConfigError(f"Account '{account_id}' has an empty name")

    api_key = str(raw.get("api_key", "")).strip()
    api_secret = str(raw.get("api_secret", "")).strip()
    enabled = _parse_bool(raw.get("enabled"), default=True)
    account_type = str(raw.get("account_type") or "subaccount").strip().lower()
    gate_uid = str(raw.get("gate_uid") or "").strip()

    if enabled and (not api_key or not api_secret):
        raise AccountConfigError(f"Enabled account '{account_id}' is missing api_key or api_secret")

    return GateAccountConfig(
        id=account_id,
        name=name,
        api_key=api_key,
        api_secret=api_secret,
        enabled=enabled,
        account_type=account_type,
        gate_uid=gate_uid,
    )


def _load_from_file(path: Path) -> list[GateAccountConfig]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise AccountConfigError(f"Cannot read Gate accounts file {path}: {exc}") from exc

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AccountConfigError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("accounts"), list):
        raise AccountConfigError(f"{path} must contain an object with an 'accounts' array")

    accounts = [_clean_account(raw, index) for index, raw in enumerate(payload["accounts"], start=1)]
    ids = [account.id for account in accounts]
    duplicates = sorted({account_id for account_id in ids if ids.count(account_id) > 1})
    if duplicates:
        raise AccountConfigError(f"Duplicate account id(s): {', '.join(duplicates)}")
    return accounts


@lru_cache(maxsize=1)
def load_gate_accounts() -> tuple[GateAccountConfig, ...]:
    settings = get_settings()
    accounts = _load_from_file(settings.gate_accounts_file)

    # Backward-compatible single-account mode. The JSON file takes precedence.
    if not accounts and settings.gate_api_key and settings.gate_api_secret:
        accounts = [
            GateAccountConfig(
                id=settings.gate_account_id,
                name=settings.gate_account_name,
                api_key=settings.gate_api_key,
                api_secret=settings.gate_api_secret,
                enabled=True,
                account_type=settings.gate_account_type,
                gate_uid=settings.gate_uid,
            )
        ]
    return tuple(accounts)


def clear_gate_accounts_cache() -> None:
    load_gate_accounts.cache_clear()


def enabled_gate_accounts() -> tuple[GateAccountConfig, ...]:
    return tuple(account for account in load_gate_accounts() if account.enabled and account.configured)


def get_gate_account(account_id: str) -> GateAccountConfig | None:
    normalized = account_id.strip().lower()
    return next((account for account in load_gate_accounts() if account.id == normalized), None)


def resolve_gate_account(account_id: str | None = None) -> GateAccountConfig:
    accounts = enabled_gate_accounts()
    if account_id:
        account = next((item for item in accounts if item.id == account_id.strip().lower()), None)
        if account is None:
            raise AccountConfigError(f"Unknown or disabled Gate account: {account_id}")
        return account
    if not accounts:
        raise AccountConfigError("No enabled Gate accounts are configured")
    if len(accounts) > 1:
        raise AccountConfigError("account_id is required because multiple Gate accounts are configured")
    return accounts[0]


def safe_account_config() -> list[dict[str, Any]]:
    return [account.safe_dict() for account in load_gate_accounts()]
