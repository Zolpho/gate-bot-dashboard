from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from .db import session_scope, utcnow
from .models import (
    TreasuryWithdrawalRecipient,
    TreasuryWithdrawalRecipientEvent,
)


RECIPIENT_STATUSES = {
    "active",
    "archived",
}

_OWNER_RE = re.compile(
    r"^[a-z0-9][a-z0-9_-]{0,63}$"
)


class TreasuryWithdrawalRecipientError(
    RuntimeError
):
    pass


def _owner(value: str) -> str:
    result = str(value or "").strip().lower()

    if not _OWNER_RE.fullmatch(result):
        raise TreasuryWithdrawalRecipientError(
            "Invalid withdrawal recipient owner account"
        )

    return result


def _address(value: str) -> str:
    result = str(value or "").strip()

    if not result:
        raise TreasuryWithdrawalRecipientError(
            "Withdrawal recipient address is required"
        )

    if len(result) > 512:
        raise TreasuryWithdrawalRecipientError(
            "Withdrawal recipient address is too long"
        )

    if any(
        char.isspace()
        for char in result
    ):
        raise TreasuryWithdrawalRecipientError(
            "Withdrawal recipient address cannot "
            "contain whitespace"
        )

    return result


def _address_key(value: str) -> str:
    address = _address(value)

    if (
        len(address) == 42
        and address.startswith(
            (
                "0x",
                "0X",
            )
        )
    ):
        payload = address[2:]

        if all(
            char
            in "0123456789abcdefABCDEF"
            for char in payload
        ):
            return (
                "evm:"
                + address.lower()
            )

    return (
        "exact:"
        + address
    )


def recipient_address_identity(
    value: str,
) -> str:
    """
    Return the canonical address identity used by
    the generic withdrawal-recipient address book.

    Destination bridging must use this function rather
    than independently reimplementing EVM normalization.
    """
    return _address_key(
        value
    )


def _label(value: str) -> str:
    result = str(value or "").strip()

    if len(result) > 128:
        raise TreasuryWithdrawalRecipientError(
            "Withdrawal recipient label is too long"
        )

    return result


def _reason(
    value: str,
    *,
    default: str,
) -> str:
    result = str(value or "").strip()

    if not result:
        result = default

    if len(result) > 1000:
        raise TreasuryWithdrawalRecipientError(
            "Withdrawal recipient audit reason "
            "is too long"
        )

    return result


def _iso_utc(
    value: datetime | None,
) -> str | None:
    """
    Serialize SQLite-backed timestamps deterministically.

    SQLite DateTime(timezone=True) round-trips as a naive
    datetime. Project timestamps are UTC, so restore UTC
    when tzinfo is absent and normalize aware values to UTC.
    """
    if value is None:
        return None

    if value.tzinfo is None:
        normalized = value.replace(
            tzinfo=timezone.utc
        )
    else:
        normalized = value.astimezone(
            timezone.utc
        )

    return normalized.isoformat()


def _snapshot(
    row: TreasuryWithdrawalRecipient,
) -> dict[str, Any]:
    return {
        "recipient_id": row.recipient_id,
        "owner_account_id": (
            row.owner_account_id
        ),
        "address": row.address,
        "label": row.label,
        "status": row.status,
        "created_by": row.created_by,
        "archived_by": row.archived_by,
        "archived_at": _iso_utc(
            row.archived_at
        ),
        "created_at": _iso_utc(
            row.created_at
        ),
        "updated_at": _iso_utc(
            row.updated_at
        ),
    }


def _event_snapshot(
    row: TreasuryWithdrawalRecipientEvent,
) -> dict[str, Any]:
    try:
        metadata = json.loads(
            row.metadata_json or "{}"
        )
    except Exception:
        metadata = {}

    return {
        "id": row.id,
        "recipient_id": row.recipient_id,
        "owner_account_id": (
            row.owner_account_id
        ),
        "username": row.username,
        "action": row.action,
        "from_status": row.from_status,
        "to_status": row.to_status,
        "reason": row.reason,
        "metadata": metadata,
        "created_at": _iso_utc(
            row.created_at
        ),
    }


