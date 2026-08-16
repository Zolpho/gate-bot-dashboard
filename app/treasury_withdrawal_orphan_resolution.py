from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sqlalchemy import delete, select, text

from .accounts import GateAccountConfig
from .config import Settings
from .db import SessionLocal, engine, utcnow
from .gate_client import GateClient
from .models import (
    TreasuryWithdrawalOperationLock,
    TreasuryWithdrawalReconciliation,
    TreasuryWithdrawalRequest,
    TreasuryWithdrawalRequestEvent,
)
from .treasury_withdrawal_audit import (
    get_withdrawal_request,
    list_withdrawal_reconciliations,
    list_withdrawal_request_events,
)
from .treasury_withdrawal_locks import (
    get_withdrawal_lock_for_request,
)


MIN_ORPHAN_AGE_SECONDS = 3600
MIN_INCONCLUSIVE_RECONCILIATIONS = 3
RECENT_HISTORY_PADDING_SECONDS = 300
RECENT_HISTORY_LIMIT = 100

ABANDONED_STATUS = "withdrawal_abandoned"


class TreasuryWithdrawalOrphanResolutionError(
    RuntimeError
):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(timezone.utc)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _as_utc(value)

    raw = str(value or "").strip()

    if not raw:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Withdrawal submission timestamp "
            "is missing"
        )

    try:
        parsed = datetime.fromisoformat(
            raw.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Withdrawal submission timestamp "
            "is invalid"
        ) from exc

    return _as_utc(parsed)


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as exc:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Withdrawal amount evidence "
            "is invalid"
        ) from exc

    if not result.is_finite():
        raise TreasuryWithdrawalOrphanResolutionError(
            "Withdrawal amount evidence "
            "is not finite"
        )

    return result


def withdrawal_abandon_confirmation_text(
    request: Mapping[str, Any],
) -> str:
    request_id = str(
        request.get("request_id") or ""
    ).strip()

    order_id = str(
        request.get(
            "gate_withdraw_order_id"
        )
        or ""
    ).strip()

    return (
        f"ABANDON WITHDRAWAL {request_id} "
        f"ORDER {order_id}"
    )


def _submission_event_from_snapshots(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    matches = [
        event
        for event in events
        if event.get("action")
        == "withdrawal_submission_started"
    ]

    if len(matches) != 1:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Exactly one withdrawal submission-start "
            "event is required before orphan resolution"
        )

    return matches[0]


def _validate_reconciliations(
    reconciliations: list[dict[str, Any]],
    *,
    minimum_reconciliations: int,
) -> None:
    if (
        len(reconciliations)
        < minimum_reconciliations
    ):
        raise TreasuryWithdrawalOrphanResolutionError(
            "Not enough inconclusive withdrawal "
            "reconciliations exist for orphan resolution"
        )

    for item in reconciliations:
        if (
            str(
                item.get("outcome") or ""
            ).strip().lower()
            != "inconclusive"
            or str(
                item.get("confidence") or ""
            ).strip().lower()
            != "inconclusive"
        ):
            raise TreasuryWithdrawalOrphanResolutionError(
                "Withdrawal history contains a "
                "non-inconclusive reconciliation"
            )


def _validate_lock_snapshot(
    row: Mapping[str, Any],
    lock: Mapping[str, Any] | None,
) -> None:
    if lock is None:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Withdrawal operation lock is missing"
        )

    if (
        str(
            lock.get("owner_request_id")
            or ""
        )
        != str(row["request_id"])
        or str(
            lock.get("owner_account_id")
            or ""
        ).strip().lower()
        != str(
            row["owner_account_id"]
        ).strip().lower()
        or str(
            lock.get("custody_account_id")
            or ""
        ).strip().lower()
        != str(
            row["custody_account_id"]
        ).strip().lower()
        or str(
            lock.get("currency") or ""
        ).strip().upper()
        != str(
            row["currency"]
        ).strip().upper()
        or str(
            lock.get("state") or ""
        ).strip().lower()
        != "held"
    ):
        raise TreasuryWithdrawalOrphanResolutionError(
            "Withdrawal operation lock does not "
            "match the unresolved request"
        )


