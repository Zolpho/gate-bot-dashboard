from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from .db import session_scope, utcnow
from .models import (
    TreasuryWithdrawalDestination,
    TreasuryWithdrawalDestinationEvent,
)


DESTINATION_STATUSES = {
    "candidate",
    "pending_verification",
    "approved",
    "revoked",
}

_OWNER_RE = re.compile(
    r"^[a-z0-9][a-z0-9_-]{0,63}$"
)
_CURRENCY_RE = re.compile(
    r"^[A-Z0-9_]{1,20}$"
)
_CHAIN_RE = re.compile(
    r"^[A-Z0-9._-]{1,64}$"
)


class TreasuryWithdrawalDestinationError(
    RuntimeError
):
    pass


def _owner(value: str) -> str:
    result = str(value or "").strip().lower()

    if not _OWNER_RE.fullmatch(result):
        raise TreasuryWithdrawalDestinationError(
            "Invalid destination owner account"
        )

    return result


def _currency(value: str) -> str:
    result = str(value or "").strip().upper()

    if not _CURRENCY_RE.fullmatch(result):
        raise TreasuryWithdrawalDestinationError(
            "Invalid destination currency"
        )

    return result


def _chain(value: str) -> str:
    result = str(value or "").strip().upper()

    if not _CHAIN_RE.fullmatch(result):
        raise TreasuryWithdrawalDestinationError(
            "Invalid destination chain"
        )

    return result


def _address(value: str) -> str:
    result = str(value or "").strip()

    if not result:
        raise TreasuryWithdrawalDestinationError(
            "Withdrawal destination address is required"
        )

    if len(result) > 512:
        raise TreasuryWithdrawalDestinationError(
            "Withdrawal destination address is too long"
        )

    if any(ch.isspace() for ch in result):
        raise TreasuryWithdrawalDestinationError(
            "Withdrawal destination address cannot "
            "contain whitespace"
        )

    return result


def _memo(value: str) -> str:
    result = str(value or "").strip()

    if len(result) > 512:
        raise TreasuryWithdrawalDestinationError(
            "Withdrawal destination memo is too long"
        )

    if any(
        ord(ch) < 32
        for ch in result
        if ch not in {"\t"}
    ):
        raise TreasuryWithdrawalDestinationError(
            "Withdrawal destination memo contains "
            "control characters"
        )

    return result


def _label(value: str) -> str:
    result = str(value or "").strip()

    if len(result) > 128:
        raise TreasuryWithdrawalDestinationError(
            "Withdrawal destination label is too long"
        )

    return result


def _reason(value: str) -> str:
    result = str(value or "").strip()

    if len(result) < 20:
        raise TreasuryWithdrawalDestinationError(
            "Destination security decisions require "
            "a reason of at least 20 characters"
        )

    if len(result) > 1000:
        raise TreasuryWithdrawalDestinationError(
            "Destination security decision reason "
            "is too long"
        )

    return result


def _snapshot(
    row: TreasuryWithdrawalDestination,
) -> dict[str, Any]:
    return {
        "destination_id": row.destination_id,
        "owner_account_id": row.owner_account_id,
        "currency": row.currency,
        "chain": row.chain,
        "address": row.address,
        "memo": row.memo,
        "label": row.label,
        "status": row.status,
        "source": row.source,
        "verification_method": (
            row.verification_method
        ),
        "created_by": row.created_by,
        "approved_by": row.approved_by,
        "approved_at": (
            row.approved_at.isoformat()
            if row.approved_at
            else None
        ),
        "revoked_by": row.revoked_by,
        "revoked_at": (
            row.revoked_at.isoformat()
            if row.revoked_at
            else None
        ),
        "created_at": (
            row.created_at.isoformat()
            if row.created_at
            else None
        ),
        "updated_at": (
            row.updated_at.isoformat()
            if row.updated_at
            else None
        ),
    }


def _event_snapshot(
    row: TreasuryWithdrawalDestinationEvent,
) -> dict[str, Any]:
    try:
        metadata = json.loads(
            row.metadata_json or "{}"
        )
    except Exception:
        metadata = {}

    return {
        "id": row.id,
        "destination_id": row.destination_id,
        "owner_account_id": row.owner_account_id,
        "username": row.username,
        "action": row.action,
        "from_status": row.from_status,
        "to_status": row.to_status,
        "reason": row.reason,
        "metadata": metadata,
        "created_at": (
            row.created_at.isoformat()
            if row.created_at
            else None
        ),
    }


