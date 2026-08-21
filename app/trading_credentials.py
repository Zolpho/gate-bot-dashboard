from __future__ import annotations

from functools import lru_cache
from typing import Sequence

from .accounts import (
    AccountConfigError,
    GateAccountConfig,
    _load_from_file,
    load_gate_accounts,
)
from .bot_control import load_bot_control_accounts
from .config import get_settings
from .treasury import load_treasury_account


class TradingConfigError(AccountConfigError):
    """Raised when Spot Trading credentials are unsafe."""


def _same_key(
    left: GateAccountConfig,
    right: GateAccountConfig,
) -> bool:
    return bool(
        left.api_key
        and right.api_key
        and left.api_key == right.api_key
    )


def _validate_trading_accounts(
    trading_accounts: Sequence[GateAccountConfig],
    monitor_accounts: Sequence[GateAccountConfig],
    bot_control_accounts: Sequence[GateAccountConfig],
    treasury_account: GateAccountConfig | None,
) -> tuple[GateAccountConfig, ...]:
    monitors = {
        account.id: account
        for account in monitor_accounts
    }

    validated: list[GateAccountConfig] = []
    seen_api_keys: dict[str, str] = {}

    for trading in trading_accounts:
        monitor = monitors.get(trading.id)

        if monitor is None:
            raise TradingConfigError(
                "Trading credential exists for unknown "
                f"Monitor account '{trading.id}'"
            )

        if not monitor.gate_uid:
            raise TradingConfigError(
                f"Monitor account '{trading.id}' "
                "has no gate_uid"
            )

        if not trading.gate_uid:
            raise TradingConfigError(
                f"Trading account '{trading.id}' "
                "has no gate_uid"
            )

        if trading.gate_uid != monitor.gate_uid:
            raise TradingConfigError(
                f"Gate UID mismatch for '{trading.id}': "
                f"Monitor={monitor.gate_uid}, "
                f"Trading={trading.gate_uid}"
            )

        if trading.account_type != monitor.account_type:
            raise TradingConfigError(
                f"Account type mismatch for '{trading.id}': "
                f"Monitor={monitor.account_type}, "
                f"Trading={trading.account_type}"
            )

        for account in monitor_accounts:
            if _same_key(
                trading,
                account,
            ):
                raise TradingConfigError(
                    f"Trading account '{trading.id}' "
                    "reuses a Monitor API key from "
                    f"account '{account.id}'. "
                    "Separate credentials are required."
                )

        for account in bot_control_accounts:
            if _same_key(
                trading,
                account,
            ):
                raise TradingConfigError(
                    f"Trading account '{trading.id}' "
                    "reuses a Bot Control API key from "
                    f"account '{account.id}'. "
                    "Separate credentials are required."
                )

        if (
            treasury_account is not None
            and _same_key(
                trading,
                treasury_account,
            )
        ):
            raise TradingConfigError(
                f"Trading account '{trading.id}' "
                "reuses the Treasury API key. "
                "Separate credentials are required."
            )

        if trading.api_key:
            previous = seen_api_keys.get(
                trading.api_key
            )

            if previous is not None:
                raise TradingConfigError(
                    "Trading API key is reused by "
                    f"accounts '{previous}' and "
                    f"'{trading.id}'"
                )

            seen_api_keys[
                trading.api_key
            ] = trading.id

        validated.append(trading)

    return tuple(validated)


@lru_cache(maxsize=1)
def load_trading_accounts() -> tuple[
    GateAccountConfig,
    ...,
]:
    settings = get_settings()

    try:
        trading_accounts = tuple(
            _load_from_file(
                settings.gate_trading_file
            )
        )

        # Missing Trading credentials are a valid
        # unconfigured state.
        if not trading_accounts:
            return ()

        return _validate_trading_accounts(
            trading_accounts,
            load_gate_accounts(),
            load_bot_control_accounts(),
            load_treasury_account(),
        )

    except TradingConfigError:
        raise

    except AccountConfigError as exc:
        raise TradingConfigError(
            str(exc)
        ) from exc


def clear_trading_cache() -> None:
    load_trading_accounts.cache_clear()


def enabled_trading_accounts() -> tuple[
    GateAccountConfig,
    ...,
]:
    monitors = {
        account.id: account
        for account in load_gate_accounts()
        if (
            account.enabled
            and account.configured
        )
    }

    return tuple(
        account
        for account in load_trading_accounts()
        if (
            account.enabled
            and account.configured
            and account.id in monitors
        )
    )


def get_trading_account(
    account_id: str,
) -> GateAccountConfig | None:
    normalized = (
        account_id.strip().lower()
    )

    return next(
        (
            account
            for account
            in enabled_trading_accounts()
            if account.id == normalized
        ),
        None,
    )


def safe_trading_config() -> dict:
    settings = get_settings()

    try:
        accounts = load_trading_accounts()

    except TradingConfigError as exc:
        return {
            "configured": False,
            "accounts": [],
            "execution_implemented": False,
            "limit_orders_enabled": False,
            "requested_enabled": bool(
                settings
                .trading_limit_orders_enabled
            ),
            "config_error": str(exc),
        }

    return {
        "configured": bool(
            enabled_trading_accounts()
        ),
        "accounts": [
            account.safe_dict()
            for account in accounts
        ],

        # Safety invariant for this stage.
        "execution_implemented": False,
        "limit_orders_enabled": False,

        # We expose the requested setting separately so an
        # accidental true value can never be mistaken for
        # implemented execution.
        "requested_enabled": bool(
            settings
            .trading_limit_orders_enabled
        ),
        "config_error": "",
    }