def _new_event(
    *,
    recipient: TreasuryWithdrawalRecipient,
    username: str,
    action: str,
    from_status: str,
    to_status: str,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> TreasuryWithdrawalRecipientEvent:
    return TreasuryWithdrawalRecipientEvent(
        recipient_id=recipient.recipient_id,
        owner_account_id=(
            recipient.owner_account_id
        ),
        username=str(
            username or ""
        ).strip(),
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


def create_recipient(
    *,
    owner_account_id: str,
    address: str,
    label: str,
    username: str,
) -> dict[str, Any]:
    owner = _owner(
        owner_account_id
    )

    recipient_address = _address(
        address
    )

    identity = _address_key(
        recipient_address
    )

    recipient_label = _label(
        label
    )

    with session_scope() as db:
        existing = db.scalar(
            select(
                TreasuryWithdrawalRecipient
            ).where(
                TreasuryWithdrawalRecipient
                .owner_account_id
                == owner,
                TreasuryWithdrawalRecipient
                .address_key
                == identity,
            )
        )

        if existing is not None:
            return {
                "created": False,
                "item": _snapshot(
                    existing
                ),
            }

        row = TreasuryWithdrawalRecipient(
            recipient_id=(
                "wr_" + uuid4().hex
            ),
            owner_account_id=owner,
            address=recipient_address,
            address_key=identity,
            label=recipient_label,
            status="active",
            created_by=str(
                username or ""
            ).strip(),
        )

        db.add(row)
        db.flush()

        event = _new_event(
            recipient=row,
            username=username,
            action="created",
            from_status="",
            to_status="active",
            reason=(
                "Withdrawal recipient created."
            ),
            metadata={
                "address_identity": (
                    identity.split(
                        ":",
                        1,
                    )[0]
                ),
            },
        )

        db.add(event)
        db.flush()

        return {
            "created": True,
            "item": _snapshot(row),
            "event": (
                _event_snapshot(event)
            ),
        }


def list_recipients(
    *,
    owner_account_ids: set[str] | None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    selected_status = str(
        status or ""
    ).strip().lower()

    if (
        selected_status
        and selected_status
        not in RECIPIENT_STATUSES
    ):
        raise TreasuryWithdrawalRecipientError(
            "Invalid withdrawal recipient status"
        )

    with session_scope() as db:
        query = select(
            TreasuryWithdrawalRecipient
        )

        if owner_account_ids is not None:
            normalized = {
                _owner(item)
                for item in owner_account_ids
            }

            if not normalized:
                return []

            query = query.where(
                TreasuryWithdrawalRecipient
                .owner_account_id
                .in_(
                    sorted(normalized)
                )
            )

        if selected_status:
            query = query.where(
                TreasuryWithdrawalRecipient.status
                == selected_status
            )

        rows = db.scalars(
            query.order_by(
                TreasuryWithdrawalRecipient
                .created_at.desc(),
                TreasuryWithdrawalRecipient
                .id.desc(),
            ).limit(
                max(
                    1,
                    min(
                        int(limit),
                        500,
                    ),
                )
            )
        ).all()

        return [
            _snapshot(row)
            for row in rows
        ]


def get_recipient(
    recipient_id: str,
) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryWithdrawalRecipient
            ).where(
                TreasuryWithdrawalRecipient
                .recipient_id
                == str(
                    recipient_id or ""
                ).strip()
            )
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def list_recipient_events(
    recipient_id: str,
) -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.scalars(
            select(
                TreasuryWithdrawalRecipientEvent
            )
            .where(
                TreasuryWithdrawalRecipientEvent
                .recipient_id
                == str(
                    recipient_id or ""
                ).strip()
            )
            .order_by(
                TreasuryWithdrawalRecipientEvent
                .created_at.asc(),
                TreasuryWithdrawalRecipientEvent
                .id.asc(),
            )
        ).all()

        return [
            _event_snapshot(row)
            for row in rows
        ]


def rename_recipient(
    *,
    recipient_id: str,
    label: str,
    username: str,
) -> dict[str, Any]:
    new_label = _label(
        label
    )

    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryWithdrawalRecipient
            ).where(
                TreasuryWithdrawalRecipient
                .recipient_id
                == str(
                    recipient_id or ""
                ).strip()
            )
        )

        if row is None:
            raise TreasuryWithdrawalRecipientError(
                "Withdrawal recipient not found"
            )

        old_label = row.label

        if old_label == new_label:
            return {
                "changed": False,
                "item": _snapshot(row),
            }

        row.label = new_label
        row.updated_at = utcnow()

        event = _new_event(
            recipient=row,
            username=username,
            action="renamed",
            from_status=row.status,
            to_status=row.status,
            reason=(
                "Withdrawal recipient label changed."
            ),
            metadata={
                "old_label": old_label,
                "new_label": new_label,
            },
        )

        db.add(event)
        db.flush()

        return {
            "changed": True,
            "item": _snapshot(row),
            "event": (
                _event_snapshot(event)
            ),
        }


