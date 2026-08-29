from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select, text

from .accounts import GateAccountConfig
from .config import Settings
from .db import SessionLocal, engine, utcnow
from .gate_client import GateClient
from .models import (
    TreasuryOwnershipLedgerEntry,
    TreasuryWithdrawalRequest,
    TreasuryWithdrawalRequestEvent,
)
from .treasury_withdrawal_audit import (
    get_withdrawal_request,
)
from .treasury_withdrawal_execution import (
    TreasuryWithdrawalExecutionError,
    classify_withdrawal_status,
    select_withdrawal_record,
)
from .treasury_withdrawal_locks import (
    get_withdrawal_lock_for_request,
    release_withdrawal_lock,
)
from .treasury_withdrawal_submission import (
    TreasuryWithdrawalSubmissionError,
    _credential_check,
    _record_details,
    withdrawal_record_mismatches,
)


WITHDRAWAL_DEBIT = "withdrawal_debit"


class TreasuryWithdrawalSettlementError(
    RuntimeError
):
    pass


def _decimal(
    value: Any,
) -> Decimal:
    try:
        result = Decimal(
            str(value)
        )
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as exc:
        raise TreasuryWithdrawalSettlementError(
            "Invalid settlement decimal value"
        ) from exc

    if not result.is_finite():
        raise TreasuryWithdrawalSettlementError(
            "Settlement decimal must be finite"
        )

    return result


def _decimal_text(
    value: Decimal,
) -> str:
    text_value = format(value, "f")

    if "." in text_value:
        text_value = (
            text_value
            .rstrip("0")
            .rstrip(".")
        )

    return text_value or "0"


def _canonical_json(
    value: Any,
) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def withdrawal_debit_event_id(
    request_id: str,
) -> str:
    normalized = str(
        request_id or ""
    ).strip()

    if not normalized:
        raise TreasuryWithdrawalSettlementError(
            "Withdrawal request ID is required"
        )

    return (
        "withdrawal-debit:"
        + normalized
    )