def _new_event(
    *,
    destination: TreasuryWithdrawalDestination,
    username: str,
    action: str,
    from_status: str,
    to_status: str,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> TreasuryWithdrawalDestinationEvent:
    return TreasuryWithdrawalDestinationEvent(
        destination_id=destination.destination_id,
        owner_account_id=(
            destination.owner_account_id
        ),
        username=username,
        action=action,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        metadata_json=json.dumps(
            metadata or {},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ),
    )


def create_candidate_destination(
    *,
    owner_account_id: str,
    currency: str,
    chain: str,
    address: str,
    memo: str,
    label: str,
    username: str,
) -> dict[str, Any]:
    owner = _owner(owner_account_id)
    symbol = _currency(currency)
    network = _chain(chain)
    destination_address = _address(address)
    destination_memo = _memo(memo)
    destination_label = _label(label)

    with session_scope() as db:
        existing = db.scalar(
            select(
                TreasuryWithdrawalDestination
            ).where(
                TreasuryWithdrawalDestination
                .owner_account_id
                == owner,
                TreasuryWithdrawalDestination
                .currency
                == symbol,
                TreasuryWithdrawalDestination
                .chain
                == network,
                TreasuryWithdrawalDestination
                .address
                == destination_address,
                TreasuryWithdrawalDestination
                .memo
                == destination_memo,
            )
        )

        if existing is not None:
            if existing.status == "revoked":
                raise (
                    TreasuryWithdrawalDestinationError(
                        "This exact withdrawal destination "
                        "was revoked and cannot be "
                        "recreated automatically"
                    )
                )

            return {
                "created": False,
                "item": _snapshot(existing),
            }

        row = TreasuryWithdrawalDestination(
            destination_id=(
                "wd_" + uuid4().hex
            ),
            owner_account_id=owner,
            currency=symbol,
            chain=network,
            address=destination_address,
            memo=destination_memo,
            label=destination_label,
            status="candidate",
            source="manual",
            verification_method="unverified",
            created_by=username,
        )

        db.add(row)
        db.flush()

        event = _new_event(
            destination=row,
            username=username,
            action="created",
            from_status="",
            to_status="candidate",
            reason=(
                "Manual withdrawal destination "
                "candidate created."
            ),
            metadata={
                "source": "manual",
            },
        )

        db.add(event)
        db.flush()

        return {
            "created": True,
            "item": _snapshot(row),
            "event": _event_snapshot(event),
        }


def list_destinations(
    *,
    owner_account_ids: set[str] | None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    selected_status = (
        str(status or "").strip().lower()
    )

    if (
        selected_status
        and selected_status
        not in DESTINATION_STATUSES
    ):
        raise TreasuryWithdrawalDestinationError(
            "Invalid withdrawal destination status"
        )

    with session_scope() as db:
        query = select(
            TreasuryWithdrawalDestination
        )

        if owner_account_ids is not None:
            normalized = {
                _owner(item)
                for item in owner_account_ids
            }

            if not normalized:
                return []

            query = query.where(
                TreasuryWithdrawalDestination
                .owner_account_id
                .in_(sorted(normalized))
            )

        if selected_status:
            query = query.where(
                TreasuryWithdrawalDestination.status
                == selected_status
            )

        rows = db.scalars(
            query.order_by(
                TreasuryWithdrawalDestination
                .created_at.desc(),
                TreasuryWithdrawalDestination
                .id.desc(),
            ).limit(
                max(1, min(int(limit), 500))
            )
        ).all()

        return [
            _snapshot(row)
            for row in rows
        ]


def get_destination(
    destination_id: str,
) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryWithdrawalDestination
            ).where(
                TreasuryWithdrawalDestination
                .destination_id
                == destination_id
            )
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def list_destination_events(
    destination_id: str,
) -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.scalars(
            select(
                TreasuryWithdrawalDestinationEvent
            )
            .where(
                TreasuryWithdrawalDestinationEvent
                .destination_id
                == destination_id
            )
            .order_by(
                TreasuryWithdrawalDestinationEvent
                .created_at.asc(),
                TreasuryWithdrawalDestinationEvent
                .id.asc(),
            )
        ).all()

        return [
            _event_snapshot(row)
            for row in rows
        ]


def approve_destination(
    *,
    destination_id: str,
    username: str,
    reason: str,
) -> dict[str, Any]:
    decision_reason = _reason(reason)

    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryWithdrawalDestination
            ).where(
                TreasuryWithdrawalDestination
                .destination_id
                == destination_id
            )
        )

        if row is None:
            raise TreasuryWithdrawalDestinationError(
                "Withdrawal destination not found"
            )

        prior = str(
            row.status or ""
        ).lower()

        if prior == "approved":
            return {
                "changed": False,
                "item": _snapshot(row),
            }

        if prior == "revoked":
            raise TreasuryWithdrawalDestinationError(
                "A revoked withdrawal destination "
                "cannot be approved"
            )

        if prior not in {
            "candidate",
            "pending_verification",
        }:
            raise TreasuryWithdrawalDestinationError(
                "Withdrawal destination is not in an "
                "approvable state"
            )

        row.status = "approved"
        row.verification_method = (
            "manual_admin_approval"
        )
        row.approved_by = username
        row.approved_at = utcnow()
        row.updated_at = utcnow()

        event = _new_event(
            destination=row,
            username=username,
            action="approved",
            from_status=prior,
            to_status="approved",
            reason=decision_reason,
            metadata={
                "verification_method": (
                    "manual_admin_approval"
                ),
            },
        )

        db.add(event)
        db.flush()

        return {
            "changed": True,
            "item": _snapshot(row),
            "event": _event_snapshot(event),
        }


def revoke_destination(
    *,
    destination_id: str,
    username: str,
    reason: str,
) -> dict[str, Any]:
    decision_reason = _reason(reason)

    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryWithdrawalDestination
            ).where(
                TreasuryWithdrawalDestination
                .destination_id
                == destination_id
            )
        )

        if row is None:
            raise TreasuryWithdrawalDestinationError(
                "Withdrawal destination not found"
            )

        prior = str(
            row.status or ""
        ).lower()

        if prior == "revoked":
            return {
                "changed": False,
                "item": _snapshot(row),
            }

        if prior not in {
            "candidate",
            "pending_verification",
            "approved",
        }:
            raise TreasuryWithdrawalDestinationError(
                "Withdrawal destination is not in a "
                "revocable state"
            )

        row.status = "revoked"
        row.revoked_by = username
        row.revoked_at = utcnow()
        row.updated_at = utcnow()

        event = _new_event(
            destination=row,
            username=username,
            action="revoked",
            from_status=prior,
            to_status="revoked",
            reason=decision_reason,
        )

        db.add(event)
        db.flush()

        return {
            "changed": True,
            "item": _snapshot(row),
            "event": _event_snapshot(event),
        }
