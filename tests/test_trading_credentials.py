import pytest

from app.accounts import GateAccountConfig
from app.trading_credentials import (
    TradingConfigError,
    _validate_trading_accounts,
)


def account(
    account_id: str,
    key: str,
    *,
    uid: str | None = None,
    account_type: str = "subaccount",
) -> GateAccountConfig:
    return GateAccountConfig(
        id=account_id,
        name=account_id,
        api_key=key,
        api_secret=f"{key}-secret",
        enabled=True,
        account_type=account_type,
        gate_uid=uid or f"uid-{account_id}",
    )


def test_trading_accepts_isolated_matching_credential():
    monitor = account(
        "arnold",
        "monitor-key",
    )

    trading = account(
        "arnold",
        "trading-key",
    )

    result = _validate_trading_accounts(
        [trading],
        [monitor],
        [],
        None,
    )

    assert result == (trading,)


def test_trading_rejects_unknown_monitor_account():
    trading = account(
        "arnold",
        "trading-key",
    )

    with pytest.raises(
        TradingConfigError,
        match="unknown Monitor",
    ):
        _validate_trading_accounts(
            [trading],
            [],
            [],
            None,
        )


def test_trading_rejects_uid_mismatch():
    monitor = account(
        "arnold",
        "monitor-key",
        uid="100",
    )

    trading = account(
        "arnold",
        "trading-key",
        uid="200",
    )

    with pytest.raises(
        TradingConfigError,
        match="Gate UID mismatch",
    ):
        _validate_trading_accounts(
            [trading],
            [monitor],
            [],
            None,
        )


def test_trading_rejects_account_type_mismatch():
    monitor = account(
        "zolnode",
        "monitor-key",
        account_type="main",
    )

    trading = account(
        "zolnode",
        "trading-key",
        account_type="subaccount",
    )

    with pytest.raises(
        TradingConfigError,
        match="Account type mismatch",
    ):
        _validate_trading_accounts(
            [trading],
            [monitor],
            [],
            None,
        )


def test_trading_rejects_monitor_key_reuse():
    monitor = account(
        "arnold",
        "same-key",
    )

    trading = account(
        "arnold",
        "same-key",
    )

    with pytest.raises(
        TradingConfigError,
        match="Monitor API key",
    ):
        _validate_trading_accounts(
            [trading],
            [monitor],
            [],
            None,
        )


def test_trading_rejects_bot_control_key_reuse():
    monitor = account(
        "arnold",
        "monitor-key",
    )

    bot_control = account(
        "arnold",
        "control-key",
    )

    trading = account(
        "arnold",
        "control-key",
    )

    with pytest.raises(
        TradingConfigError,
        match="Bot Control API key",
    ):
        _validate_trading_accounts(
            [trading],
            [monitor],
            [bot_control],
            None,
        )


def test_trading_rejects_treasury_key_reuse():
    monitor = account(
        "arnold",
        "monitor-key",
    )

    trading = account(
        "arnold",
        "treasury-key",
    )

    treasury = account(
        "zolnode",
        "treasury-key",
        account_type="main",
    )

    with pytest.raises(
        TradingConfigError,
        match="Treasury API key",
    ):
        _validate_trading_accounts(
            [trading],
            [monitor],
            [],
            treasury,
        )


def test_trading_rejects_key_reuse_between_accounts():
    monitors = [
        account(
            "arnold",
            "monitor-a",
            uid="101",
        ),
        account(
            "eqtydao",
            "monitor-b",
            uid="102",
        ),
    ]

    trading = [
        account(
            "arnold",
            "shared-trading-key",
            uid="101",
        ),
        account(
            "eqtydao",
            "shared-trading-key",
            uid="102",
        ),
    ]

    with pytest.raises(
        TradingConfigError,
        match="reused by accounts",
    ):
        _validate_trading_accounts(
            trading,
            monitors,
            [],
            None,
        )
