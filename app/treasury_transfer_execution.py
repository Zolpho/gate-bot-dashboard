from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException

from .accounts import GateAccountConfig
from .config import Settings
from .gate_client import (
    GateAPIError,
    GateClient,
)
from .treasury_transfer import (
    TreasuryTransferValidationError,
    as_decimal,
    build_subaccount_to_main_preflight,
)
from .treasury_transfer_audit import (
    TreasuryTransferIdempotencyConflict,
    mark_transfer_request,
    record_transfer_reconciliation,
    reserve_live_transfer,
)
from .treasury_transfer_live_policy import (
    evaluate_live_transfer_policy,
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


def existing_live_transfer_result(
    record: dict,
) -> dict:
    """
    Return an already-terminal transfer safely.

    Non-terminal/uncertain records must be reconciled rather
    than causing a second Gate POST.
    """

    status = str(
        record.get("status") or ""
    )

    if status in {
        "success",
        "failed",
        "blocked",
        "rejected",
    }:
        return {
            "phase": "T2B_TRANSFER_CONTROL",
            "status": status,
            "simulation": False,
            "gate_write_performed": bool(
                record.get("write_performed")
            ),
            "idempotent_replay": True,
            "request_id": record["request_id"],
            "audit": record,
            "message": (
                "Existing Treasury request returned. "
                "No second Gate transfer was sent."
            ),
        }

    raise HTTPException(
        status_code=409,
        detail={
            "message": (
                "This Treasury request_id already exists "
                "and is not in a safely retryable state. "
                "No second Gate transfer was sent. "
                "Reconcile the existing request."
            ),
            "request_id": record["request_id"],
            "status": status,
            "write_performed": bool(
                record.get("write_performed")
            ),
        },
    )


async def reconcile_live_transfer(
    *,
    settings: Settings,
    record: dict,
    treasury_account: GateAccountConfig,
) -> dict:
    """
    Read-only reconciliation of an already-submitted
    Treasury internal transfer.

    This function NEVER performs the transfer POST.
    """

    request_id = record["request_id"]

    try:
        async with GateClient(
            settings,
            treasury_account,
        ) as client:
            response = (
                await client.get_transfer_order_status(
                    client_order_id=(
                        record["client_order_id"]
                    ),
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
                    "Gate transfer status query failed. "
                    "Treasury lock remains held."
                ),
                details={
                    "error": str(exc),
                    "label": exc.label,
                    "status_code": exc.status_code,
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
            "lock_released": False,
            "audit": updated,
            "reconciliation": reconciliation,
        }

    decision = interpret_transfer_order_status(
        response.data
    )

    tx_id = (
        decision.tx_id
        or str(
            record.get("gate_transfer_id")
            or ""
        )
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
            tx_id=tx_id,
            summary=decision.summary,
            details=response.raw,
        )
    )

    updated = mark_transfer_request(
        request_id,
        status=decision.request_status,
        response=response.raw,
        gate_transfer_id=tx_id,
        write_performed=(
            True
            if decision.gate_status
            else bool(
                record.get("write_performed")
            )
        ),
        completed=decision.terminal,
    )

    released = False

    if decision.release_lock:
        released = release_transfer_lock(
            source_account_id=(
                record["source_account_id"]
            ),
            currency=record["currency"],
            owner_request_id=request_id,
        )

    return {
        "status": decision.request_status,
        "lock_released": released,
        "audit": updated,
        "reconciliation": reconciliation,
    }


async def execute_reserved_live_transfer(
    *,
    settings: Settings,
    source_account: GateAccountConfig,
    treasury_account: GateAccountConfig,
    request_id: str,
    username: str,
    currency: str,
    amount: Decimal,
    audit_payload: dict,
    gate_payload: dict,
) -> dict:
    """
    Execute one already-authorized subaccount -> main
    Treasury transfer.

    IMPORTANT:
      * Authentication/authorization is done by the caller.
      * Human confirmation is done by the caller.
      * Rate limiting is done by the caller.
      * Treasury live arm/allowlist is checked by the caller
        AND again by evaluate_live_transfer_policy below.
      * Exactly one Gate transfer POST exists here.
      * Nothing automatically retries that POST.
    """

    source_account_id = (
        source_account.id.strip().lower()
    )

    selected_currency = (
        currency.strip().upper()
    )

    try:
        audit_record, created = (
            reserve_live_transfer(
                request_id=request_id,
                source_account_id=(
                    source_account_id
                ),
                destination_account_id=(
                    settings.treasury_main_account
                ),
                username=username,
                currency=selected_currency,
                amount=amount,
                payload=audit_payload,
            )
        )

    except TreasuryTransferIdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    if not created:
        return existing_live_transfer_result(
            audit_record
        )

    try:
        operation_lock = acquire_transfer_lock(
            source_account_id=(
                source_account_id
            ),
            currency=selected_currency,
            owner_request_id=request_id,
            username=username,
        )

    except TreasuryTransferLocked as exc:
        message = (
            "Another unresolved Treasury transfer "
            "already owns the source/currency lock."
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
                "write_performed": False,
            },
        ) from exc

    mark_transfer_request(
        request_id,
        status="validating",
    )

    # Fresh source balance uses the ordinary Monitor
    # credential. No Treasury write is possible here.
    try:
        async with GateClient(
            settings,
            source_account,
        ) as client:
            balances_response = (
                await client.list_spot_accounts()
            )

        preflight = (
            build_subaccount_to_main_preflight(
                source_account=source_account,
                main_account_id=(
                    settings.treasury_main_account
                ),
                currency=selected_currency,
                amount=amount,
                spot_accounts=(
                    balances_response.data
                ),
            )
        )

    except (
        GateAPIError,
        TreasuryTransferValidationError,
    ) as exc:
        mark_transfer_request(
            request_id,
            status="preflight_failed",
            error=str(exc),
            completed=True,
        )

        release_transfer_lock(
            source_account_id=(
                source_account_id
            ),
            currency=selected_currency,
            owner_request_id=request_id,
        )

        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "Treasury transfer preflight failed. "
                    "No Gate write was performed."
                ),
                "error": str(exc),
                "write_performed": False,
            },
        ) from exc

    if not preflight["can_transfer"]:
        message = (
            "Treasury transfer preflight rejected "
            "the requested amount."
        )

        mark_transfer_request(
            request_id,
            status="blocked",
            response=preflight,
            error=message,
            completed=True,
        )

        release_transfer_lock(
            source_account_id=(
                source_account_id
            ),
            currency=selected_currency,
            owner_request_id=request_id,
        )

        raise HTTPException(
            status_code=409,
            detail={
                "message": message,
                "errors": preflight["errors"],
                "write_performed": False,
            },
        )

    available_amount = as_decimal(
        preflight.get("available")
    )

    if available_amount is None:
        mark_transfer_request(
            request_id,
            status="preflight_failed",
            error=(
                "Available balance could not be parsed"
            ),
            completed=True,
        )

        release_transfer_lock(
            source_account_id=(
                source_account_id
            ),
            currency=selected_currency,
            owner_request_id=request_id,
        )

        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Treasury safety policy could not "
                    "determine available balance."
                ),
                "write_performed": False,
            },
        )

    live_decision = (
        evaluate_live_transfer_policy(
            settings=settings,
            source_account_id=(
                source_account_id
            ),
            currency=selected_currency,
            requested_amount=amount,
            available_amount=available_amount,
        )
    )

    if not live_decision.allowed:
        mark_transfer_request(
            request_id,
            status="blocked",
            response=live_decision.safe_dict(),
            error=live_decision.message,
            completed=True,
        )

        release_transfer_lock(
            source_account_id=(
                source_account_id
            ),
            currency=selected_currency,
            owner_request_id=request_id,
        )

        raise HTTPException(
            status_code=403,
            detail={
                **live_decision.safe_dict(),
                "write_performed": False,
            },
        )

    mark_transfer_request(
        request_id,
        status="submitting",
    )

    # MONEY-MOVING BOUNDARY.
    #
    # There is exactly ONE Gate POST below.
    # After reaching this boundary an ambiguous exception
    # retains the transfer lock and this function NEVER
    # retries the POST automatically.
    try:
        async with GateClient(
            settings,
            treasury_account,
        ) as client:
            response = (
                await client
                .create_sub_account_transfer(
                    gate_payload
                )
            )

    except GateAPIError as exc:
        submission_decision = (
            interpret_transfer_submission_error(
                exc.status_code
            )
        )

        mark_transfer_request(
            request_id,
            status=(
                submission_decision.request_status
            ),
            response=exc.response,
            error=str(exc),
            gate_status_code=exc.status_code,
            gate_label=exc.label,
            write_performed=True,
            completed=(
                submission_decision.definitive
            ),
        )

        lock_released = False

        if submission_decision.release_lock:
            lock_released = (
                release_transfer_lock(
                    source_account_id=(
                        source_account_id
                    ),
                    currency=selected_currency,
                    owner_request_id=request_id,
                )
            )

        detail = {
            "message": (
                submission_decision.summary
            ),
            "request_id": request_id,
            "status": (
                submission_decision
                .request_status
            ),
            "write_performed": True,
            "lock_released": lock_released,
            "gate_error": str(exc),
        }

        if not submission_decision.definitive:
            detail["reconcile_path"] = (
                "/api/treasury/transfers/"
                f"{request_id}/reconcile"
            )

        raise HTTPException(
            status_code=502,
            detail=detail,
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
                    "Unexpected error after the Treasury "
                    "Gate submission boundary. Outcome is "
                    "uncertain. Do not retry."
                ),
                "request_id": request_id,
                "status": "uncertain",
            },
        ) from exc

    data = (
        response.data
        if isinstance(response.data, dict)
        else {}
    )

    tx_id = str(
        data.get("tx_id") or ""
    )

    submitted = mark_transfer_request(
        request_id,
        status="submitted",
        response=response.raw,
        gate_transfer_id=tx_id,
        write_performed=True,
        completed=False,
    )

    reconciliation = (
        await reconcile_live_transfer(
            settings=settings,
            record=submitted,
            treasury_account=treasury_account,
        )
    )

    return {
        "phase": "T2B_TRANSFER_CONTROL",
        "status": reconciliation["status"],
        "simulation": False,
        "gate_write_performed": True,
        "idempotent_replay": False,
        "request_id": request_id,
        "source_account_id": (
            source_account_id
        ),
        "destination_account_id": (
            settings.treasury_main_account
        ),
        "policy": live_decision.safe_dict(),
        "transfer": preflight,
        "gate_payload": gate_payload,
        "operation_lock": operation_lock,
        **reconciliation,
    }
