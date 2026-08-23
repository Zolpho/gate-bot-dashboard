from __future__ import annotations

from decimal import Decimal

from app.accounts import GateAccountConfig
from app.treasury_transfer import (
    build_subaccount_to_main_preflight,
    live_transfer_confirmation_text,
    user_transfer_confirmation_text,
)
from app.treasury_transfer_reconcile import (
    interpret_transfer_order_status,
)


def source() -> GateAccountConfig:
    return GateAccountConfig(
        id="arnold",
        name="Arnold",
        api_key="key",
        api_secret="secret",
        enabled=True,
        account_type="subaccount",
        gate_uid="12345678",
    )


def test_live_confirmation_binds_transfer_intent() -> None:
    value = live_transfer_confirmation_text(
        base_text="LIVE TRANSFER",
        source_account_id="arnold",
        destination_account_id="zolnode",
        currency="usdt",
        amount=Decimal("1"),
    )

    assert (
        value
        == "LIVE TRANSFER arnold 1 USDT TO zolnode"
    )



def test_user_transfer_confirmation_is_human_typable() -> None:
    value = user_transfer_confirmation_text(
        base_text="TRANSFER",
        source_account_id="zolnode",
        destination_account_id="arnold",
        currency="eqty",
        amount=Decimal("10000"),
    )

    assert (
        value
        == "TRANSFER 10000 EQTY FROM zolnode TO arnold"
    )


def test_preflight_exposes_live_transfer_flag() -> None:
    result = build_subaccount_to_main_preflight(
        source_account=source(),
        main_account_id="zolnode",
        currency="USDT",
        amount=Decimal("1"),
        spot_accounts=[
            {
                "currency": "USDT",
                "available": "10",
                "locked": "0",
            }
        ],
    )

    assert result["can_transfer"] is True


def test_reconcile_success() -> None:
    result = interpret_transfer_order_status(
        {
            "tx_id": "123",
            "status": "SUCCESS",
        }
    )

    assert result.outcome == "success"
    assert result.request_status == "success"
    assert result.terminal is True
    assert result.release_lock is True


def test_reconcile_fail() -> None:
    result = interpret_transfer_order_status(
        {
            "tx_id": "123",
            "status": "FAIL",
        }
    )

    assert result.outcome == "failed"
    assert result.request_status == "failed"
    assert result.terminal is True
    assert result.release_lock is True


def test_reconcile_pending_keeps_lock() -> None:
    result = interpret_transfer_order_status(
        {
            "tx_id": "123",
            "status": "PENDING",
        }
    )

    assert result.outcome == "pending"
    assert result.terminal is False
    assert result.release_lock is False


def test_reconcile_partial_success_requires_attention() -> None:
    result = interpret_transfer_order_status(
        {
            "tx_id": "123",
            "status": "PARTIAL_SUCCESS",
        }
    )

    assert result.outcome == "partial_success"
    assert result.request_status == "attention"
    assert result.release_lock is False


def test_reconcile_unknown_keeps_lock() -> None:
    result = interpret_transfer_order_status(
        {
            "status": "SOMETHING_NEW",
        }
    )

    assert result.outcome == "unknown"
    assert result.request_status == "uncertain"
    assert result.release_lock is False


def test_submission_4xx_is_definitive_rejection() -> None:
    from app.treasury_transfer_reconcile import (
        interpret_transfer_submission_error,
    )

    result = interpret_transfer_submission_error(403)

    assert result.request_status == "rejected"
    assert result.definitive is True
    assert result.release_lock is True


def test_submission_network_failure_is_uncertain() -> None:
    from app.treasury_transfer_reconcile import (
        interpret_transfer_submission_error,
    )

    result = interpret_transfer_submission_error(None)

    assert result.request_status == "uncertain"
    assert result.definitive is False
    assert result.release_lock is False


def test_submission_5xx_is_uncertain() -> None:
    from app.treasury_transfer_reconcile import (
        interpret_transfer_submission_error,
    )

    result = interpret_transfer_submission_error(500)

    assert result.request_status == "uncertain"
    assert result.definitive is False
    assert result.release_lock is False
