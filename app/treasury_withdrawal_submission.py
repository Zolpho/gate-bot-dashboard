from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .accounts import GateAccountConfig
from .config import Settings
from .gate_client import GateClient
from .treasury_withdrawal_audit import (
    TreasuryWithdrawalStateError,
    apply_withdrawal_reconciliation,
    begin_withdrawal_submission,
    get_withdrawal_request,
    mark_withdrawal_submission_attempt,
)
from .treasury_withdrawal_execution import (
    TreasuryWithdrawalExecutionError,
    build_gate_withdrawal_payload,
    classify_withdrawal_status,
    select_withdrawal_record,
)
from .treasury_withdrawal_locks import (
    get_withdrawal_lock_for_request,
    release_withdrawal_lock,
)


class TreasuryWithdrawalSubmissionError(
    RuntimeError
):
    pass


def _safe_error(exc: Exception) -> str:
    text = str(exc).strip()

    if len(text) > 500:
        text = text[:500] + "..."

    return (
        f"{type(exc).__name__}: {text}"
        if text
        else type(exc).__name__
    )


def _credential_check(
    settings: Settings,
    account: GateAccountConfig,
) -> None:
    expected = (
        settings.treasury_main_account
        .strip()
        .lower()
    )

    actual = str(
        getattr(account, "id", "") or ""
    ).strip().lower()

    if actual != expected:
        raise TreasuryWithdrawalSubmissionError(
            "External withdrawal requires the "
            "dedicated Treasury main-account "
            "credential"
        )

    if not bool(
        getattr(account, "enabled", False)
    ):
        raise TreasuryWithdrawalSubmissionError(
            "Treasury credential is disabled"
        )

    account_type = str(
        getattr(account, "account_type", "")
        or ""
    ).strip().lower()

    if account_type and account_type != "main":
        raise TreasuryWithdrawalSubmissionError(
            "Treasury withdrawal credential must "
            "belong to the Gate main account"
        )


def _require_request_lock(
    row: dict[str, Any],
) -> dict[str, Any]:
    lock = get_withdrawal_lock_for_request(
        row["request_id"]
    )

    if lock is None:
        raise TreasuryWithdrawalSubmissionError(
            "Withdrawal request has no custody "
            "operation lock"
        )

    expected = {
        "owner_account_id": (
            str(
                row["owner_account_id"]
            ).strip().lower()
        ),
        "custody_account_id": (
            str(
                row["custody_account_id"]
            ).strip().lower()
        ),
        "currency": (
            str(
                row["currency"]
            ).strip().upper()
        ),
        "owner_request_id": (
            row["request_id"]
        ),
    }

    for key, value in expected.items():
        if lock.get(key) != value:
            raise TreasuryWithdrawalSubmissionError(
                "Withdrawal custody lock does not "
                "match the request"
            )

    return lock


def _decimal_equal(
    first: Any,
    second: Any,
) -> bool:
    try:
        return (
            Decimal(str(first))
            == Decimal(str(second))
        )
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return False


def withdrawal_record_mismatches(
    request: dict[str, Any],
    record: dict[str, Any],
) -> list[str]:
    mismatches: list[str] = []

    expected_order = str(
        request.get(
            "gate_withdraw_order_id"
        )
        or ""
    ).strip()

    actual_order = str(
        record.get("withdraw_order_id")
        or ""
    ).strip()

    if actual_order != expected_order:
        mismatches.append(
            "withdraw_order_id"
        )

    if (
        str(
            record.get("currency") or ""
        ).strip().upper()
        != str(
            request.get("currency") or ""
        ).strip().upper()
    ):
        mismatches.append("currency")

    if (
        str(
            record.get("chain") or ""
        ).strip().upper()
        != str(
            request.get("chain") or ""
        ).strip().upper()
    ):
        mismatches.append("chain")

    if (
        str(
            record.get("address") or ""
        ).strip()
        != str(
            request.get("address") or ""
        ).strip()
    ):
        mismatches.append("address")

    if (
        str(
            record.get("memo") or ""
        )
        != str(
            request.get("memo") or ""
        )
    ):
        mismatches.append("memo")

    if not _decimal_equal(
        record.get("amount"),
        request.get("amount"),
    ):
        mismatches.append("amount")

    return mismatches


def _record_details(
    record: dict[str, Any],
) -> dict[str, Any]:
    # Deliberately omit the full destination address.
    # The immutable request already stores it.
    keys = (
        "id",
        "withdraw_id",
        "withdraw_order_id",
        "currency",
        "amount",
        "fee",
        "chain",
        "status",
        "txid",
        "block_number",
        "fail_reason",
        "timestamp",
        "timestamp2",
    )

    return {
        key: record.get(key)
        for key in keys
        if key in record
    }