def _validate_local_candidate(
    *,
    row: dict[str, Any],
    now: datetime,
    minimum_age_seconds: int,
    minimum_reconciliations: int,
) -> dict[str, Any]:
    if row["status"] != "withdrawal_reconciling":
        raise TreasuryWithdrawalOrphanResolutionError(
            "Only withdrawal_reconciling requests "
            "can be abandoned"
        )

    if not bool(row.get("write_performed")):
        raise TreasuryWithdrawalOrphanResolutionError(
            "Orphan resolution requires evidence "
            "that a Gate POST was attempted"
        )

    order_id = str(
        row.get(
            "gate_withdraw_order_id"
        )
        or ""
    ).strip()

    if not order_id:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Persisted Gate withdraw_order_id "
            "is missing"
        )

    if (
        row.get("gate_withdrawal_id")
        or row.get("gate_txid")
        or str(
            row.get("gate_status") or ""
        ).strip()
    ):
        raise TreasuryWithdrawalOrphanResolutionError(
            "Gate withdrawal evidence already exists; "
            "manual orphan resolution is not allowed"
        )

    lock = get_withdrawal_lock_for_request(
        row["request_id"]
    )

    _validate_lock_snapshot(
        row,
        lock,
    )

    events = list_withdrawal_request_events(
        row["request_id"]
    )

    submission_event = (
        _submission_event_from_snapshots(
            events
        )
    )

    submission_at = _parse_datetime(
        submission_event["created_at"]
    )

    age_seconds = max(
        0,
        int(
            (
                _as_utc(now)
                - submission_at
            ).total_seconds()
        ),
    )

    if age_seconds < minimum_age_seconds:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Withdrawal submission is too recent "
            "for orphan resolution"
        )

    reconciliations = (
        list_withdrawal_reconciliations(
            row["request_id"]
        )
    )

    _validate_reconciliations(
        reconciliations,
        minimum_reconciliations=(
            minimum_reconciliations
        ),
    )

    return {
        "order_id": order_id,
        "submission_at": submission_at,
        "submission_age_seconds": (
            age_seconds
        ),
        "reconciliation_count": (
            len(reconciliations)
        ),
    }


def _validate_treasury_credential(
    *,
    settings: Settings,
    treasury_account: GateAccountConfig,
) -> None:
    main_id = (
        settings.treasury_main_account
        .strip()
        .lower()
    )

    if (
        treasury_account.id.strip().lower()
        != main_id
    ):
        raise TreasuryWithdrawalOrphanResolutionError(
            "Treasury credential is not bound "
            "to the configured main account"
        )

    if not treasury_account.enabled:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Treasury credential is disabled"
        )

    if (
        treasury_account.account_type
        .strip()
        .lower()
        != "main"
    ):
        raise TreasuryWithdrawalOrphanResolutionError(
            "Treasury credential must be a "
            "main-account credential"
        )


def _gate_rows(
    response: Any,
    *,
    description: str,
) -> list[dict[str, Any]]:
    if getattr(
        response,
        "status_code",
        None,
    ) != 200:
        raise TreasuryWithdrawalOrphanResolutionError(
            f"{description} did not return HTTP 200"
        )

    data = getattr(
        response,
        "data",
        None,
    )

    if not isinstance(data, list):
        raise TreasuryWithdrawalOrphanResolutionError(
            f"{description} returned an invalid payload"
        )

    if any(
        not isinstance(item, dict)
        for item in data
    ):
        raise TreasuryWithdrawalOrphanResolutionError(
            f"{description} returned malformed records"
        )

    return data


def _plausible_same_withdrawal(
    *,
    record: Mapping[str, Any],
    request: Mapping[str, Any],
) -> bool:
    order_id = str(
        request.get(
            "gate_withdraw_order_id"
        )
        or ""
    ).strip()

    record_order_id = str(
        record.get(
            "withdraw_order_id"
        )
        or ""
    ).strip()

    if (
        order_id
        and record_order_id == order_id
    ):
        return True

    expected_currency = str(
        request.get("currency") or ""
    ).strip().upper()

    record_currency = str(
        record.get("currency") or ""
    ).strip().upper()

    if (
        record_currency
        and record_currency
        != expected_currency
    ):
        return False

    try:
        if (
            _decimal(record.get("amount"))
            != _decimal(request.get("amount"))
        ):
            return False
    except TreasuryWithdrawalOrphanResolutionError:
        # Malformed same-currency history is not safe
        # evidence for releasing a money-movement lock.
        return True

    expected_address = str(
        request.get("address") or ""
    ).strip()

    record_address = str(
        record.get("address") or ""
    ).strip()

    if (
        record_address
        and record_address
        != expected_address
    ):
        return False

    expected_chain = str(
        request.get("chain") or ""
    ).strip().upper()

    record_chain = str(
        record.get("chain") or ""
    ).strip().upper()

    if (
        record_chain
        and record_chain
        != expected_chain
    ):
        return False

    expected_memo = str(
        request.get("memo") or ""
    ).strip()

    if "memo" in record:
        record_memo = str(
            record.get("memo") or ""
        ).strip()

        if record_memo != expected_memo:
            return False

    # Currency + amount match and every available
    # identity field is compatible. Missing Gate
    # fields are treated conservatively as plausible.
    return True


