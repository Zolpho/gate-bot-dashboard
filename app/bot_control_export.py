from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from .db import session_scope
from .models import (
    BotControlLockResolution,
    BotControlOperationLock,
    BotControlReconciliation,
    BotControlRequest,
)


SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "api_secret",
    "secret",
    "password",
    "passphrase",
    "authorization",
    "access_token",
    "refresh_token",
    "token",
}


def _json(value: str) -> Any:
    try:
        return json.loads(value or "{}")
    except Exception:
        return {}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}

        for key, item in value.items():
            normalized = str(key).lower()

            if normalized in SENSITIVE_KEYS:
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_sensitive(
                    item
                )

        return result

    if isinstance(value, list):
        return [
            redact_sensitive(item)
            for item in value
        ]

    return value


def csv_safe_cell(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(
        value,
        (dict, list),
    ):
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    else:
        text = str(value)

    # Protect against spreadsheet formula injection.
    if (
        text
        and text[0]
        in "=+-@\t\r\n"
    ):
        text = "'" + text

    return text


def _lock_snapshot(
    row: BotControlOperationLock,
) -> dict[str, Any]:
    return {
        "lock_key": row.lock_key,
        "lock_type": row.lock_type,
        "state": row.state,
        "strategy_id": (
            row.strategy_id or None
        ),
        "strategy_type": (
            row.strategy_type or None
        ),
        "market": row.market or None,
        "owner_request_id": (
            row.owner_request_id
        ),
        "acquired_at": _iso(
            row.acquired_at
        ),
        "cooldown_until": _iso(
            row.cooldown_until
        ),
    }


def _reconciliation_snapshot(
    row: BotControlReconciliation,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "outcome": row.outcome,
        "confidence": row.confidence,
        "strategy_id": (
            row.strategy_id or None
        ),
        "gate_status": (
            row.gate_status or None
        ),
        "summary": row.summary,
        "details": redact_sensitive(
            _json(
                row.details_json
            )
        ),
        "created_at": _iso(
            row.created_at
        ),
    }


def _resolution_snapshot(
    row: BotControlLockResolution,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "resolution_type": (
            row.resolution_type
        ),
        "decision": row.decision,
        "username": row.username,
        "reason": row.reason,
        "reconciliation_id": (
            row.reconciliation_id
        ),
        "reconciliation_outcome": (
            row.reconciliation_outcome
        ),
        "reconciliation_confidence": (
            row.reconciliation_confidence
        ),
        "prior_state": row.prior_state,
        "created_at": _iso(
            row.created_at
        ),
    }


def empty_export() -> dict[str, Any]:
    return {
        "generated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "count": 0,
        "items": [],
    }


def build_bot_control_export(
    *,
    account_ids: set[str] | None,
    limit: int = 1000,
) -> dict[str, Any]:
    limit = max(
        1,
        min(
            int(limit),
            5000,
        ),
    )

    if (
        account_ids is not None
        and not account_ids
    ):
        return empty_export()

    with session_scope() as db:
        statement = (
            select(
                BotControlRequest
            )
            .order_by(
                BotControlRequest
                .created_at.desc(),
                BotControlRequest
                .id.desc(),
            )
            .limit(limit)
        )

        if account_ids is not None:
            statement = (
                statement.where(
                    BotControlRequest
                    .account_id.in_(
                        sorted(
                            account_ids
                        )
                    )
                )
            )

        requests = list(
            db.scalars(
                statement
            ).all()
        )

        if not requests:
            return empty_export()

        request_ids = {
            row.request_id
            for row in requests
        }

        locks = db.scalars(
            select(
                BotControlOperationLock
            ).where(
                BotControlOperationLock
                .owner_request_id.in_(
                    sorted(
                        request_ids
                    )
                )
            )
        ).all()

        lock_by_request = {
            row.owner_request_id: row
            for row in locks
        }

        reconciliation_rows = (
            db.scalars(
                select(
                    BotControlReconciliation
                )
                .where(
                    BotControlReconciliation
                    .request_id.in_(
                        sorted(
                            request_ids
                        )
                    )
                )
                .order_by(
                    BotControlReconciliation
                    .created_at.desc(),
                    BotControlReconciliation
                    .id.desc(),
                )
            )
            .all()
        )

        reconciliations: dict[
            str,
            list[dict[str, Any]],
        ] = {}

        for row in reconciliation_rows:
            reconciliations.setdefault(
                row.request_id,
                [],
            ).append(
                _reconciliation_snapshot(
                    row
                )
            )

        resolution_rows = (
            db.scalars(
                select(
                    BotControlLockResolution
                )
                .where(
                    BotControlLockResolution
                    .request_id.in_(
                        sorted(
                            request_ids
                        )
                    )
                )
                .order_by(
                    BotControlLockResolution
                    .created_at.desc(),
                    BotControlLockResolution
                    .id.desc(),
                )
            )
            .all()
        )

        resolutions: dict[
            str,
            list[dict[str, Any]],
        ] = {}

        for row in resolution_rows:
            resolutions.setdefault(
                row.request_id,
                [],
            ).append(
                _resolution_snapshot(
                    row
                )
            )

        items = []

        for row in requests:
            request_data = (
                redact_sensitive(
                    _json(
                        row.request_json
                    )
                )
            )

            response_data = (
                redact_sensitive(
                    _json(
                        row.response_json
                    )
                )
            )

            items.append({
                "request_id": (
                    row.request_id
                ),
                "action": row.action,
                "account_id": (
                    row.account_id
                ),
                "username": row.username,
                "status": row.status,
                "strategy_id": (
                    row.strategy_id
                    or None
                ),
                "gate_status_code": (
                    row.gate_status_code
                ),
                "gate_label": (
                    row.gate_label
                    or None
                ),
                "error": row.error or "",
                "created_at": _iso(
                    row.created_at
                ),
                "updated_at": _iso(
                    row.updated_at
                ),
                "completed_at": _iso(
                    row.completed_at
                ),
                "request": request_data,
                "response": response_data,
                "operation_lock": (
                    _lock_snapshot(
                        lock_by_request[
                            row.request_id
                        ]
                    )
                    if row.request_id
                    in lock_by_request
                    else None
                ),
                "reconciliations": (
                    reconciliations.get(
                        row.request_id,
                        [],
                    )
                ),
                "lock_resolutions": (
                    resolutions.get(
                        row.request_id,
                        [],
                    )
                ),
            })

        return {
            "generated_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "count": len(items),
            "items": items,
        }


def build_bot_control_json(
    document: dict[str, Any],
) -> str:
    return json.dumps(
        document,
        ensure_ascii=False,
        indent=2,
        default=str,
    )


def _csv_row(
    item: dict[str, Any],
) -> dict[str, Any]:
    request = (
        item.get("request")
        or {}
    )

    response = (
        item.get("response")
        or {}
    )

    gate_payload = (
        request.get("gate_payload")
        if isinstance(
            request,
            dict,
        )
        else {}
    )

    if not isinstance(
        gate_payload,
        dict,
    ):
        gate_payload = {}

    create_params = (
        gate_payload.get(
            "create_params"
        )
        or {}
    )

    if not isinstance(
        create_params,
        dict,
    ):
        create_params = {}

    lock = (
        item.get("operation_lock")
        or {}
    )

    reconciliations = (
        item.get(
            "reconciliations"
        )
        or []
    )

    latest_reconciliation = (
        reconciliations[0]
        if reconciliations
        else {}
    )

    resolutions = (
        item.get(
            "lock_resolutions"
        )
        or []
    )

    latest_resolution = (
        resolutions[0]
        if resolutions
        else {}
    )

    return {
        "created_at": (
            item.get("created_at")
        ),
        "completed_at": (
            item.get("completed_at")
        ),
        "account_id": (
            item.get("account_id")
        ),
        "username": (
            item.get("username")
        ),
        "action": (
            item.get("action")
        ),
        "status": (
            item.get("status")
        ),
        "market": (
            gate_payload.get(
                "market"
            )
        ),
        "investment": (
            create_params.get(
                "money"
            )
        ),
        "grid_num": (
            create_params.get(
                "grid_num"
            )
        ),
        "strategy_id": (
            item.get("strategy_id")
        ),
        "write_performed": (
            response.get(
                "write_performed"
            )
            if isinstance(
                response,
                dict,
            )
            else None
        ),
        "simulation": (
            response.get(
                "simulation"
            )
            if isinstance(
                response,
                dict,
            )
            else None
        ),
        "gate_status_code": (
            item.get(
                "gate_status_code"
            )
        ),
        "gate_label": (
            item.get("gate_label")
        ),
        "lock_state": (
            lock.get("state")
        ),
        "lock_type": (
            lock.get("lock_type")
        ),
        "reconciliation_outcome": (
            latest_reconciliation.get(
                "outcome"
            )
        ),
        "reconciliation_confidence": (
            latest_reconciliation.get(
                "confidence"
            )
        ),
        "resolution_type": (
            latest_resolution.get(
                "resolution_type"
            )
        ),
        "resolution_decision": (
            latest_resolution.get(
                "decision"
            )
        ),
        "error": item.get("error"),
        "request_id": (
            item.get("request_id")
        ),
    }


def build_bot_control_csv(
    document: dict[str, Any],
) -> str:
    rows = [
        _csv_row(item)
        for item in (
            document.get("items")
            or []
        )
    ]

    fieldnames = [
        "created_at",
        "completed_at",
        "account_id",
        "username",
        "action",
        "status",
        "market",
        "investment",
        "grid_num",
        "strategy_id",
        "write_performed",
        "simulation",
        "gate_status_code",
        "gate_label",
        "lock_state",
        "lock_type",
        "reconciliation_outcome",
        "reconciliation_confidence",
        "resolution_type",
        "resolution_decision",
        "error",
        "request_id",
    ]

    output = io.StringIO(
        newline=""
    )

    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        extrasaction="ignore",
    )

    writer.writeheader()

    for row in rows:
        writer.writerow({
            key: csv_safe_cell(
                row.get(key)
            )
            for key in fieldnames
        })

    return output.getvalue()


def export_filename(
    extension: str,
) -> str:
    stamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    return (
        "bot_control_audit_"
        f"{stamp}.{extension}"
    )
