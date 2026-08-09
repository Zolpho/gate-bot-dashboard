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


class TreasuryConfigError(AccountConfigError):
    """Raised when Treasury credentials are unsafe or invalid."""


def _validate_treasury_accounts(
    treasury_accounts: Sequence[GateAccountConfig],
    monitor_accounts: Sequence[GateAccountConfig],
    bot_control_accounts: Sequence[GateAccountConfig],
    *,
    main_account_id: str,
) -> GateAccountConfig | None:
    main_account_id = main_account_id.strip().lower()

    configured = [
        account
        for account in treasury_accounts
        if account.enabled and account.configured
    ]

    # Missing Treasury credentials are valid in T1. Treasury is optional
    # until an explicit privileged credential is provisioned.
    if not configured:
        return None

    if len(configured) != 1:
        raise TreasuryConfigError(
            "Treasury requires exactly one enabled, configured "
            "credential"
        )

    treasury = configured[0]

    if treasury.id != main_account_id:
        raise TreasuryConfigError(
            "Treasury credential must belong to configured main "
            f"account '{main_account_id}', not '{treasury.id}'"
        )

    if treasury.account_type != "main":
        raise TreasuryConfigError(
            f"Treasury account '{treasury.id}' must have "
            "account_type='main'"
        )

    monitor = next(
        (
            account
            for account in monitor_accounts
            if account.id == main_account_id
        ),
        None,
    )

    if monitor is None:
        raise TreasuryConfigError(
            f"Treasury main account '{main_account_id}' does not "
            "exist in Monitor configuration"
        )

    if monitor.account_type != "main":
        raise TreasuryConfigError(
            f"Monitor account '{main_account_id}' must have "
            "account_type='main' before Treasury can be enabled"
        )

    if not monitor.gate_uid:
        raise TreasuryConfigError(
            f"Monitor account '{main_account_id}' has no gate_uid"
        )

    if not treasury.gate_uid:
        raise TreasuryConfigError(
            f"Treasury account '{main_account_id}' has no gate_uid"
        )

    if treasury.gate_uid != monitor.gate_uid:
        raise TreasuryConfigError(
            f"Gate UID mismatch for Treasury '{main_account_id}': "
            f"Monitor={monitor.gate_uid}, "
            f"Treasury={treasury.gate_uid}"
        )

    # A Treasury credential must never be one of the ordinary
    # Monitor credentials, for any account.
    for account in monitor_accounts:
        if (
            treasury.api_key
            and account.api_key
            and treasury.api_key == account.api_key
        ):
            raise TreasuryConfigError(
                "Treasury credential reuses a Monitor API key "
                f"from account '{account.id}'. Separate credentials "
                "are required."
            )

    # Nor may it reuse any Bot Control credential.
    for account in bot_control_accounts:
        if (
            treasury.api_key
            and account.api_key
            and treasury.api_key == account.api_key
        ):
            raise TreasuryConfigError(
                "Treasury credential reuses a Bot Control API key "
                f"from account '{account.id}'. Separate credentials "
                "are required."
            )

    return treasury


@lru_cache(maxsize=1)
def load_treasury_account() -> GateAccountConfig | None:
    settings = get_settings()

    try:
        treasury_accounts = tuple(
            _load_from_file(settings.gate_treasury_file)
        )
    except AccountConfigError as exc:
        raise TreasuryConfigError(str(exc)) from exc

    # An absent/empty file is a valid unconfigured Treasury state.
    if not treasury_accounts:
        return None

    try:
        return _validate_treasury_accounts(
            treasury_accounts,
            load_gate_accounts(),
            load_bot_control_accounts(),
            main_account_id=settings.treasury_main_account,
        )
    except TreasuryConfigError:
        raise
    except AccountConfigError as exc:
        raise TreasuryConfigError(str(exc)) from exc


def clear_treasury_cache() -> None:
    load_treasury_account.cache_clear()


def get_treasury_account() -> GateAccountConfig | None:
    return load_treasury_account()


def safe_treasury_config() -> dict:
    settings = get_settings()

    try:
        account = load_treasury_account()
    except TreasuryConfigError as exc:
        return {
            "phase": "T2B_TRANSFER_CONTROL",
            "configured": False,
            "main_account": settings.treasury_main_account,
            "account": None,
            "transfers_enabled": False,
            "withdrawals_enabled": False,
            "config_error": str(exc),
        }

    return {
        "phase": "T2B_TRANSFER_CONTROL",
        "configured": account is not None,
        "main_account": settings.treasury_main_account,
        "account": (
            account.safe_dict()
            if account is not None
            else None
        ),
        "transfers_enabled": bool(
            account is not None
            and settings.treasury_transfers_live_armed
        ),
        "transfers_live_armed": (
            settings.treasury_transfers_live_armed
        ),
        "transfers_live_accounts": sorted(
            settings.treasury_transfers_live_account_list
        ),
        "withdrawals_enabled": False,
        "config_error": "",
    }