def _validate_db_state_for_finalize(
    *,
    session: Any,
    row: TreasuryWithdrawalRequest,
    now: datetime,
    minimum_age_seconds: int,
    minimum_reconciliations: int,
) -> tuple[
    TreasuryWithdrawalOperationLock,
    datetime,
    int,
]:
    if row.status != "withdrawal_reconciling":
        raise TreasuryWithdrawalOrphanResolutionError(
            "Withdrawal state changed before "
            "orphan resolution could be committed"
        )

    if not row.write_performed:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Withdrawal POST-attempt evidence "
            "disappeared before finalization"
        )

    submission_events = session.scalars(
        select(
            TreasuryWithdrawalRequestEvent
        )
        .where(
            TreasuryWithdrawalRequestEvent
            .request_id
            == row.request_id,
            TreasuryWithdrawalRequestEvent
            .action
            == "withdrawal_submission_started",
        )
        .order_by(
            TreasuryWithdrawalRequestEvent
            .created_at.asc(),
            TreasuryWithdrawalRequestEvent
            .id.asc(),
        )
    ).all()

    if len(submission_events) != 1:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Submission-start audit evidence changed "
            "before finalization"
        )

    submission_at = _as_utc(
        submission_events[0].created_at
    )

    age_seconds = max(
        0,
        int(
            (
                _as_utc(now)
                - submission_at
            ).total_seconds()
        ),
    )

    if age_seconds < minimum_age_seconds:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Withdrawal submission is too recent "
            "for final orphan resolution"
        )

    reconciliations = session.scalars(
        select(
            TreasuryWithdrawalReconciliation
        )
        .where(
            TreasuryWithdrawalReconciliation
            .request_id
            == row.request_id
        )
        .order_by(
            TreasuryWithdrawalReconciliation
            .created_at.asc(),
            TreasuryWithdrawalReconciliation
            .id.asc(),
        )
    ).all()

    if (
        len(reconciliations)
        < minimum_reconciliations
    ):
        raise TreasuryWithdrawalOrphanResolutionError(
            "Reconciliation evidence changed "
            "before finalization"
        )

    for reconciliation in reconciliations:
        if (
            reconciliation.outcome
            != "inconclusive"
            or reconciliation.confidence
            != "inconclusive"
        ):
            raise TreasuryWithdrawalOrphanResolutionError(
                "A non-inconclusive reconciliation "
                "exists; orphan resolution refused"
            )

    lock = session.scalar(
        select(
            TreasuryWithdrawalOperationLock
        ).where(
            TreasuryWithdrawalOperationLock
            .owner_request_id
            == row.request_id
        )
    )

    if lock is None:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Withdrawal lock disappeared "
            "before finalization"
        )

    if (
        lock.owner_account_id
        != row.owner_account_id
        or lock.custody_account_id
        != row.custody_account_id
        or lock.currency
        != row.currency
        or lock.state != "held"
    ):
        raise TreasuryWithdrawalOrphanResolutionError(
            "Withdrawal lock changed "
            "before finalization"
        )

    return (
        lock,
        submission_at,
        len(reconciliations),
    )