def _positive_block_number(
    value: Any,
) -> int:
    try:
        block = int(
            str(value or "0").strip()
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise TreasuryWithdrawalSettlementError(
            "Gate block number is invalid"
        ) from exc

    if block <= 0:
        raise TreasuryWithdrawalSettlementError(
            "Gate withdrawal is not "
            "definitively on-chain"
        )

    return block


def _settlement_values(
    row: TreasuryWithdrawalRequest,
    gate_record: dict[str, Any],
) -> tuple[
    Decimal,
    Decimal,
    int,
]:
    if row.status not in {
        "withdrawal_done_unsettled",
        "withdrawal_settled",
    }:
        raise TreasuryWithdrawalSettlementError(
            "Withdrawal is not in a "
            "settleable state"
        )

    if bool(row.simulation):
        raise TreasuryWithdrawalSettlementError(
            "Simulation withdrawal cannot settle"
        )

    if not bool(row.write_performed):
        raise TreasuryWithdrawalSettlementError(
            "Withdrawal has no proven Gate write"
        )

    if (
        str(row.gate_status or "")
        .strip()
        .upper()
        != "DONE"
    ):
        raise TreasuryWithdrawalSettlementError(
            "Persisted Gate status is not DONE"
        )

    if not isinstance(gate_record, dict):
        raise TreasuryWithdrawalSettlementError(
            "Gate withdrawal record is missing"
        )

    if (
        str(
            gate_record.get("status")
            or ""
        )
        .strip()
        .upper()
        != "DONE"
    ):
        raise TreasuryWithdrawalSettlementError(
            "Gate withdrawal record is not DONE"
        )

    block_number = (
        _positive_block_number(
            gate_record.get(
                "block_number"
            )
        )
    )

    persisted_order_id = str(
        row.gate_withdraw_order_id
        or ""
    ).strip()

    record_order_id = str(
        gate_record.get(
            "withdraw_order_id"
        )
        or ""
    ).strip()

    if (
        not persisted_order_id
        or record_order_id
        != persisted_order_id
    ):
        raise TreasuryWithdrawalSettlementError(
            "Gate withdrawal order ID mismatch"
        )

    persisted_withdrawal_id = str(
        row.gate_withdrawal_id
        or ""
    ).strip()

    record_withdrawal_id = str(
        gate_record.get("id")
        or gate_record.get(
            "withdraw_id"
        )
        or ""
    ).strip()

    if (
        not persisted_withdrawal_id
        or record_withdrawal_id
        != persisted_withdrawal_id
    ):
        raise TreasuryWithdrawalSettlementError(
            "Gate withdrawal ID mismatch"
        )

    persisted_txid = str(
        row.gate_txid
        or ""
    ).strip()

    record_txid = str(
        gate_record.get("txid")
        or ""
    ).strip()

    if (
        not persisted_txid
        or record_txid
        != persisted_txid
    ):
        raise TreasuryWithdrawalSettlementError(
            "Gate withdrawal txid mismatch"
        )

    if (
        str(
            gate_record.get("currency")
            or ""
        )
        .strip()
        .upper()
        != str(row.currency).upper()
    ):
        raise TreasuryWithdrawalSettlementError(
            "Gate withdrawal currency mismatch"
        )

    if (
        str(
            gate_record.get("chain")
            or ""
        )
        .strip()
        .upper()
        != str(row.chain).upper()
    ):
        raise TreasuryWithdrawalSettlementError(
            "Gate withdrawal chain mismatch"
        )

    record_amount = _decimal(
        gate_record.get("amount")
    )

    request_amount = _decimal(
        row.amount
    )

    if (
        record_amount <= 0
        or record_amount
        != request_amount
    ):
        raise TreasuryWithdrawalSettlementError(
            "Gate withdrawal amount mismatch"
        )

    record_fee = _decimal(
        gate_record.get("fee")
        or "0"
    )

    if record_fee < 0:
        raise TreasuryWithdrawalSettlementError(
            "Gate withdrawal fee is invalid"
        )

    return (
        record_amount,
        record_fee,
        block_number,
    )


def apply_withdrawal_ownership_settlement(
    *,
    request_id: str,
    username: str,
    gate_record: dict[str, Any],
) -> dict[str, Any]:
    """
    Atomically:
      - verify definitive Gate withdrawal evidence,
      - append exactly one withdrawal ownership debit,
      - move withdrawal_done_unsettled -> withdrawal_settled.

    Gate record amount is the ownership debit basis.
    Gate fee is retained as evidence but is NOT added
    a second time to the ledger debit.

    This function performs no Gate API request/write.
    """

    session = SessionLocal()

    try:
        if engine.dialect.name == "sqlite":
            session.execute(
                text("BEGIN IMMEDIATE")
            )

        row = session.scalar(
            select(
                TreasuryWithdrawalRequest
            ).where(
                TreasuryWithdrawalRequest
                .request_id
                == request_id
            )
        )

        if row is None:
            raise TreasuryWithdrawalSettlementError(
                "Withdrawal request not found"
            )

        (
            settlement_amount,
            gate_fee,
            block_number,
        ) = _settlement_values(
            row,
            gate_record,
        )

        event_id = (
            withdrawal_debit_event_id(
                row.request_id
            )
        )

        existing = session.scalar(
            select(
                TreasuryOwnershipLedgerEntry
            ).where(
                TreasuryOwnershipLedgerEntry
                .event_id
                == event_id
            )
        )

        expected_delta = (
            -settlement_amount
        )

        if existing is not None:
            if (
                existing.owner_account_id
                != row.owner_account_id
                or existing.custody_account_id
                != row.custody_account_id
                or existing.currency
                != row.currency
                or Decimal(
                    existing.delta_amount
                )
                != expected_delta
                or existing.entry_type
                != WITHDRAWAL_DEBIT
                or existing.source_request_id
                != row.request_id
            ):
                raise TreasuryWithdrawalSettlementError(
                    "Withdrawal ownership ledger "
                    "event conflicts with expected "
                    "settlement"
                )

        ownership_rows = session.scalars(
            select(
                TreasuryOwnershipLedgerEntry
            ).where(
                TreasuryOwnershipLedgerEntry
                .owner_account_id
                == row.owner_account_id,
                TreasuryOwnershipLedgerEntry
                .custody_account_id
                == row.custody_account_id,
                TreasuryOwnershipLedgerEntry
                .currency
                == row.currency,
            )
        ).all()

        ownership_current = sum(
            (
                Decimal(
                    item.delta_amount
                )
                for item in ownership_rows
            ),
            Decimal("0"),
        )

        if existing is not None:
            # Debit already exists. Current ownership
            # already reflects settlement.
            ownership_before = (
                ownership_current
                + settlement_amount
            )

            ownership_after = (
                ownership_current
            )

        else:
            ownership_before = (
                ownership_current
            )

            if (
                ownership_before
                < settlement_amount
            ):
                raise TreasuryWithdrawalSettlementError(
                    "Owner has insufficient "
                    "main-held ownership for "
                    "withdrawal settlement"
                )

            ownership_after = (
                ownership_before
                - settlement_amount
            )

            entry = (
                TreasuryOwnershipLedgerEntry(
                    event_id=event_id,
                    owner_account_id=(
                        row.owner_account_id
                    ),
                    custody_account_id=(
                        row.custody_account_id
                    ),
                    currency=row.currency,
                    delta_amount=(
                        expected_delta
                    ),
                    entry_type=(
                        WITHDRAWAL_DEBIT
                    ),
                    source_request_id=(
                        row.request_id
                    ),
                    reason=(
                        "Definitive completed "
                        "external Gate withdrawal."
                    ),
                    metadata_json=(
                        _canonical_json(
                            {
                                "source": (
                                    "gate_done_"
                                    "withdrawal"
                                ),
                                "settlement_basis": (
                                    "gate_record_"
                                    "amount"
                                ),
                                "gate_record_amount": (
                                    _decimal_text(
                                        settlement_amount
                                    )
                                ),
                                "gate_record_fee": (
                                    _decimal_text(
                                        gate_fee
                                    )
                                ),
                                "gate_withdraw_order_id": (
                                    row
                                    .gate_withdraw_order_id
                                ),
                                "gate_withdrawal_id": (
                                    row
                                    .gate_withdrawal_id
                                ),
                                "gate_txid": (
                                    row.gate_txid
                                ),
                                "gate_status": "DONE",
                                "block_number": (
                                    str(
                                        block_number
                                    )
                                ),
                            }
                        )
                    ),
                    created_at=utcnow(),
                )
            )

            session.add(entry)

        changed = (
            row.status
            != "withdrawal_settled"
        )

        if changed:
            old_status = row.status

            row.status = (
                "withdrawal_settled"
            )
            row.error = ""
            row.simulation = False
            row.completed_at = utcnow()

            event = (
                TreasuryWithdrawalRequestEvent(
                    request_id=(
                        row.request_id
                    ),
                    owner_account_id=(
                        row.owner_account_id
                    ),
                    username=username,
                    action=(
                        "withdrawal_settled"
                    ),
                    from_status=old_status,
                    to_status=(
                        "withdrawal_settled"
                    ),
                    details_json=(
                        _canonical_json(
                            {
                                "ownership_settlement_performed": (
                                    True
                                ),
                                "settlement_basis": (
                                    "gate_record_"
                                    "amount"
                                ),
                                "settlement_amount": (
                                    _decimal_text(
                                        settlement_amount
                                    )
                                ),
                                "gate_fee": (
                                    _decimal_text(
                                        gate_fee
                                    )
                                ),
                                "ownership_before": (
                                    _decimal_text(
                                        ownership_before
                                    )
                                ),
                                "ownership_after": (
                                    _decimal_text(
                                        ownership_after
                                    )
                                ),
                                "gate_withdraw_order_id": (
                                    row
                                    .gate_withdraw_order_id
                                ),
                                "gate_withdrawal_id": (
                                    row
                                    .gate_withdrawal_id
                                ),
                                "gate_txid": (
                                    row.gate_txid
                                ),
                                "block_number": (
                                    str(
                                        block_number
                                    )
                                ),
                                "gate_write_performed": (
                                    False
                                ),
                            }
                        )
                    ),
                )
            )

            session.add(event)

        session.flush()
        session.commit()

        return {
            "status": "withdrawal_settled",
            "state_changed": changed,
            "idempotent_replay": (
                not changed
            ),
            "ownership_settlement_performed": (
                existing is None
            ),
            "ownership_ledger_changed": (
                existing is None
            ),
            "settlement_amount": (
                _decimal_text(
                    settlement_amount
                )
            ),
            "gate_fee": (
                _decimal_text(
                    gate_fee
                )
            ),
            "ownership_before": (
                _decimal_text(
                    ownership_before
                )
            ),
            "ownership_after": (
                _decimal_text(
                    ownership_after
                )
            ),
            "ledger_event_id": event_id,
            "gate_read_performed": False,
            "gate_write_performed": False,
        }

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()



def withdrawal_settlement_action_policy(
    *,
    status: Any,
    withdrawals_live_armed: bool,
) -> dict[str, bool]:
    """
    Describe whether the settlement endpoint represents
    a normal accounting action or only an idempotent
    crash-recovery replay.

    A fully settled withdrawal must never be advertised
    as a new settlement action.
    """

    normalized = str(
        status or ""
    ).strip().lower()

    pending = (
        normalized
        == "withdrawal_done_unsettled"
    )

    settled = (
        normalized
        == "withdrawal_settled"
    )

    fail_closed = not bool(
        withdrawals_live_armed
    )

    return {
        "settlement_allowed": bool(
            pending
            and fail_closed
        ),
        "idempotent_replay_only": settled,
        "idempotent_replay_allowed": bool(
            settled
            and fail_closed
        ),
    }


def withdrawal_settlement_confirmation_text(
    request: dict[str, Any],
) -> str:
    request_id = str(
        request.get("request_id") or ""
    ).strip()

    owner = str(
        request.get("owner_account_id") or ""
    ).strip().lower()

    currency = str(
        request.get("currency") or ""
    ).strip().upper()

    amount = str(
        request.get("amount") or ""
    ).strip()

    order_id = str(
        request.get(
            "gate_withdraw_order_id"
        )
        or ""
    ).strip()

    if (
        not request_id
        or not owner
        or not currency
        or not amount
        or not order_id
    ):
        raise TreasuryWithdrawalSettlementError(
            "Withdrawal settlement confirmation "
            "cannot be built from incomplete audit data"
        )

    result = (
        f"SETTLE WITHDRAWAL {request_id} "
        f"{owner} {currency} {amount} "
        f"{order_id}"
    )

    if len(result) > 500:
        raise TreasuryWithdrawalSettlementError(
            "Withdrawal settlement confirmation "
            "exceeds 500 characters"
        )

    return result


def _validate_settlement_lock(
    row: dict[str, Any],
) -> dict[str, Any]:
    lock = get_withdrawal_lock_for_request(
        row["request_id"]
    )

    if lock is None:
        raise TreasuryWithdrawalSettlementError(
            "Definitive completed withdrawal "
            "has no custody operation lock"
        )

    if (
        str(
            lock.get("owner_account_id")
            or ""
        ).strip().lower()
        != str(
            row.get("owner_account_id")
            or ""
        ).strip().lower()
        or str(
            lock.get("custody_account_id")
            or ""
        ).strip().lower()
        != str(
            row.get("custody_account_id")
            or ""
        ).strip().lower()
        or str(
            lock.get("currency")
            or ""
        ).strip().upper()
        != str(
            row.get("currency")
            or ""
        ).strip().upper()
        or str(
            lock.get("owner_request_id")
            or ""
        )
        != str(
            row.get("request_id")
            or ""
        )
    ):
        raise TreasuryWithdrawalSettlementError(
            "Withdrawal custody operation lock "
            "does not match the settlement request"
        )

    return lock


async def settle_withdrawal_from_gate(
    *,
    settings: Settings,
    request_id: str,
    username: str,
    treasury_account: (
        GateAccountConfig | None
    ),
) -> dict[str, Any]:
    """
    Perform the final GET-only Gate verification and
    local ownership settlement.

    This function never submits a Gate withdrawal and
    never performs any Gate write.
    """

    if settings.treasury_withdrawals_live_armed:
        raise TreasuryWithdrawalSettlementError(
            "Withdrawal settlement requires live "
            "withdrawals to be disarmed"
        )

    row = get_withdrawal_request(
        request_id
    )

    if row is None:
        raise TreasuryWithdrawalSettlementError(
            "Withdrawal request not found"
        )

    # Crash-recovery / idempotent replay:
    #
    # The atomic ledger/status transaction may have
    # committed immediately before the process died while
    # releasing the separate custody lock.
    if (
        row["status"]
        == "withdrawal_settled"
    ):
        released = release_withdrawal_lock(
            custody_account_id=(
                row["custody_account_id"]
            ),
            currency=row["currency"],
            owner_request_id=request_id,
        )

        remaining_lock = (
            get_withdrawal_lock_for_request(
                request_id
            )
        )

        if remaining_lock is not None:
            raise TreasuryWithdrawalSettlementError(
                "Withdrawal is already settled but "
                "its custody lock could not be released"
            )

        return {
            "status": "withdrawal_settled",
            "state_changed": False,
            "idempotent_replay": True,
            "ownership_settlement_performed": False,
            "ownership_ledger_changed": False,
            "settlement_amount": str(
                row["amount"]
            ),
            "gate_read_performed": False,
            "gate_write_performed": False,
            "lock_released": released,
            "operation_lock": None,
            "gate_record": None,
        }

    if (
        row["status"]
        != "withdrawal_done_unsettled"
    ):
        raise TreasuryWithdrawalSettlementError(
            "Withdrawal is not in "
            "withdrawal_done_unsettled state"
        )

    _validate_settlement_lock(
        row
    )

    if treasury_account is None:
        raise TreasuryWithdrawalSettlementError(
            "Treasury credential is required "
            "for settlement verification"
        )

    try:
        _credential_check(
            settings,
            treasury_account,
        )

    except TreasuryWithdrawalSubmissionError as exc:
        raise TreasuryWithdrawalSettlementError(
            str(exc)
        ) from exc

    try:
        async with GateClient(
            settings,
            treasury_account,
        ) as client:
            response = (
                await client.list_withdrawals(
                    currency=row["currency"],
                    withdraw_order_id=(
                        row[
                            "gate_withdraw_order_id"
                        ]
                    ),
                    limit=100,
                    offset=0,
                )
            )

    except Exception:
        # Gate transport/API errors intentionally propagate
        # unchanged so the API layer can distinguish them
        # from local settlement validation errors.
        raise

    try:
        record = select_withdrawal_record(
            response.raw,
            withdraw_order_id=(
                row[
                    "gate_withdraw_order_id"
                ]
            ),
        )

    except TreasuryWithdrawalExecutionError as exc:
        raise TreasuryWithdrawalSettlementError(
            str(exc)
        ) from exc

    if record is None:
        raise TreasuryWithdrawalSettlementError(
            "No exact Gate withdrawal record "
            "matched the persisted withdraw_order_id"
        )

    mismatches = (
        withdrawal_record_mismatches(
            row,
            record,
        )
    )

    if mismatches:
        raise TreasuryWithdrawalSettlementError(
            "Gate withdrawal record mismatches "
            "the immutable local request: "
            + ", ".join(mismatches)
        )

    decision = classify_withdrawal_status(
        record.get("status"),
        block_number=record.get(
            "block_number"
        ),
    )

    if not (
        decision.success
        and decision.terminal
        and decision.request_status
        == "withdrawal_done_unsettled"
    ):
        raise TreasuryWithdrawalSettlementError(
            "Gate withdrawal is not definitively "
            "DONE on-chain"
        )

    settlement = (
        apply_withdrawal_ownership_settlement(
            request_id=request_id,
            username=username,
            gate_record=record,
        )
    )

    # Deliberately separate from the atomic ownership /
    # lifecycle transaction.
    #
    # If the process dies here, replay sees
    # withdrawal_settled and releases only this request's
    # lock without touching the ownership ledger again.
    released = release_withdrawal_lock(
        custody_account_id=(
            row["custody_account_id"]
        ),
        currency=row["currency"],
        owner_request_id=request_id,
    )

    remaining_lock = (
        get_withdrawal_lock_for_request(
            request_id
        )
    )

    if remaining_lock is not None:
        raise TreasuryWithdrawalSettlementError(
            "Withdrawal ownership settlement "
            "committed but its custody lock could "
            "not be released. Replay this exact "
            "settlement operation."
        )

    return {
        **settlement,
        "gate_read_performed": True,
        "gate_write_performed": False,
        "lock_released": released,
        "operation_lock": None,
        "gate_record": _record_details(
            record
        ),
    }
