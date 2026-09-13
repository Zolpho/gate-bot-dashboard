from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import session_scope, utcnow
from .models import (
    AccountActionPolicy,
    AccountActionPolicyEvent,
    GateAccount,
)

CAPABILITIES = (
    "transfers",
    "withdrawals",
    "trading",
)

_CAPABILITY_COLUMNS = {
    "transfers": "transfers_enabled",
    "withdrawals": "withdrawals_enabled",
    "trading": "trading_enabled",
}


class AccountActionPolicyError(RuntimeError):
    pass


class AccountActionPolicyDenied(
    AccountActionPolicyError
):
    """
    A risk-on account capability is disabled.

    This exception is intentionally framework-neutral so
    Treasury, Trading and Bot Control can share the same
    durable account-policy semantics without coupling the
    service layer to FastAPI.
    """

    def __init__(
        self,
        *,
        account_id: str,
        capability: str,
    ) -> None:
        self.account_id = account_id
        self.capability = capability

        super().__init__(

                f"The {capability.capitalize()} capability is disabled "
                f"for Wallet account {account_id}"

        )

    def safe_dict(
        self,
        *,
        operation: str,
    ) -> dict[str, Any]:
        return {
            "reason": (
                f"{self.capability}"
                "_disabled_by_account_policy"
            ),
            "message": str(self),
            "account_id": self.account_id,
            "capability": self.capability,
            "operation": str(operation or "").strip(),
        }


def _account_id(value: str) -> str:
    normalized = str(value or "").strip().lower()

    if not normalized:
        raise AccountActionPolicyError(
            "Gate account ID is required"
        )

    return normalized


def _username(value: str) -> str:
    normalized = str(value or "").strip().lower()

    if not normalized:
        raise AccountActionPolicyError(
            "Dashboard username is required"
        )

    return normalized


def _capability(value: str) -> str:
    normalized = str(value or "").strip().lower()

    if normalized not in _CAPABILITY_COLUMNS:
        raise AccountActionPolicyError(
            "Unknown account action capability: "
            f"{normalized or '<empty>'}"
        )

    return normalized


def _metadata_json(
    value: dict[str, Any] | None,
) -> str:
    if value is None:
        value = {}

    if not isinstance(value, dict):
        raise AccountActionPolicyError(
            "Policy event metadata must be an object"
        )

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _policy_snapshot(
    account_id: str,
    row: AccountActionPolicy | None,
) -> dict[str, Any]:
    if row is None:
        return {
            "account_id": account_id,
            "exists": False,
            "transfers_enabled": False,
            "withdrawals_enabled": False,
            "trading_enabled": False,
            "updated_by": None,
            "created_at": None,
            "updated_at": None,
        }

    return {
        "account_id": row.account_id,
        "exists": True,
        "transfers_enabled": bool(
            row.transfers_enabled
        ),
        "withdrawals_enabled": bool(
            row.withdrawals_enabled
        ),
        "trading_enabled": bool(
            row.trading_enabled
        ),
        "updated_by": row.updated_by or None,
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
    row: AccountActionPolicyEvent,
) -> dict[str, Any]:
    try:
        metadata = json.loads(
            row.metadata_json or "{}"
        )
    except Exception:
        metadata = {}

    return {
        "id": row.id,
        "account_id": row.account_id,
        "capability": row.capability,
        "old_enabled": (
            None
            if row.old_enabled is None
            else bool(row.old_enabled)
        ),
        "new_enabled": bool(row.new_enabled),
        "username": row.username,
        "reason": row.reason,
        "metadata": metadata,
        "created_at": (
            row.created_at.isoformat()
            if row.created_at
            else None
        ),
    }


def _policy_row(
    db: Session,
    account_id: str,
) -> AccountActionPolicy | None:
    return db.get(
        AccountActionPolicy,
        account_id,
    )


def get_account_action_policy(
    account_id: str,
) -> dict[str, Any]:
    normalized = _account_id(account_id)

    with session_scope() as db:
        return _policy_snapshot(
            normalized,
            _policy_row(
                db,
                normalized,
            ),
        )


def account_action_allowed(
    account_id: str,
    capability: str,
) -> bool:
    normalized_account = _account_id(
        account_id
    )

    normalized_capability = _capability(
        capability
    )

    column_name = _CAPABILITY_COLUMNS[
        normalized_capability
    ]

    with session_scope() as db:
        row = _policy_row(
            db,
            normalized_account,
        )

        # Missing policy is intentionally fail-closed.
        if row is None:
            return False

        return bool(
            getattr(
                row,
                column_name,
            )
        )