def archive_recipient(
    *,
    recipient_id: str,
    username: str,
    reason: str = "",
) -> dict[str, Any]:
    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryWithdrawalRecipient
            ).where(
                TreasuryWithdrawalRecipient
                .recipient_id
                == str(
                    recipient_id or ""
                ).strip()
            )
        )

        if row is None:
            raise TreasuryWithdrawalRecipientError(
                "Withdrawal recipient not found"
            )

        prior = str(
            row.status or ""
        ).strip().lower()

        if prior == "archived":
            return {
                "changed": False,
                "item": _snapshot(row),
            }

        if prior != "active":
            raise TreasuryWithdrawalRecipientError(
                "Withdrawal recipient is not active"
            )

        event_reason = _reason(
            reason,
            default=(
                "Withdrawal recipient archived "
                "by its owner."
            ),
        )

        row.status = "archived"
        row.archived_by = str(
            username or ""
        ).strip()
        row.archived_at = utcnow()
        row.updated_at = utcnow()

        event = _new_event(
            recipient=row,
            username=username,
            action="archived",
            from_status=prior,
            to_status="archived",
            reason=event_reason,
        )

        db.add(event)
        db.flush()

        return {
            "changed": True,
            "item": _snapshot(row),
            "event": (
                _event_snapshot(event)
            ),
        }


def restore_recipient(
    *,
    recipient_id: str,
    username: str,
    reason: str = "",
) -> dict[str, Any]:
    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryWithdrawalRecipient
            ).where(
                TreasuryWithdrawalRecipient
                .recipient_id
                == str(
                    recipient_id or ""
                ).strip()
            )
        )

        if row is None:
            raise TreasuryWithdrawalRecipientError(
                "Withdrawal recipient not found"
            )

        prior = str(
            row.status or ""
        ).strip().lower()

        if prior == "active":
            return {
                "changed": False,
                "item": _snapshot(row),
            }

        if prior != "archived":
            raise TreasuryWithdrawalRecipientError(
                "Withdrawal recipient is not archived"
            )

        event_reason = _reason(
            reason,
            default=(
                "Withdrawal recipient restored "
                "by its owner."
            ),
        )

        row.status = "active"
        row.archived_by = ""
        row.archived_at = None
        row.updated_at = utcnow()

        event = _new_event(
            recipient=row,
            username=username,
            action="restored",
            from_status=prior,
            to_status="active",
            reason=event_reason,
        )

        db.add(event)
        db.flush()

        return {
            "changed": True,
            "item": _snapshot(row),
            "event": (
                _event_snapshot(event)
            ),
        }