def _finalize_abandonment(
    *,
    request_id: str,
    username: str,
    reason: str,
    verification: dict[str, Any],
    minimum_age_seconds: int,
    minimum_reconciliations: int,
) -> dict[str, Any]:
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
            raise TreasuryWithdrawalOrphanResolutionError(
                "Treasury withdrawal request "
                "not found"
            )

        if row.status == ABANDONED_STATUS:
            existing_lock = session.scalar(
                select(
                    TreasuryWithdrawalOperationLock
                ).where(
                    TreasuryWithdrawalOperationLock
                    .owner_request_id
                    == request_id
                )
            )

            if existing_lock is not None:
                raise TreasuryWithdrawalOrphanResolutionError(
                    "Abandoned withdrawal still owns "
                    "an operation lock"
                )

            session.rollback()

            return {
                "idempotent_replay": True,
                "reconciliation_id": None,
                "event_id": None,
            }

        (
            lock,
            submission_at,
            reconciliation_count,
        ) = _validate_db_state_for_finalize(
            session=session,
            row=row,
            now=utcnow(),
            minimum_age_seconds=(
                minimum_age_seconds
            ),
            minimum_reconciliations=(
                minimum_reconciliations
            ),
        )

        if (
            row.gate_withdraw_order_id
            != verification[
                "gate_withdraw_order_id"
            ]
        ):
            raise TreasuryWithdrawalOrphanResolutionError(
                "Persisted Gate withdraw_order_id "
                "changed during verification"
            )

        details = {
            **verification,
            "reason": reason,
            "submission_at": (
                submission_at.isoformat()
            ),
            "submission_age_seconds": max(
                0,
                int(
                    (
                        _as_utc(utcnow())
                        - submission_at
                    ).total_seconds()
                ),
            ),
            "prior_reconciliation_count": (
                reconciliation_count
            ),
            "automatic_retry_allowed": False,
            "gate_read_performed": True,
            "gate_write_performed": False,
            "ownership_settlement_performed": (
                False
            ),
            "resolution_semantics": (
                "operator_reviewed_absence_evidence"
            ),
        }

        reconciliation = (
            TreasuryWithdrawalReconciliation(
                request_id=row.request_id,
                owner_account_id=(
                    row.owner_account_id
                ),
                username=username,
                outcome=(
                    "abandoned_no_gate_record"
                ),
                confidence="operator_reviewed",
                gate_status="",
                gate_withdrawal_id="",
                gate_txid="",
                summary=(
                    "Administrative orphan resolution "
                    "after repeated inconclusive "
                    "reconciliation and fresh Gate "
                    "no-record verification. This is "
                    "not proof that Gate never received "
                    "the original POST."
                ),
                details_json=(
                    _canonical_json(details)
                ),
            )
        )

        event = TreasuryWithdrawalRequestEvent(
            request_id=row.request_id,
            owner_account_id=(
                row.owner_account_id
            ),
            username=username,
            action="withdrawal_abandoned",
            from_status=row.status,
            to_status=ABANDONED_STATUS,
            details_json=_canonical_json(
                details
            ),
        )

        row.status = ABANDONED_STATUS
        row.completed_at = utcnow()

        # Deliberately preserve:
        # - write_performed=True
        # - original error evidence
        # - Gate order ID
        # The historical POST attempt must never be
        # rewritten as though it did not happen.

        session.add(reconciliation)
        session.add(event)
        session.flush()

        reconciliation_id = reconciliation.id
        event_id = event.id

        result = session.execute(
            delete(
                TreasuryWithdrawalOperationLock
            ).where(
                TreasuryWithdrawalOperationLock
                .id
                == lock.id,
                TreasuryWithdrawalOperationLock
                .owner_request_id
                == row.request_id,
            )
        )

        if result.rowcount != 1:
            raise TreasuryWithdrawalOrphanResolutionError(
                "Exact withdrawal operation lock "
                "could not be released atomically"
            )

        session.commit()

        return {
            "idempotent_replay": False,
            "reconciliation_id": (
                reconciliation_id
            ),
            "event_id": event_id,
        }

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


def _resolved_result(
    *,
    request_id: str,
    idempotent_replay: bool,
    reconciliation_id: int | None = None,
    event_id: int | None = None,
) -> dict[str, Any]:
    row = get_withdrawal_request(
        request_id
    )

    if row is None:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Resolved withdrawal request "
            "could not be reloaded"
        )

    lock = get_withdrawal_lock_for_request(
        request_id
    )

    if lock is not None:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Resolved withdrawal still owns "
            "an operation lock"
        )

    reconciliations = (
        list_withdrawal_reconciliations(
            request_id
        )
    )

    events = list_withdrawal_request_events(
        request_id
    )

    reconciliation = next(
        (
            item
            for item in reconciliations
            if item.get("id")
            == reconciliation_id
        ),
        None,
    )

    event = next(
        (
            item
            for item in events
            if item.get("id")
            == event_id
        ),
        None,
    )

    return {
        "status": ABANDONED_STATUS,
        "idempotent_replay": (
            idempotent_replay
        ),
        "gate_read_performed": (
            not idempotent_replay
        ),
        "gate_write_performed": False,
        "ownership_settlement_performed": False,
        "automatic_retry_allowed": False,
        "lock_released": (
            not idempotent_replay
        ),
        "audit": row,
        "operation_lock": None,
        "reconciliation": reconciliation,
        "event": event,
    }