def require_account_action_allowed(
    account_id: str,
    capability: str,
) -> None:
    """
    Fail closed when a risk-on account capability is off.

    Missing policy rows remain denied because
    account_action_allowed() is deliberately fail-closed.
    """

    normalized_account = _account_id(
        account_id
    )

    normalized_capability = _capability(
        capability
    )

    if account_action_allowed(
        normalized_account,
        normalized_capability,
    ):
        return

    raise AccountActionPolicyDenied(
        account_id=normalized_account,
        capability=normalized_capability,
    )


def list_account_action_policies(
) -> list[dict[str, Any]]:
    with session_scope() as db:
        accounts = list(
            db.scalars(
                select(GateAccount).order_by(
                    GateAccount.id.asc()
                )
            )
        )

        policies = {
            row.account_id: row
            for row in db.scalars(
                select(AccountActionPolicy)
            )
        }

        result: list[dict[str, Any]] = []

        for account in accounts:
            item = _policy_snapshot(
                account.id,
                policies.get(account.id),
            )

            result.append(
                {
                    **item,
                    "account_name": account.name,
                    "account_type": account.account_type,
                    "account_enabled": bool(
                        account.enabled
                    ),
                    "account_configured": bool(
                        account.configured
                    ),
                }
            )

        return result


def update_account_action_policy(
    account_id: str,
    *,
    username: str,
    transfers_enabled: bool | None = None,
    withdrawals_enabled: bool | None = None,
    trading_enabled: bool | None = None,
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_account = _account_id(
        account_id
    )

    normalized_username = _username(
        username
    )

    requested = {
        "transfers": transfers_enabled,
        "withdrawals": withdrawals_enabled,
        "trading": trading_enabled,
    }

    if all(
        value is None
        for value in requested.values()
    ):
        raise AccountActionPolicyError(
            "At least one policy capability "
            "must be provided"
        )

    for capability, value in requested.items():
        if (
            value is not None
            and not isinstance(value, bool)
        ):
            raise AccountActionPolicyError(
                f"{capability} policy value "
                "must be true or false"
            )

    selected_reason = str(
        reason or ""
    ).strip()

    selected_metadata = _metadata_json(
        metadata
    )

    with session_scope() as db:
        account = db.get(
            GateAccount,
            normalized_account,
        )

        if account is None:
            raise AccountActionPolicyError(
                "Unknown Gate account: "
                f"{normalized_account}"
            )

        row = _policy_row(
            db,
            normalized_account,
        )

        created = row is None

        if row is None:
            now = utcnow()

            row = AccountActionPolicy(
                account_id=normalized_account,
                transfers_enabled=False,
                withdrawals_enabled=False,
                trading_enabled=False,
                updated_by=normalized_username,
                created_at=now,
                updated_at=now,
            )

            db.add(row)
            db.flush()

        changed_events: list[
            AccountActionPolicyEvent
        ] = []

        for capability, requested_value in (
            requested.items()
        ):
            if requested_value is None:
                continue

            column_name = _CAPABILITY_COLUMNS[
                capability
            ]

            old_value = (
                None
                if created
                else bool(
                    getattr(
                        row,
                        column_name,
                    )
                )
            )

            # The first explicit configuration is auditable
            # even when the requested value equals the
            # fail-closed default. Once a durable row exists,
            # repeating the stored value is a true no-op.
            if (
                old_value is not None
                and old_value == requested_value
            ):
                continue

            setattr(
                row,
                column_name,
                requested_value,
            )

            event = AccountActionPolicyEvent(
                account_id=normalized_account,
                capability=capability,
                old_enabled=old_value,
                new_enabled=requested_value,
                username=normalized_username,
                reason=selected_reason,
                metadata_json=selected_metadata,
                created_at=utcnow(),
            )

            db.add(event)
            changed_events.append(event)

        if changed_events:
            row.updated_by = normalized_username
            row.updated_at = utcnow()

        db.flush()

        return {
            "created": created,
            "changed": bool(changed_events),
            "policy": _policy_snapshot(
                normalized_account,
                row,
            ),
            "events": [
                _event_snapshot(event)
                for event in changed_events
            ],
        }


def list_account_action_policy_events(
    account_id: str,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    normalized = _account_id(
        account_id
    )

    if limit < 1 or limit > 1000:
        raise AccountActionPolicyError(
            "Policy event limit must be "
            "between 1 and 1000"
        )

    with session_scope() as db:
        rows = list(
            db.scalars(
                select(
                    AccountActionPolicyEvent
                )
                .where(
                    AccountActionPolicyEvent
                    .account_id
                    == normalized
                )
                .order_by(
                    AccountActionPolicyEvent
                    .id.desc()
                )
                .limit(limit)
            )
        )

        return [
            _event_snapshot(row)
            for row in rows
        ]
