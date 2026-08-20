from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .db import (
    SessionLocal,
    engine,
    session_scope,
    utcnow,
)
from .models import (
    TreasuryOwnershipLedgerEntry,
    TreasuryTransferOperationLock,
    TreasuryWithdrawalOperationLock,
)

USER_TRANSFER_DEBIT = "user_transfer_debit"
USER_TRANSFER_CREDIT = "user_transfer_credit"


class TreasuryUserTransferError(RuntimeError):
    pass


class TreasuryUserTransferConflict(
    TreasuryUserTransferError
):
    pass


def decimal_text(value: Decimal) -> str:
    text_value = format(value, "f")

    if "." in text_value:
        text_value = (
            text_value.rstrip("0").rstrip(".")
        )

    return text_value or "0"


def validate_user_transfer_amount(
    amount: Decimal,
) -> None:
    if not amount.is_finite() or amount <= 0:
        raise TreasuryUserTransferError(
            "Transfer amount must be greater than zero"
        )

    exponent = amount.as_tuple().exponent

    decimal_places = (
        -exponent
        if exponent < 0
        else 0
    )

    # TREASURY_AMOUNT is Numeric(48, 24).
    if decimal_places > 24:
        raise TreasuryUserTransferError(
            "Transfer amount supports at most "
            "24 decimal places"
        )

    # Numeric(48, 24) permits at most 24 integer digits.
    if amount.adjusted() >= 24:
        raise TreasuryUserTransferError(
            "Transfer amount exceeds Treasury precision"
        )


def user_transfer_confirmation_text(
    *,
    source_account_id: str,
    destination_account_id: str,
    currency: str,
    amount: Decimal,
) -> str:
    return (
        "TRANSFER "
        f"{source_account_id.strip().lower()} "
        f"{decimal_text(amount)} "
        f"{currency.strip().upper()} "
        "TO "
        f"{destination_account_id.strip().lower()}"
    )


def user_transfer_debit_event_id(
    request_id: str,
) -> str:
    return f"user-transfer-debit:{request_id}"


def user_transfer_credit_event_id(
    request_id: str,
) -> str:
    return f"user-transfer-credit:{request_id}"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _load_json(value: str) -> dict[str, Any]:
    try:
        result = json.loads(value or "{}")
    except Exception:
        return {}

    return result if isinstance(result, dict) else {}


def _ownership_amount_in_session(
    db: Session,
    *,
    owner_account_id: str,
    custody_account_id: str,
    currency: str,
) -> Decimal:
    rows = db.scalars(
        select(
            TreasuryOwnershipLedgerEntry
        ).where(
            TreasuryOwnershipLedgerEntry
            .owner_account_id
            == owner_account_id,
            TreasuryOwnershipLedgerEntry
            .custody_account_id
            == custody_account_id,
            TreasuryOwnershipLedgerEntry
            .currency
            == currency,
        )
    ).all()

    total = Decimal("0")

    for row in rows:
        total += Decimal(row.delta_amount)

    return total


def _operation_blockers_in_session(
    db: Session,
    *,
    source_account_id: str,
    custody_account_id: str,
    currency: str,
) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []

    transfer_lock = db.scalar(
        select(
            TreasuryTransferOperationLock
        ).where(
            TreasuryTransferOperationLock
            .source_account_id
            == source_account_id,
            TreasuryTransferOperationLock
            .currency
            == currency,
            TreasuryTransferOperationLock
            .state
            == "held",
        )
    )

    if transfer_lock is not None:
        blockers.append(
            {
                "type": "treasury_transfer",
                "request_id": (
                    transfer_lock.owner_request_id
                ),
            }
        )

    withdrawal_lock = db.scalar(
        select(
            TreasuryWithdrawalOperationLock
        ).where(
            TreasuryWithdrawalOperationLock
            .custody_account_id
            == custody_account_id,
            TreasuryWithdrawalOperationLock
            .currency
            == currency,
            TreasuryWithdrawalOperationLock
            .state
            == "held",
        )
    )

    if withdrawal_lock is not None:
        blockers.append(
            {
                "type": "treasury_withdrawal",
                "request_id": (
                    withdrawal_lock.owner_request_id
                ),
            }
        )

    return blockers


