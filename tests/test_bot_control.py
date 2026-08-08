from __future__ import annotations

import pytest

from app.accounts import GateAccountConfig
from app.bot_control import (
    BotControlConfigError,
    _validate_bot_control_accounts,
)


def account(
    account_id: str,
    *,
    key: str,
    uid: str,
) -> GateAccountConfig:
    return GateAccountConfig(
        id=account_id,
        name=account_id,
        api_key=key,
        api_secret=f"secret-{key}",
        enabled=True,
        gate_uid=uid,
    )


def test_bot_control_accepts_separate_matching_credential() -> None:
    monitor = account(
        "zolnode",
        key="monitor-key",
        uid="13079163",
    )

    control = account(
        "zolnode",
        key="control-key",
        uid="13079163",
    )

    result = _validate_bot_control_accounts(
        [control],
        [monitor],
    )

    assert result == (control,)


def test_bot_control_rejects_gate_uid_mismatch() -> None:
    monitor = account(
        "zolnode",
        key="monitor-key",
        uid="13079163",
    )

    control = account(
        "zolnode",
        key="control-key",
        uid="99999999",
    )

    with pytest.raises(
        BotControlConfigError,
        match="Gate UID mismatch",
    ):
        _validate_bot_control_accounts(
            [control],
            [monitor],
        )


def test_bot_control_rejects_monitor_key_reuse() -> None:
    monitor = account(
        "zolnode",
        key="same-key",
        uid="13079163",
    )

    control = account(
        "zolnode",
        key="same-key",
        uid="13079163",
    )

    with pytest.raises(
        BotControlConfigError,
        match="same API key",
    ):
        _validate_bot_control_accounts(
            [control],
            [monitor],
        )


def test_bot_control_rejects_unknown_account() -> None:
    monitor = account(
        "zolnode",
        key="monitor-key",
        uid="13079163",
    )

    control = account(
        "unknown",
        key="control-key",
        uid="123456",
    )

    with pytest.raises(
        BotControlConfigError,
        match="unknown Monitor account",
    ):
        _validate_bot_control_accounts(
            [control],
            [monitor],
        )