async def submit_withdrawal_once(
    *,
    settings: Settings,
    request_id: str,
    username: str,
    treasury_account: GateAccountConfig,
) -> dict[str, Any]:
    row = get_withdrawal_request(
        request_id
    )

    if row is None:
        raise TreasuryWithdrawalSubmissionError(
            "Withdrawal request not found"
        )

    # Any state at/after the submission boundary is
    # permanently retry-forbidden. The only safe next
    # action is reconciliation.
    if row["status"] in {
        "withdrawal_submitting",
        "withdrawal_submitted",
        "withdrawal_reconciling",
    }:
        return {
            "status": row["status"],
            "idempotent_replay": True,
            "gate_write_performed": False,
            "requires_reconciliation": True,
            "audit": row,
            "operation_lock": (
                get_withdrawal_lock_for_request(
                    request_id
                )
            ),
        }

    if row["status"] in {
        "withdrawal_done_unsettled",
        "withdrawal_failed",
    }:
        return {
            "status": row["status"],
            "idempotent_replay": True,
            "gate_write_performed": False,
            "requires_reconciliation": False,
            "audit": row,
            "operation_lock": (
                get_withdrawal_lock_for_request(
                    request_id
                )
            ),
        }

    if row["status"] != "jit_ready":
        raise TreasuryWithdrawalSubmissionError(
            "Withdrawal request is not ready "
            "for external submission"
        )

    if not settings.treasury_withdrawals_live_armed:
        raise TreasuryWithdrawalSubmissionError(
            "External Treasury withdrawals "
            "are not live-armed"
        )

    if not (
        settings
        .treasury_withdrawals_live_account_allowed(
            row["owner_account_id"]
        )
    ):
        raise TreasuryWithdrawalSubmissionError(
            "Economic owner is not allowed for "
            "live external withdrawals"
        )

    _credential_check(
        settings,
        treasury_account,
    )

    lock = _require_request_lock(row)

    payload = build_gate_withdrawal_payload(
        row
    )

    order_id = payload[
        "withdraw_order_id"
    ]

    try:
        audit, start_event, _changed = (
            begin_withdrawal_submission(
                request_id,
                username=username,
                gate_withdraw_order_id=(
                    order_id
                ),
                details={
                    "currency": row["currency"],
                    "chain": row["chain"],
                    "amount": row["amount"],
                    "destination_id": (
                        row["destination_id"]
                    ),
                },
            )
        )

    except TreasuryWithdrawalStateError as exc:
        raise TreasuryWithdrawalSubmissionError(
            str(exc)
        ) from exc

    try:
        async with GateClient(
            settings,
            treasury_account,
        ) as client:
            # EXACTLY ONE external withdrawal POST.
            response = (
                await client.create_withdrawal(
                    payload
                )
            )

    except Exception as exc:
        error = _safe_error(exc)

        audit, event, _changed = (
            mark_withdrawal_submission_attempt(
                request_id,
                username=username,
                gate_withdraw_order_id=(
                    order_id
                ),
                new_status=(
                    "withdrawal_reconciling"
                ),
                error=error,
                details={
                    "reason": (
                        "Gate POST outcome is "
                        "not safely known."
                    ),
                    "automatic_retry_allowed": (
                        False
                    ),
                },
            )
        )

        return {
            "status": (
                "withdrawal_reconciling"
            ),
            "gate_write_performed": True,
            "gate_write_accepted": None,
            "requires_reconciliation": True,
            "automatic_retry_allowed": False,
            "error": error,
            "audit": audit,
            "event": event,
            "operation_lock": lock,
        }

    data = (
        response.data
        if isinstance(response.data, dict)
        else {}
    )

    response_order_id = str(
        data.get("withdraw_order_id")
        or ""
    ).strip()

    gate_withdrawal_id = str(
        data.get("id")
        or data.get("withdraw_id")
        or ""
    ).strip()

    gate_txid = str(
        data.get("txid")
        or ""
    ).strip()

    gate_status = str(
        data.get("status")
        or ""
    ).strip().upper()

    # A 200 response is only submission acceptance.
    # If Gate echoes a DIFFERENT custom order ID,
    # treat the result as uncertain and reconcile.
    response_order_mismatch = bool(
        response_order_id
        and response_order_id != order_id
    )

    target_status = (
        "withdrawal_reconciling"
        if response_order_mismatch
        else "withdrawal_submitted"
    )

    error = (
        "Gate accepted the withdrawal POST "
        "but returned a different "
        "withdraw_order_id."
        if response_order_mismatch
        else ""
    )

    audit, event, _changed = (
        mark_withdrawal_submission_attempt(
            request_id,
            username=username,
            gate_withdraw_order_id=order_id,
            new_status=target_status,
            gate_withdrawal_id=(
                gate_withdrawal_id
            ),
            gate_txid=gate_txid,
            gate_status=gate_status,
            error=error,
            details={
                "http_status": (
                    response.status_code
                ),
                "response_order_id_matches": (
                    not response_order_mismatch
                ),
                "automatic_retry_allowed": (
                    False
                ),
            },
        )
    )

    return {
        "status": target_status,
        "gate_write_performed": True,
        "gate_write_accepted": True,
        "requires_reconciliation": True,
        "automatic_retry_allowed": False,
        "gate_http_status": (
            response.status_code
        ),
        "audit": audit,
        "event": event,
        "operation_lock": lock,
    }