def preview_user_transfer(
    *,
    source_account_id: str,
    destination_account_id: str,
    custody_account_id: str,
    currency: str,
    amount: Decimal,
) -> dict[str, Any]:
    source = source_account_id.strip().lower()
    destination = (
        destination_account_id.strip().lower()
    )
    custody = custody_account_id.strip().lower()
    symbol = currency.strip().upper()

    validate_user_transfer_amount(amount)

    if not source or not destination:
        raise TreasuryUserTransferError(
            "Source and destination are required"
        )

    if source == destination:
        raise TreasuryUserTransferError(
            "Source and destination must be different"
        )

    with session_scope() as db:
        source_before = _ownership_amount_in_session(
            db,
            owner_account_id=source,
            custody_account_id=custody,
            currency=symbol,
        )

        destination_before = (
            _ownership_amount_in_session(
                db,
                owner_account_id=destination,
                custody_account_id=custody,
                currency=symbol,
            )
        )

        operation_blockers = (
            _operation_blockers_in_session(
                db,
                source_account_id=source,
                custody_account_id=custody,
                currency=symbol,
            )
        )

    sufficient = source_before >= amount
    can_transfer = (
        sufficient
        and not operation_blockers
    )

    return {
        "source_account_id": source,
        "destination_account_id": destination,
        "custody_account_id": custody,
        "currency": symbol,
        "amount": decimal_text(amount),
        "source_before": decimal_text(
            source_before
        ),
        "source_after": (
            decimal_text(source_before - amount)
            if sufficient
            else None
        ),
        "destination_before": decimal_text(
            destination_before
        ),
        "destination_after": decimal_text(
            destination_before + amount
        ),
        "sufficient_ownership": sufficient,
        "operation_blockers": operation_blockers,
        "can_transfer": can_transfer,
        "gate_write_required": False,
    }


def _existing_transfer_result(
    *,
    debit: TreasuryOwnershipLedgerEntry,
    credit: TreasuryOwnershipLedgerEntry,
    request_id: str,
    source: str,
    destination: str,
    custody: str,
    symbol: str,
    amount: Decimal,
) -> dict[str, Any]:
    expected = {
        "request_id": request_id,
        "source_account_id": source,
        "destination_account_id": destination,
        "custody_account_id": custody,
        "currency": symbol,
        "amount": decimal_text(amount),
    }

    debit_metadata = _load_json(
        debit.metadata_json
    )
    credit_metadata = _load_json(
        credit.metadata_json
    )

    valid = (
        debit.event_id
        == user_transfer_debit_event_id(request_id)
        and debit.owner_account_id == source
        and debit.custody_account_id == custody
        and debit.currency == symbol
        and Decimal(debit.delta_amount) == -amount
        and debit.entry_type == USER_TRANSFER_DEBIT
        and debit.source_request_id == request_id
        and credit.event_id
        == user_transfer_credit_event_id(request_id)
        and credit.owner_account_id == destination
        and credit.custody_account_id == custody
        and credit.currency == symbol
        and Decimal(credit.delta_amount) == amount
        and credit.entry_type == USER_TRANSFER_CREDIT
        and credit.source_request_id == request_id
    )

    for key, value in expected.items():
        valid = (
            valid
            and debit_metadata.get(key) == value
            and credit_metadata.get(key) == value
        )

    if not valid:
        raise TreasuryUserTransferConflict(
            "User transfer request ID conflicts with "
            "existing ownership ledger evidence"
        )

    return {
        "request_id": request_id,
        "status": "success",
        "idempotent_replay": True,
        "state_changed": False,
        "gate_write_performed": False,
        "source_account_id": source,
        "destination_account_id": destination,
        "custody_account_id": custody,
        "currency": symbol,
        "amount": decimal_text(amount),
        "source_before": debit_metadata.get(
            "source_before"
        ),
        "source_after": debit_metadata.get(
            "source_after"
        ),
        "destination_before": (
            debit_metadata.get(
                "destination_before"
            )
        ),
        "destination_after": (
            debit_metadata.get(
                "destination_after"
            )
        ),
    }


