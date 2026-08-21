from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException

from .accounts import GateAccountConfig
from .config import Settings
from .gate_client import GateAPIError, GateClient
from .treasury_transfer import (
    TreasuryTransferValidationError,
    decimal_text,
    gate_client_order_id,
    validate_transfer_amount,
)
from .treasury_transfer_audit import (
    TreasuryTransferIdempotencyConflict,
    mark_transfer_request,
    record_transfer_reconciliation,
    reserve_user_account_transfer,
)
from .treasury_transfer_locks import (
    TreasuryTransferLocked,
    acquire_transfer_lock,
    release_transfer_lock,
)
from .treasury_transfer_reconcile import (
    interpret_transfer_order_status,
    interpret_transfer_submission_error,
)

USER_TRANSFER_OPERATION = "user_account_transfer"

SUB_TO_SUB = "subaccount_to_subaccount"
SUB_TO_MAIN = "subaccount_to_main"
MAIN_TO_SUB = "main_to_subaccount"


def build_user_gate_transfer(
    *,
    source_account: GateAccountConfig,
    destination_account: GateAccountConfig,
    currency: str,
    amount: Decimal,
    request_id: str,
) -> dict[str, Any]:
    """
    Build the Gate request for a dashboard user transfer.

    No API call is performed here.
    """
    validate_transfer_amount(amount)

    source_id = source_account.id.strip().lower()
    destination_id = (
        destination_account.id.strip().lower()
    )

    if source_id == destination_id:
        raise TreasuryTransferValidationError(
            "Source and destination must be different"
        )

    source_type = (
        source_account.account_type.strip().lower()
    )
    destination_type = (
        destination_account.account_type.strip().lower()
    )

    symbol = currency.strip().upper()

    if (
        source_type == "subaccount"
        and destination_type == "subaccount"
    ):
        if not source_account.gate_uid:
            raise TreasuryTransferValidationError(
                f"Source account '{source_id}' has no Gate UID"
            )

        if not destination_account.gate_uid:
            raise TreasuryTransferValidationError(
                "Destination account "
                f"'{destination_id}' has no Gate UID"
            )

        payload = {
            "currency": symbol,
            "sub_account_from": (
                source_account.gate_uid
            ),
            "sub_account_from_type": "spot",
            "sub_account_to": (
                destination_account.gate_uid
            ),
            "sub_account_to_type": "spot",
            "amount": decimal_text(amount),
        }

        return {
            "path": SUB_TO_SUB,
            "endpoint": (
                "/wallet/"
                "sub_account_to_sub_account"
            ),
            "payload": payload,
            # Gate does not accept client_order_id
            # on this endpoint.
            "client_order_id_sent": False,
        }

    if (
        source_type == "subaccount"
        and destination_type == "main"
    ):
        if not source_account.gate_uid:
            raise TreasuryTransferValidationError(
                f"Source account '{source_id}' has no Gate UID"
            )

        payload = {
            "sub_account": source_account.gate_uid,
            "sub_account_type": "spot",
            "currency": symbol,
            "amount": decimal_text(amount),
            "direction": "from",
            "client_order_id": (
                gate_client_order_id(request_id)
            ),
        }

        return {
            "path": SUB_TO_MAIN,
            "endpoint": (
                "/wallet/sub_account_transfers"
            ),
            "payload": payload,
            "client_order_id_sent": True,
        }

    if (
        source_type == "main"
        and destination_type == "subaccount"
    ):
        if not destination_account.gate_uid:
            raise TreasuryTransferValidationError(
                "Destination account "
                f"'{destination_id}' has no Gate UID"
            )

        payload = {
            "sub_account": (
                destination_account.gate_uid
            ),
            "sub_account_type": "spot",
            "currency": symbol,
            "amount": decimal_text(amount),
            "direction": "to",
            "client_order_id": (
                gate_client_order_id(request_id)
            ),
        }

        return {
            "path": MAIN_TO_SUB,
            "endpoint": (
                "/wallet/sub_account_transfers"
            ),
            "payload": payload,
            "client_order_id_sent": True,
        }

    raise TreasuryTransferValidationError(
        "Unsupported Gate user-transfer path: "
        f"{source_type} -> {destination_type}"
    )