async def abandon_unresolved_withdrawal(
    *,
    settings: Settings,
    request_id: str,
    username: str,
    reason: str,
    confirmation: str,
    treasury_account: GateAccountConfig,
    minimum_age_seconds: int = (
        MIN_ORPHAN_AGE_SECONDS
    ),
    minimum_reconciliations: int = (
        MIN_INCONCLUSIVE_RECONCILIATIONS
    ),
) -> dict[str, Any]:
    if minimum_age_seconds < 0:
        raise ValueError(
            "minimum_age_seconds cannot be negative"
        )

    if minimum_reconciliations < 1:
        raise ValueError(
            "minimum_reconciliations must be positive"
        )

    reason = str(reason or "").strip()

    if len(reason) < 20:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Orphan-resolution reason must contain "
            "at least 20 characters"
        )

    row = get_withdrawal_request(
        request_id
    )

    if row is None:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Treasury withdrawal request not found"
        )

    if row["status"] == ABANDONED_STATUS:
        return _resolved_result(
            request_id=request_id,
            idempotent_replay=True,
        )

    if settings.treasury_withdrawals_live_armed:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Withdrawal orphan resolution requires "
            "Treasury withdrawals to be disarmed"
        )

    if (
        str(
            row["custody_account_id"]
        ).strip().lower()
        != settings.treasury_main_account
        .strip()
        .lower()
    ):
        raise TreasuryWithdrawalOrphanResolutionError(
            "Withdrawal custody account is not "
            "the configured Treasury main account"
        )

    now = datetime.now(timezone.utc)

    local = _validate_local_candidate(
        row=row,
        now=now,
        minimum_age_seconds=(
            minimum_age_seconds
        ),
        minimum_reconciliations=(
            minimum_reconciliations
        ),
    )

    required_confirmation = (
        withdrawal_abandon_confirmation_text(
            row
        )
    )

    if confirmation != required_confirmation:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Exact withdrawal-abandon "
            "confirmation is required"
        )

    _validate_treasury_credential(
        settings=settings,
        treasury_account=treasury_account,
    )

    order_id = local["order_id"]

    async with GateClient(
        settings,
        treasury_account,
    ) as client:
        exact_response = (
            await client.list_withdrawals(
                currency=row["currency"],
                withdraw_order_id=order_id,
                limit=RECENT_HISTORY_LIMIT,
                offset=0,
            )
        )

        exact_rows = _gate_rows(
            exact_response,
            description=(
                "Exact Gate withdrawal lookup"
            ),
        )

        if exact_rows:
            raise TreasuryWithdrawalOrphanResolutionError(
                "Gate now has a withdrawal record "
                "for the persisted withdraw_order_id; "
                "orphan resolution refused"
            )

        from_timestamp = max(
            0,
            int(
                local[
                    "submission_at"
                ].timestamp()
            )
            - RECENT_HISTORY_PADDING_SECONDS,
        )

        to_timestamp = int(
            now.timestamp()
        )

        recent_response = (
            await client.list_withdrawals(
                currency=row["currency"],
                from_timestamp=(
                    from_timestamp
                ),
                to_timestamp=to_timestamp,
                limit=RECENT_HISTORY_LIMIT,
                offset=0,
            )
        )

        recent_rows = _gate_rows(
            recent_response,
            description=(
                "Recent Gate withdrawal lookup"
            ),
        )

    # If Gate filled a complete 100-row page, we do not
    # know whether another page contains the candidate.
    # Fail closed rather than releasing the lock.
    if (
        len(recent_rows)
        >= RECENT_HISTORY_LIMIT
    ):
        raise TreasuryWithdrawalOrphanResolutionError(
            "Recent Gate withdrawal history filled "
            "the query limit; absence cannot be proven"
        )

    plausible = [
        record
        for record in recent_rows
        if _plausible_same_withdrawal(
            record=record,
            request=row,
        )
    ]

    if plausible:
        raise TreasuryWithdrawalOrphanResolutionError(
            "Recent Gate withdrawal history contains "
            "a plausible record for this request; "
            "orphan resolution refused"
        )

    verification = {
        "gate_withdraw_order_id": order_id,
        "exact_get_http_status": (
            exact_response.status_code
        ),
        "exact_result_count": 0,
        "recent_get_http_status": (
            recent_response.status_code
        ),
        "recent_result_count": (
            len(recent_rows)
        ),
        "plausible_candidate_count": 0,
        "verification_window_from": (
            from_timestamp
        ),
        "verification_window_to": (
            to_timestamp
        ),
    }

    finalized = _finalize_abandonment(
        request_id=request_id,
        username=username,
        reason=reason,
        verification=verification,
        minimum_age_seconds=(
            minimum_age_seconds
        ),
        minimum_reconciliations=(
            minimum_reconciliations
        ),
    )

    return _resolved_result(
        request_id=request_id,
        idempotent_replay=(
            finalized[
                "idempotent_replay"
            ]
        ),
        reconciliation_id=(
            finalized[
                "reconciliation_id"
            ]
        ),
        event_id=finalized["event_id"],
    )