def execute_user_transfer(
    *,
    request_id: str,
    username: str,
    source_account_id: str,
    destination_account_id: str,
    custody_account_id: str,
    currency: str,
    amount: Decimal,
) -> dict[str, Any]:
    request_id = request_id.strip()
    username = username.strip().lower()
    source = source_account_id.strip().lower()
    destination = (
        destination_account_id.strip().lower()
    )
    custody = custody_account_id.strip().lower()
    symbol = currency.strip().upper()

    validate_user_transfer_amount(amount)

    if not request_id:
        raise TreasuryUserTransferError(
            "Request ID is required"
        )

    if not source or not destination:
        raise TreasuryUserTransferError(
            "Source and destination are required"
        )

    if source == destination:
        raise TreasuryUserTransferError(
            "Source and destination must be different"
        )

    debit_event_id = (
        user_transfer_debit_event_id(request_id)
    )

    credit_event_id = (
        user_transfer_credit_event_id(request_id)
    )

    session = SessionLocal()

    try:
        # Serialize the balance check + double-entry write.
        # This prevents two concurrent transfers from both
        # spending the same ownership balance under SQLite.
        if engine.dialect.name == "sqlite":
            session.execute(
                text("BEGIN IMMEDIATE")
            )

        existing_rows = session.scalars(
            select(
                TreasuryOwnershipLedgerEntry
            ).where(
                TreasuryOwnershipLedgerEntry
                .event_id.in_(
                    [
                        debit_event_id,
                        credit_event_id,
                    ]
                )
            )
        ).all()

        if existing_rows:
            by_event = {
                row.event_id: row
                for row in existing_rows
            }

            debit = by_event.get(debit_event_id)
            credit = by_event.get(credit_event_id)

            if debit is None or credit is None:
                raise TreasuryUserTransferConflict(
                    "User transfer has incomplete "
                    "existing ledger evidence"
                )

            result = _existing_transfer_result(
                debit=debit,
                credit=credit,
                request_id=request_id,
                source=source,
                destination=destination,
                custody=custody,
                symbol=symbol,
                amount=amount,
            )

            session.commit()
            return result

        operation_blockers = (
            _operation_blockers_in_session(
                session,
                source_account_id=source,
                custody_account_id=custody,
                currency=symbol,
            )
        )

        if operation_blockers:
            blocker = operation_blockers[0]

            raise TreasuryUserTransferError(
                "User transfer blocked by active "
                "Treasury operation: "
                f"{blocker['type']} "
                f"{blocker['request_id']}"
            )

        source_before = _ownership_amount_in_session(
            session,
            owner_account_id=source,
            custody_account_id=custody,
            currency=symbol,
        )

        if source_before < amount:
            raise TreasuryUserTransferError(
                "Insufficient main-held ownership: "
                f"requested {decimal_text(amount)} "
                f"{symbol}, available "
                f"{decimal_text(source_before)} "
                f"{symbol}"
            )

        destination_before = (
            _ownership_amount_in_session(
                session,
                owner_account_id=destination,
                custody_account_id=custody,
                currency=symbol,
            )
        )

        source_after = source_before - amount
        destination_after = (
            destination_before + amount
        )

        metadata = {
            "operation": "user_ownership_transfer",
            "request_id": request_id,
            "username": username,
            "source_account_id": source,
            "destination_account_id": destination,
            "custody_account_id": custody,
            "currency": symbol,
            "amount": decimal_text(amount),
            "source_before": decimal_text(
                source_before
            ),
            "source_after": decimal_text(
                source_after
            ),
            "destination_before": decimal_text(
                destination_before
            ),
            "destination_after": decimal_text(
                destination_after
            ),
            "gate_write_performed": False,
        }

        now = utcnow()

        debit = TreasuryOwnershipLedgerEntry(
            event_id=debit_event_id,
            owner_account_id=source,
            custody_account_id=custody,
            currency=symbol,
            delta_amount=-amount,
            entry_type=USER_TRANSFER_DEBIT,
            source_request_id=request_id,
            reason=(
                "Dashboard user-to-user economic "
                "ownership transfer debit."
            ),
            metadata_json=_canonical_json(metadata),
            created_at=now,
        )

        credit = TreasuryOwnershipLedgerEntry(
            event_id=credit_event_id,
            owner_account_id=destination,
            custody_account_id=custody,
            currency=symbol,
            delta_amount=amount,
            entry_type=USER_TRANSFER_CREDIT,
            source_request_id=request_id,
            reason=(
                "Dashboard user-to-user economic "
                "ownership transfer credit."
            ),
            metadata_json=_canonical_json(metadata),
            created_at=now,
        )

        session.add(debit)
        session.add(credit)
        session.flush()
        session.commit()

        return {
            "request_id": request_id,
            "status": "success",
            "idempotent_replay": False,
            "state_changed": True,
            "gate_write_performed": False,
            "source_account_id": source,
            "destination_account_id": destination,
            "custody_account_id": custody,
            "currency": symbol,
            "amount": decimal_text(amount),
            "source_before": decimal_text(
                source_before
            ),
            "source_after": decimal_text(
                source_after
            ),
            "destination_before": decimal_text(
                destination_before
            ),
            "destination_after": decimal_text(
                destination_after
            ),
        }

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()