def _available_spot_amount(
    rows: Any,
    currency: str,
) -> Decimal:
    symbol = currency.strip().upper()

    if not isinstance(rows, list):
        return Decimal("0")

    for row in rows:
        if not isinstance(row, dict):
            continue

        if (
            str(row.get("currency") or "")
            .strip()
            .upper()
            != symbol
        ):
            continue

        try:
            amount = Decimal(
                str(row.get("available") or "0")
            )
        except (
            InvalidOperation,
            TypeError,
            ValueError,
        ):
            return Decimal("0")

        if not amount.is_finite():
            return Decimal("0")

        return amount

    return Decimal("0")


def existing_user_transfer_result(
    record: dict[str, Any],
) -> dict[str, Any]:
    status = str(
        record.get("status") or ""
    ).strip().lower()

    if status in {
        "success",
        "failed",
        "blocked",
        "rejected",
        "preflight_failed",
    }:
        return {
            "phase": "USER_ACCOUNT_TRANSFER",
            "status": status,
            "gate_write_performed": bool(
                record.get("write_performed")
            ),
            "idempotent_replay": True,
            "request_id": record["request_id"],
            "audit": record,
            "message": (
                "Existing user transfer request "
                "returned. No second Gate transfer "
                "was submitted."
            ),
        }

    raise HTTPException(
        status_code=409,
        detail={
            "message": (
                "This user-transfer request ID "
                "already exists in a non-terminal "
                "state. No second Gate transfer "
                "was submitted."
            ),
            "request_id": record["request_id"],
            "status": status,
            "gate_write_performed": bool(
                record.get("write_performed")
            ),
            "reconciliation_required": True,
        },
    )


def _record_transfer_path(
    record: dict[str, Any],
) -> str:
    payload = record.get("request") or {}

    if not isinstance(payload, dict):
        return ""

    return str(
        payload.get("transfer_path") or ""
    ).strip().lower()


async def reconcile_user_account_transfer(
    *,
    settings: Settings,
    record: dict[str, Any],
    treasury_account: GateAccountConfig,
) -> dict[str, Any]:
    """
    Read-only reconciliation.

    This function never submits a transfer POST.
    """
    request_id = record["request_id"]
    transfer_path = _record_transfer_path(record)

    tx_id = str(
        record.get("gate_transfer_id") or ""
    ).strip()

    client_order_id = str(
        record.get("client_order_id") or ""
    ).strip()

    # Sub->sub has no Gate client_order_id.
    # Without a persisted tx_id there is no safe
    # automatic lookup key and definitely no safe retry.
    if (
        transfer_path == SUB_TO_SUB
        and not tx_id
    ):
        reconciliation = (
            record_transfer_reconciliation(
                request_id=request_id,
                source_account_id=(
                    record["source_account_id"]
                ),
                username=record["username"],
                outcome="unknown",
                confidence="inconclusive",
                summary=(
                    "Subaccount-to-subaccount transfer "
                    "has no persisted Gate tx_id. "
                    "Automatic retry is forbidden."
                ),
                details={
                    "transfer_path": transfer_path,
                    "gate_read_performed": False,
                },
            )
        )

        updated = mark_transfer_request(
            request_id,
            status="uncertain",
            error=(
                "No Gate tx_id is available for "
                "subaccount-to-subaccount reconciliation."
            ),
            write_performed=bool(
                record.get("write_performed")
            ),
            completed=False,
        )

        return {
            "status": "uncertain",
            "gate_read_performed": False,
            "lock_released": False,
            "manual_review_required": True,
            "audit": updated,
            "reconciliation": reconciliation,
        }

    lookup: dict[str, str]

    if transfer_path == SUB_TO_SUB:
        lookup = {"tx_id": tx_id}

    elif client_order_id:
        lookup = {
            "client_order_id": client_order_id
        }

    elif tx_id:
        lookup = {"tx_id": tx_id}

    else:
        reconciliation = (
            record_transfer_reconciliation(
                request_id=request_id,
                source_account_id=(
                    record["source_account_id"]
                ),
                username=record["username"],
                outcome="unknown",
                confidence="inconclusive",
                summary=(
                    "No Gate reconciliation key "
                    "is available."
                ),
                details={
                    "transfer_path": transfer_path,
                    "gate_read_performed": False,
                },
            )
        )

        updated = mark_transfer_request(
            request_id,
            status="uncertain",
            error=(
                "No Gate reconciliation key "
                "is available."
            ),
            completed=False,
        )

        return {
            "status": "uncertain",
            "gate_read_performed": False,
            "lock_released": False,
            "manual_review_required": True,
            "audit": updated,
            "reconciliation": reconciliation,
        }

    try:
        async with GateClient(
            settings,
            treasury_account,
        ) as client:
            response = (
                await client
                .get_transfer_order_status(
                    **lookup
                )
            )

    except GateAPIError as exc:
        reconciliation = (
            record_transfer_reconciliation(
                request_id=request_id,
                source_account_id=(
                    record["source_account_id"]
                ),
                username=record["username"],
                outcome="inconclusive",
                confidence="inconclusive",
                summary=(
                    "Gate user-transfer status "
                    "query failed. Lock remains held."
                ),
                details={
                    "error": str(exc),
                    "label": exc.label,
                    "status_code": exc.status_code,
                    "transfer_path": transfer_path,
                },
            )
        )

        updated = mark_transfer_request(
            request_id,
            status="uncertain",
            error=str(exc),
            write_performed=bool(
                record.get("write_performed")
            ),
            completed=False,
        )

        return {
            "status": "uncertain",
            "gate_read_performed": True,
            "lock_released": False,
            "audit": updated,
            "reconciliation": reconciliation,
        }

    decision = interpret_transfer_order_status(
        response.data
    )

    resulting_tx_id = (
        decision.tx_id
        or tx_id
    )

    reconciliation = (
        record_transfer_reconciliation(
            request_id=request_id,
            source_account_id=(
                record["source_account_id"]
            ),
            username=record["username"],
            outcome=decision.outcome,
            confidence=decision.confidence,
            gate_status=decision.gate_status,
            tx_id=resulting_tx_id,
            summary=decision.summary,
            details=response.raw,
        )
    )

    updated = mark_transfer_request(
        request_id,
        status=decision.request_status,
        response=response.raw,
        gate_transfer_id=resulting_tx_id,
        write_performed=(
            True
            if decision.gate_status
            else bool(
                record.get("write_performed")
            )
        ),
        completed=decision.terminal,
    )

    lock_released = False

    if decision.release_lock:
        lock_released = release_transfer_lock(
            source_account_id=(
                record["source_account_id"]
            ),
            currency=record["currency"],
            owner_request_id=request_id,
        )

    return {
        "status": decision.request_status,
        "gate_read_performed": True,
        "lock_released": lock_released,
        "manual_review_required": (
            decision.request_status
            in {
                "attention",
                "uncertain",
            }
        ),
        "audit": updated,
        "reconciliation": reconciliation,
    }


