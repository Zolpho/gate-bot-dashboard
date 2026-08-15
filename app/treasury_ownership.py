from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import session_scope
from .models import (
    TreasuryOwnershipLedgerEntry,
    TreasuryTransferRequest,
)


INTERNAL_TRANSFER_CREDIT = (
    "internal_transfer_credit"
)


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


def _load_json(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return {}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _snapshot(
    row: TreasuryOwnershipLedgerEntry,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "event_id": row.event_id,
        "owner_account_id": row.owner_account_id,
        "custody_account_id": (
            row.custody_account_id
        ),
        "currency": row.currency,
        "delta_amount": _decimal_text(
            Decimal(row.delta_amount)
        ),
        "entry_type": row.entry_type,
        "source_request_id": (
            row.source_request_id or None
        ),
        "reason": row.reason,
        "metadata": _load_json(
            row.metadata_json
        ),
        "created_at": (
            row.created_at.isoformat()
            if row.created_at
            else None
        ),
    }


def internal_transfer_credit_event_id(
    request_id: str,
) -> str:
    return (
        "internal-transfer-credit:"
        + request_id
    )


def _is_successful_internal_transfer(
    row: TreasuryTransferRequest,
) -> bool:
    if str(row.status or "").lower() != "success":
        return False

    if bool(row.simulation):
        return False

    if not bool(row.write_performed):
        return False

    if str(row.direction or "").lower() != "from":
        return False

    if Decimal(row.amount) <= 0:
        return False

    request = _load_json(
        row.request_json or "{}"
    )

    if not isinstance(request, dict):
        return False

    return (
        str(
            request.get("operation") or ""
        ).lower()
        == "subaccount_to_main"
    )


def ensure_internal_transfer_credit_for_row(
    db: Session,
    row: TreasuryTransferRequest,
    *,
    metadata_source: str = "runtime_success",
) -> tuple[
    dict[str, Any] | None,
    bool,
]:
    """
    Ensure exactly one ownership credit exists for a
    definitive successful live internal transfer.

    The caller may use the same DB transaction that marks
    the transfer successful, making financial status and
    ownership accounting atomic.
    """

    if not _is_successful_internal_transfer(row):
        return None, False

    event_id = internal_transfer_credit_event_id(
        row.request_id
    )

    existing = db.scalar(
        select(
            TreasuryOwnershipLedgerEntry
        ).where(
            TreasuryOwnershipLedgerEntry.event_id
            == event_id
        )
    )

    expected_amount = Decimal(row.amount)

    if existing is not None:
        if (
            existing.owner_account_id
            != row.source_account_id
            or existing.custody_account_id
            != row.destination_account_id
            or existing.currency
            != row.currency
            or Decimal(existing.delta_amount)
            != expected_amount
            or existing.entry_type
            != INTERNAL_TRANSFER_CREDIT
            or existing.source_request_id
            != row.request_id
        ):
            raise RuntimeError(
                "Treasury ownership ledger event "
                f"conflict for {event_id}"
            )

        return _snapshot(existing), False

    entry = TreasuryOwnershipLedgerEntry(
        event_id=event_id,
        owner_account_id=(
            row.source_account_id
        ),
        custody_account_id=(
            row.destination_account_id
        ),
        currency=row.currency,
        delta_amount=expected_amount,
        entry_type=INTERNAL_TRANSFER_CREDIT,
        source_request_id=row.request_id,
        reason=(
            "Definitive successful "
            "subaccount-to-main Treasury transfer."
        ),
        metadata_json=_canonical_json(
            {
                "source": metadata_source,
                "gate_transfer_id": (
                    row.gate_transfer_id or None
                ),
            }
        ),
        created_at=(
            row.completed_at
            or row.updated_at
            or row.created_at
        ),
    )

    db.add(entry)
    db.flush()

    return _snapshot(entry), True


def backfill_internal_transfer_credits(
) -> dict[str, int]:
    """
    Idempotent repair/backfill.

    This never guesses from Gate balances. It only derives
    ownership from definitive successful local transfer
    audit records.
    """

    created = 0
    existing = 0

    with session_scope() as db:
        rows = db.scalars(
            select(
                TreasuryTransferRequest
            )
            .where(
                TreasuryTransferRequest.status
                == "success"
            )
            .order_by(
                TreasuryTransferRequest.id.asc()
            )
        ).all()

        for row in rows:
            entry, was_created = (
                ensure_internal_transfer_credit_for_row(
                    db,
                    row,
                    metadata_source=(
                        "runtime_backfill"
                    ),
                )
            )

            if entry is None:
                continue

            if was_created:
                created += 1
            else:
                existing += 1

    return {
        "created": created,
        "existing": existing,
    }


def list_ownership_entries(
    *,
    account_ids: set[str] | None = None,
    currency: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    limit = max(
        1,
        min(int(limit), 500),
    )

    if (
        account_ids is not None
        and not account_ids
    ):
        return []

    with session_scope() as db:
        statement = (
            select(
                TreasuryOwnershipLedgerEntry
            )
            .order_by(
                TreasuryOwnershipLedgerEntry
                .created_at.desc(),
                TreasuryOwnershipLedgerEntry
                .id.desc(),
            )
            .limit(limit)
        )

        if account_ids is not None:
            statement = statement.where(
                TreasuryOwnershipLedgerEntry
                .owner_account_id.in_(
                    sorted(account_ids)
                )
            )

        if currency:
            statement = statement.where(
                TreasuryOwnershipLedgerEntry
                .currency
                == currency.strip().upper()
            )

        rows = db.scalars(
            statement
        ).all()

        return [
            _snapshot(row)
            for row in rows
        ]


def ownership_balances(
    *,
    account_ids: set[str] | None = None,
) -> list[dict[str, str]]:
    if (
        account_ids is not None
        and not account_ids
    ):
        return []

    # Aggregate in Python using Decimal rather than relying
    # on SQLite floating-point SUM behaviour.
    with session_scope() as db:
        statement = select(
            TreasuryOwnershipLedgerEntry
        )

        if account_ids is not None:
            statement = statement.where(
                TreasuryOwnershipLedgerEntry
                .owner_account_id.in_(
                    sorted(account_ids)
                )
            )

        rows = db.scalars(
            statement
        ).all()

    totals: dict[
        tuple[str, str, str],
        Decimal,
    ] = {}

    for row in rows:
        key = (
            row.owner_account_id,
            row.custody_account_id,
            row.currency,
        )

        totals[key] = (
            totals.get(key, Decimal("0"))
            + Decimal(row.delta_amount)
        )

    result = []

    for (
        owner_account_id,
        custody_account_id,
        currency,
    ), amount in sorted(totals.items()):
        result.append(
            {
                "owner_account_id": (
                    owner_account_id
                ),
                "custody_account_id": (
                    custody_account_id
                ),
                "currency": currency,
                "main_held_amount": (
                    _decimal_text(amount)
                ),
            }
        )

    return result


def ownership_amount(
    *,
    owner_account_id: str,
    custody_account_id: str,
    currency: str,
) -> Decimal:
    owner = owner_account_id.strip().lower()
    custody = custody_account_id.strip().lower()
    symbol = currency.strip().upper()

    total = Decimal("0")

    with session_scope() as db:
        rows = db.scalars(
            select(
                TreasuryOwnershipLedgerEntry
            ).where(
                TreasuryOwnershipLedgerEntry
                .owner_account_id
                == owner,
                TreasuryOwnershipLedgerEntry
                .custody_account_id
                == custody,
                TreasuryOwnershipLedgerEntry
                .currency
                == symbol,
            )
        ).all()

        for row in rows:
            total += Decimal(
                row.delta_amount
            )

    return total


def custody_liability_amount(
    *,
    custody_account_id: str,
    currency: str,
) -> Decimal:
    custody = custody_account_id.strip().lower()
    symbol = currency.strip().upper()

    total = Decimal("0")

    with session_scope() as db:
        rows = db.scalars(
            select(
                TreasuryOwnershipLedgerEntry
            ).where(
                TreasuryOwnershipLedgerEntry
                .custody_account_id
                == custody,
                TreasuryOwnershipLedgerEntry
                .currency
                == symbol,
            )
        ).all()

        for row in rows:
            total += Decimal(
                row.delta_amount
            )

    return total
