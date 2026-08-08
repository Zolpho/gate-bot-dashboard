from __future__ import annotations

from functools import lru_cache

from .accounts import (
    AccountConfigError,
    GateAccountConfig,
    _load_from_file,
    load_gate_accounts,
)
from .config import get_settings


class BotControlConfigError(AccountConfigError):
    """Raised when Bot Control credentials are invalid."""


def _validate_bot_control_accounts(
    control_accounts: tuple[GateAccountConfig, ...]
    | list[GateAccountConfig],
    monitor_accounts: tuple[GateAccountConfig, ...]
    | list[GateAccountConfig],
) -> tuple[GateAccountConfig, ...]:
    monitors = {
        account.id: account
        for account in monitor_accounts
    }

    validated: list[GateAccountConfig] = []

    for control in control_accounts:
        monitor = monitors.get(control.id)

        if monitor is None:
            raise BotControlConfigError(
                "Bot Control credential exists for unknown "
                f"Monitor account '{control.id}'"
            )

        if not monitor.gate_uid:
            raise BotControlConfigError(
                f"Monitor account '{control.id}' has no gate_uid"
            )

        if not control.gate_uid:
            raise BotControlConfigError(
                f"Bot Control account '{control.id}' has no gate_uid"
            )

        if control.gate_uid != monitor.gate_uid:
            raise BotControlConfigError(
                f"Gate UID mismatch for '{control.id}': "
                f"Monitor={monitor.gate_uid}, "
                f"Bot Control={control.gate_uid}"
            )

        if (
            control.api_key
            and monitor.api_key
            and control.api_key == monitor.api_key
        ):
            raise BotControlConfigError(
                f"Bot Control account '{control.id}' uses the "
                "same API key as Monitor. Separate credentials "
                "are required."
            )

        validated.append(control)

    return tuple(validated)


@lru_cache(maxsize=1)
def load_bot_control_accounts() -> tuple[GateAccountConfig, ...]:
    settings = get_settings()

    try:
        control_accounts = tuple(
            _load_from_file(settings.gate_bot_control_file)
        )
        monitor_accounts = load_gate_accounts()

        return _validate_bot_control_accounts(
            control_accounts,
            monitor_accounts,
        )

    except BotControlConfigError:
        raise

    except AccountConfigError as exc:
        raise BotControlConfigError(str(exc)) from exc


def clear_bot_control_cache() -> None:
    load_bot_control_accounts.cache_clear()


def enabled_bot_control_accounts() -> tuple[GateAccountConfig, ...]:
    monitors = {
        account.id: account
        for account in load_gate_accounts()
        if account.enabled and account.configured
    }

    return tuple(
        account
        for account in load_bot_control_accounts()
        if (
            account.enabled
            and account.configured
            and account.id in monitors
        )
    )


def get_bot_control_account(
    account_id: str,
) -> GateAccountConfig | None:
    normalized = account_id.strip().lower()

    return next(
        (
            account
            for account in enabled_bot_control_accounts()
            if account.id == normalized
        ),
        None,
    )


def safe_bot_control_config() -> list[dict]:
    return [
        account.safe_dict()
        for account in load_bot_control_accounts()
    ]