async def reconcile_withdrawal(
    *,
    settings: Settings,
    request_id: str,
    username: str,
    treasury_account: GateAccountConfig,
) -> dict[str, Any]:
    """
    GET-only Gate reconciliation.

    This function intentionally does not inspect or
    require the external-withdrawal live arm.
    """
    row = get_withdrawal_request(
        request_id
    )

    if row is None:
        raise TreasuryWithdrawalSubmissionError(
            "Withdrawal request not found"
        )

    _credential_check(
        settings,
        treasury_account,
    )

    if row["status"] == (
        "withdrawal_done_unsettled"
    ):
        return {
            "status": row["status"],
            "idempotent_replay": True,
            "gate_read_performed": False,
            "gate_write_performed": False,
            "requires_reconciliation": False,
            "audit": row,
            "operation_lock": (
                get_withdrawal_lock_for_request(
                    request_id
                )
            ),
        }

    if row["status"] == "withdrawal_failed":
        released = release_withdrawal_lock(
            custody_account_id=(
                row["custody_account_id"]
            ),
            currency=row["currency"],
            owner_request_id=request_id,
        )

        return {
            "status": row["status"],
            "idempotent_replay": True,
            "gate_read_performed": False,
            "gate_write_performed": False,
            "requires_reconciliation": False,
            "lock_released": released,
            "audit": row,
            "operation_lock": (
                get_withdrawal_lock_for_request(
                    request_id
                )
            ),
        }

    allowed = {
        "withdrawal_submitting",
        "withdrawal_submitted",
        "withdrawal_reconciling",
    }

    if row["status"] not in allowed:
        raise TreasuryWithdrawalSubmissionError(
            "Withdrawal request has not crossed "
            "the external submission boundary"
        )

    lock = _require_request_lock(row)

    order_id = str(
        row.get(
            "gate_withdraw_order_id"
        )
        or ""
    ).strip()

    if not order_id:
        raise TreasuryWithdrawalSubmissionError(
            "Withdrawal has no persisted Gate "
            "withdraw_order_id"
        )

    try:
        async with GateClient(
            settings,
            treasury_account,
        ) as client:
            response = (
                await client.list_withdrawals(
                    currency=row["currency"],
                    withdraw_order_id=order_id,
                    limit=100,
                    offset=0,
                )
            )

    except Exception as exc:
        error = _safe_error(exc)

        audit, reconciliation, event, changed = (
            apply_withdrawal_reconciliation(
                request_id,
                username=username,
                gate_withdraw_order_id=order_id,
                expected_statuses=allowed,
                new_status=(
                    "withdrawal_reconciling"
                ),
                outcome="inconclusive",
                confidence="inconclusive",
                summary=(
                    "Gate withdrawal history "
                    "query failed."
                ),
                details={
                    "error": error,
                    "gate_read_performed": True,
                    "gate_write_performed": False,
                },
                error=error,
                completed=False,
            )
        )

        return {
            "status": (
                "withdrawal_reconciling"
            ),
            "gate_read_performed": True,
            "gate_write_performed": False,
            "requires_reconciliation": True,
            "automatic_retry_allowed": False,
            "audit": audit,
            "reconciliation": reconciliation,
            "event": event,
            "state_changed": changed,
            "operation_lock": lock,
        }

    try:
        record = select_withdrawal_record(
            response.data,
            withdraw_order_id=order_id,
        )

    except TreasuryWithdrawalExecutionError as exc:
        record = None
        selection_error = str(exc)

    else:
        selection_error = ""

    if record is None:
        audit, reconciliation, event, changed = (
            apply_withdrawal_reconciliation(
                request_id,
                username=username,
                gate_withdraw_order_id=order_id,
                expected_statuses=allowed,
                new_status=(
                    "withdrawal_reconciling"
                ),
                outcome="inconclusive",
                confidence="inconclusive",
                summary=(
                    "No unique Gate withdrawal "
                    "record matched the persisted "
                    "withdraw_order_id."
                ),
                details={
                    "selection_error": (
                        selection_error or None
                    ),
                    "gate_read_performed": True,
                    "gate_write_performed": False,
                    "automatic_retry_allowed": False,
                },
                completed=False,
            )
        )

        return {
            "status": (
                "withdrawal_reconciling"
            ),
            "gate_read_performed": True,
            "gate_write_performed": False,
            "requires_reconciliation": True,
            "automatic_retry_allowed": False,
            "audit": audit,
            "reconciliation": reconciliation,
            "event": event,
            "state_changed": changed,
            "operation_lock": lock,
        }

    mismatches = (
        withdrawal_record_mismatches(
            row,
            record,
        )
    )

    if mismatches:
        audit, reconciliation, event, changed = (
            apply_withdrawal_reconciliation(
                request_id,
                username=username,
                gate_withdraw_order_id=order_id,
                expected_statuses=allowed,
                new_status=(
                    "withdrawal_reconciling"
                ),
                outcome="inconclusive",
                confidence="inconclusive",
                gate_status=str(
                    record.get("status") or ""
                ).strip().upper(),
                gate_withdrawal_id=str(
                    record.get("id")
                    or record.get(
                        "withdraw_id"
                    )
                    or ""
                ),
                gate_txid=str(
                    record.get("txid") or ""
                ),
                summary=(
                    "Gate withdrawal record did "
                    "not match the immutable "
                    "withdrawal request."
                ),
                details={
                    "mismatches": mismatches,
                    "gate_record": (
                        _record_details(record)
                    ),
                    "automatic_retry_allowed": False,
                },
                write_performed=True,
                completed=False,
            )
        )

        return {
            "status": (
                "withdrawal_reconciling"
            ),
            "gate_read_performed": True,
            "gate_write_performed": False,
            "requires_reconciliation": True,
            "automatic_retry_allowed": False,
            "record_mismatches": mismatches,
            "audit": audit,
            "reconciliation": reconciliation,
            "event": event,
            "state_changed": changed,
            "operation_lock": lock,
        }

    gate_status = str(
        record.get("status") or ""
    ).strip().upper()

    decision = classify_withdrawal_status(
        gate_status,
        block_number=record.get(
            "block_number"
        ),
    )

    gate_withdrawal_id = str(
        record.get("id")
        or record.get("withdraw_id")
        or ""
    ).strip()

    gate_txid = str(
        record.get("txid")
        or ""
    ).strip()

    fail_reason = str(
        record.get("fail_reason")
        or ""
    ).strip()

    audit, reconciliation, event, changed = (
        apply_withdrawal_reconciliation(
            request_id,
            username=username,
            gate_withdraw_order_id=order_id,
            expected_statuses=allowed,
            new_status=(
                decision.request_status
            ),
            outcome=decision.outcome,
            confidence=decision.confidence,
            gate_status=gate_status,
            gate_withdrawal_id=(
                gate_withdrawal_id
            ),
            gate_txid=gate_txid,
            summary=decision.summary,
            details={
                "gate_record": (
                    _record_details(record)
                ),
                "automatic_retry_allowed": False,
                "ownership_settlement_performed": (
                    False
                ),
            },
            # Finding the exact Gate record proves that
            # the withdrawal submission existed even if
            # the process died before setting this flag.
            write_performed=True,
            error=(
                fail_reason
                if decision.request_status
                == "withdrawal_failed"
                else ""
            ),
            completed=(
                decision.request_status
                == "withdrawal_failed"
            ),
        )
    )

    lock_released = False

    if decision.request_status == (
        "withdrawal_failed"
    ):
        lock_released = (
            release_withdrawal_lock(
                custody_account_id=(
                    row[
                        "custody_account_id"
                    ]
                ),
                currency=row["currency"],
                owner_request_id=request_id,
            )
        )

    return {
        "status": decision.request_status,
        "gate_read_performed": True,
        "gate_write_performed": False,
        "requires_reconciliation": (
            decision.requires_reconciliation
        ),
        "automatic_retry_allowed": False,
        "definitive_success": (
            decision.success
            and decision.terminal
        ),
        "ownership_settlement_performed": False,
        "lock_released": lock_released,
        "audit": audit,
        "reconciliation": reconciliation,
        "event": event,
        "state_changed": changed,
        "operation_lock": (
            get_withdrawal_lock_for_request(
                request_id
            )
        ),
    }