async def execute_user_account_transfer(
    *,
    settings: Settings,
    source_account: GateAccountConfig,
    destination_account: GateAccountConfig,
    treasury_account: GateAccountConfig,
    request_id: str,
    username: str,
    currency: str,
    amount: Decimal,
    transfer_path: str,
    audit_payload: dict[str, Any],
    gate_payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Execute exactly one account-scoped Gate transfer.

    Caller is responsible for user/source authorization,
    destination authorization, confirmation and rate limit.

    This function still independently checks the user-transfer
    live arm before crossing the Gate POST boundary.
    """
    if not settings.treasury_user_transfers_enabled:
        raise HTTPException(
            status_code=403,
            detail={
                "reason": "user_transfers_not_enabled",
                "message": (
                    "Dashboard user transfers "
                    "are not enabled."
                ),
                "gate_write_performed": False,
            },
        )

    try:
        validate_transfer_amount(amount)
    except TreasuryTransferValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    source_id = source_account.id.strip().lower()
    destination_id = (
        destination_account.id.strip().lower()
    )
    symbol = currency.strip().upper()

    try:
        audit_record, created = (
            reserve_user_account_transfer(
                request_id=request_id,
                source_account_id=source_id,
                destination_account_id=(
                    destination_id
                ),
                username=username,
                currency=symbol,
                amount=amount,
                payload=audit_payload,
                client_order_id=str(
                    gate_payload.get(
                        "client_order_id"
                    )
                    or ""
                ),
            )
        )
    except TreasuryTransferIdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    if not created:
        return existing_user_transfer_result(
            audit_record
        )

    try:
        operation_lock = acquire_transfer_lock(
            source_account_id=source_id,
            currency=symbol,
            owner_request_id=request_id,
            username=username,
        )

    except TreasuryTransferLocked as exc:
        message = (
            "Another unresolved Treasury operation "
            "already owns this source/currency lock."
        )

        mark_transfer_request(
            request_id,
            status="blocked",
            error=message,
            completed=True,
        )

        raise HTTPException(
            status_code=409,
            detail={
                "message": message,
                "conflicting_lock": exc.lock,
                "gate_write_performed": False,
            },
        ) from exc

    mark_transfer_request(
        request_id,
        status="validating",
    )

    # Fresh balance read uses only the source account's
    # ordinary Monitor credential.
    try:
        async with GateClient(
            settings,
            source_account,
        ) as client:
            balances_response = (
                await client.list_spot_accounts()
            )

    except GateAPIError as exc:
        mark_transfer_request(
            request_id,
            status="preflight_failed",
            error=str(exc),
            completed=True,
        )

        release_transfer_lock(
            source_account_id=source_id,
            currency=symbol,
            owner_request_id=request_id,
        )

        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "Fresh Gate balance read failed. "
                    "No transfer was submitted."
                ),
                "gate_write_performed": False,
            },
        ) from exc

    available = _available_spot_amount(
        balances_response.data,
        symbol,
    )

    if available < amount:
        message = (
            "Requested transfer exceeds the fresh "
            "available Gate spot balance."
        )

        mark_transfer_request(
            request_id,
            status="blocked",
            response={
                "available": decimal_text(available),
                "requested": decimal_text(amount),
                "currency": symbol,
            },
            error=message,
            completed=True,
        )

        release_transfer_lock(
            source_account_id=source_id,
            currency=symbol,
            owner_request_id=request_id,
        )

        raise HTTPException(
            status_code=409,
            detail={
                "message": message,
                "available": decimal_text(available),
                "requested": decimal_text(amount),
                "gate_write_performed": False,
            },
        )

    mark_transfer_request(
        request_id,
        status="submitting",
    )

    # MONEY-MOVING BOUNDARY.
    #
    # Every real write uses the privileged Treasury/main
    # credential, never a credential selected by the browser.
    #
    # Exactly one POST is attempted. No automatic retry exists.
    try:
        async with GateClient(
            settings,
            treasury_account,
        ) as client:
            if transfer_path == SUB_TO_SUB:
                response = await (
                    client
                    .create_sub_account_to_sub_account_transfer(
                        gate_payload
                    )
                )

            elif transfer_path in {
                SUB_TO_MAIN,
                MAIN_TO_SUB,
            }:
                response = await (
                    client
                    .create_sub_account_transfer(
                        gate_payload
                    )
                )

            else:
                raise RuntimeError(
                    "Unsupported user-transfer "
                    f"path: {transfer_path}"
                )

    except GateAPIError as exc:
        submission = (
            interpret_transfer_submission_error(
                exc.status_code
            )
        )

        updated = mark_transfer_request(
            request_id,
            status=submission.request_status,
            response=exc.response,
            error=str(exc),
            gate_status_code=exc.status_code,
            gate_label=exc.label,
            write_performed=True,
            completed=submission.definitive,
        )

        lock_released = False

        if submission.release_lock:
            lock_released = release_transfer_lock(
                source_account_id=source_id,
                currency=symbol,
                owner_request_id=request_id,
            )

        raise HTTPException(
            status_code=502,
            detail={
                "message": submission.summary,
                "request_id": request_id,
                "status": submission.request_status,
                "gate_write_performed": True,
                "lock_released": lock_released,
                "audit": updated,
                "automatic_retry_allowed": False,
            },
        ) from exc

    except Exception as exc:
        mark_transfer_request(
            request_id,
            status="uncertain",
            error=str(exc),
            write_performed=True,
            completed=False,
        )

        raise HTTPException(
            status_code=500,
            detail={
                "message": (
                    "Unexpected error after the Gate "
                    "submission boundary. Outcome is "
                    "uncertain. Do not retry."
                ),
                "request_id": request_id,
                "status": "uncertain",
                "gate_write_performed": True,
                "automatic_retry_allowed": False,
            },
        ) from exc

    data = (
        response.data
        if isinstance(response.data, dict)
        else {}
    )

    tx_id = str(
        data.get("tx_id") or ""
    ).strip()

    submitted = mark_transfer_request(
        request_id,
        status="submitted",
        response=response.raw,
        gate_transfer_id=tx_id,
        write_performed=True,
        completed=False,
    )

    reconciliation = (
        await reconcile_user_account_transfer(
            settings=settings,
            record=submitted,
            treasury_account=treasury_account,
        )
    )

    return {
        "phase": "USER_ACCOUNT_TRANSFER",
        "status": reconciliation["status"],
        "gate_write_performed": True,
        "idempotent_replay": False,
        "request_id": request_id,
        "source_account_id": source_id,
        "destination_account_id": destination_id,
        "currency": symbol,
        "amount": decimal_text(amount),
        "transfer_path": transfer_path,
        "fresh_available_before": (
            decimal_text(available)
        ),
        "gate_payload": gate_payload,
        "operation_lock": operation_lock,
        **reconciliation,
    }
