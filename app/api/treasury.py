from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..accounts import get_gate_account
from ..config import get_settings
from ..gate_client import GateAPIError, GateClient
from ..security import (
    DashboardUser,
    require_account_access,
    require_super_admin,
    require_user,
)
from ..treasury import (
    TreasuryConfigError,
    get_treasury_account,
    safe_treasury_config,
)
from ..treasury_transfer import (
    TreasuryTransferValidationError,
    as_decimal,
    build_gate_subaccount_transfer_payload,
    build_subaccount_to_main_preflight,
    gate_client_order_id,
    live_transfer_confirmation_text,
)
from ..treasury_transfer_audit import (
    TreasuryTransferIdempotencyConflict,
    find_matching_transfer_request,
    get_transfer_request,
    list_transfer_reconciliations,
    list_transfer_requests,
    mark_transfer_request,
    record_simulation,
    record_transfer_reconciliation,
    reserve_live_transfer,
)
from ..treasury_transfer_live_policy import (
    evaluate_live_transfer_policy,
)
from ..treasury_transfer_locks import (
    TreasuryTransferLocked,
    acquire_transfer_lock,
    get_transfer_lock_for_request,
    list_transfer_locks,
    release_transfer_lock,
)
from ..treasury_transfer_lock_resolution import (
    TreasuryLockResolutionError,
    list_lock_resolutions,
    manual_release_transfer_lock,
)
from ..treasury_rate_limit import (
    TreasuryRateLimitExceeded,
    enforce_treasury_rate_limit,
)
from ..treasury_transfer_reconcile import (
    interpret_transfer_order_status,
    interpret_transfer_submission_error,
)


router = APIRouter(
    prefix="/api/treasury",
    tags=["treasury"],
)

settings = get_settings()

_CURRENCY_RE = re.compile(r"^[A-Z0-9_]{1,20}$")


def _require_treasury_access(
    user: DashboardUser,
) -> str:
    return require_account_access(
        user,
        settings.treasury_main_account,
    )


def _currency(value: str) -> str:
    normalized = str(value or "").strip().upper()

    if not _CURRENCY_RE.fullmatch(normalized):
        raise HTTPException(
            status_code=400,
            detail="Invalid currency",
        )

    return normalized


def _enforce_treasury_rate_limit(
    *,
    user: DashboardUser,
    source_account_id: str,
    action: str,
) -> None:
    try:
        enforce_treasury_rate_limit(
            settings=settings,
            username=user.username,
            source_account_id=source_account_id,
            action=action,
        )

    except TreasuryRateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=exc.detail(),
            headers={
                "Retry-After": str(
                    exc.retry_after_seconds
                ),
            },
        ) from exc


def _treasury_account_or_http():  # type: ignore[no-untyped-def]
    try:
        account = get_treasury_account()
    except TreasuryConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    if account is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Treasury credential is not configured. "
                "T1 remains read-only and unarmed."
            ),
        )

    return account


class TreasuryTransferSimulationRequest(BaseModel):
    request_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$",
    )

    source_account_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$",
    )

    currency: str = Field(
        min_length=1,
        max_length=20,
        pattern=r"^[A-Za-z0-9_]+$",
    )

    amount: Decimal = Field(gt=0)


class TreasuryTransferExecutionRequest(
    TreasuryTransferSimulationRequest
):
    confirmation: str = Field(
        min_length=1,
        max_length=255,
    )


def _existing_live_transfer_result(
    record: dict,
) -> dict:
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


async def _reconcile_live_transfer(
    *,
    record: dict,
    treasury_account,
) -> dict:
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


@router.post("/transfers/simulate")
async def simulate_treasury_transfer(
    request: TreasuryTransferSimulationRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    source_account_id = require_account_access(
        user,
        request.source_account_id,
    )

    source_account = get_gate_account(
        source_account_id
    )

    if (
        source_account is None
        or not source_account.enabled
        or not source_account.configured
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Monitor credentials are not configured "
                f"for {source_account_id}"
            ),
        )

    # Ensure the privileged Treasury identity is configured,
    # but T2A does not perform any write using it.
    _treasury_account_or_http()

    selected_currency = _currency(
        request.currency
    )

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
                amount=request.amount,
                spot_accounts=balances_response.data,
            )
        )

    except TreasuryTransferValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except GateAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    base_response = {
        "phase": "T2B_TRANSFER_CONTROL",
        "status": (
            "ready"
            if preflight["can_simulate"]
            else "invalid"
        ),
        "simulation": True,
        "gate_write_performed": False,
        "transfers_enabled": False,
        "withdrawals_enabled": False,
        "credential_profiles": {
            "source_balance": "monitor",
            "future_transfer": "treasury",
        },
        "transfer": preflight,
        "client_order_id_preview": (
            gate_client_order_id(
                request.request_id
            )
        ),
    }

    if not preflight["can_simulate"]:
        return {
            **base_response,
            "audit_recorded": False,
        }

    audit_payload = {
        "request_id": request.request_id,
        "source_account_id": (
            source_account_id
        ),
        "destination_account_id": (
            settings.treasury_main_account
        ),
        "direction": "from",
        "currency": selected_currency,
        "amount": format(
            request.amount,
            "f",
        ),
    }

    try:
        audit, created = record_simulation(
            request_id=request.request_id,
            source_account_id=(
                source_account_id
            ),
            destination_account_id=(
                settings.treasury_main_account
            ),
            username=user.username,
            currency=selected_currency,
            amount=request.amount,
            payload=audit_payload,
            response=base_response,
        )

    except TreasuryTransferIdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return {
        **base_response,
        "audit_recorded": True,
        "audit_created": created,
        "audit": audit,
    }


@router.post("/transfers/execute")
async def execute_treasury_transfer(
    request: TreasuryTransferExecutionRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    source_account_id = require_account_access(
        user,
        request.source_account_id,
    )

    selected_currency = _currency(
        request.currency
    )

    source_account = get_gate_account(
        source_account_id
    )

    if (
        source_account is None
        or not source_account.enabled
        or not source_account.configured
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Monitor credentials are not configured "
                f"for {source_account_id}"
            ),
        )

    try:
        gate_payload = (
            build_gate_subaccount_transfer_payload(
                source_account=source_account,
                currency=selected_currency,
                amount=request.amount,
                request_id=request.request_id,
            )
        )

    except TreasuryTransferValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    audit_payload = {
        "operation": "subaccount_to_main",
        "source_account_id": (
            source_account_id
        ),
        "destination_account_id": (
            settings.treasury_main_account
        ),
        "gate_payload": gate_payload,
    }

    # Idempotency check happens BEFORE any live balance read
    # and, critically, before any possible Gate write.
    try:
        existing = find_matching_transfer_request(
            request_id=request.request_id,
            source_account_id=(
                source_account_id
            ),
            username=user.username,
            payload=audit_payload,
        )

    except TreasuryTransferIdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    if existing is not None:
        return _existing_live_transfer_result(
            existing
        )

    required_confirmation = (
        live_transfer_confirmation_text(
            base_text=(
                settings
                .treasury_transfer_confirmation_text
            ),
            source_account_id=source_account_id,
            destination_account_id=(
                settings.treasury_main_account
            ),
            currency=selected_currency,
            amount=request.amount,
        )
    )

    if request.confirmation != required_confirmation:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Invalid Treasury live transfer "
                    "confirmation text."
                ),
                "required_confirmation": (
                    required_confirmation
                ),
                "write_performed": False,
            },
        )

    # Fast rejection before creating a live audit reservation.
    if not settings.treasury_transfers_live_armed:
        raise HTTPException(
            status_code=403,
            detail={
                "message": (
                    "Live Treasury transfers are not armed."
                ),
                "reason": "live_not_armed",
                "write_performed": False,
            },
        )

    if not (
        settings
        .treasury_transfers_live_account_allowed(
            source_account_id
        )
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "message": (
                    "This source account is not enabled "
                    "for live Treasury transfers."
                ),
                "reason": (
                    "source_account_not_live_enabled"
                ),
                "write_performed": False,
            },
        )

    _enforce_treasury_rate_limit(
        user=user,
        source_account_id=source_account_id,
        action="execute",
    )

    treasury_account = (
        _treasury_account_or_http()
    )

    try:
        audit_record, created = (
            reserve_live_transfer(
                request_id=request.request_id,
                source_account_id=(
                    source_account_id
                ),
                destination_account_id=(
                    settings.treasury_main_account
                ),
                username=user.username,
                currency=selected_currency,
                amount=request.amount,
                payload=audit_payload,
            )
        )

    except TreasuryTransferIdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    if not created:
        return _existing_live_transfer_result(
            audit_record
        )

    try:
        operation_lock = acquire_transfer_lock(
            source_account_id=(
                source_account_id
            ),
            currency=selected_currency,
            owner_request_id=request.request_id,
            username=user.username,
        )

    except TreasuryTransferLocked as exc:
        message = (
            "Another unresolved Treasury transfer "
            "already owns the source/currency lock."
        )

        mark_transfer_request(
            request.request_id,
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
        request.request_id,
        status="validating",
    )

    # The source balance is read using the source account's
    # ordinary Monitor credential. No Treasury write is
    # possible during this stage.
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
                amount=request.amount,
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
            request.request_id,
            status="preflight_failed",
            error=str(exc),
            completed=True,
        )

        release_transfer_lock(
            source_account_id=(
                source_account_id
            ),
            currency=selected_currency,
            owner_request_id=request.request_id,
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
            request.request_id,
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
            owner_request_id=request.request_id,
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
            request.request_id,
            status="preflight_failed",
            error="Available balance could not be parsed",
            completed=True,
        )

        release_transfer_lock(
            source_account_id=(
                source_account_id
            ),
            currency=selected_currency,
            owner_request_id=request.request_id,
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
            requested_amount=request.amount,
            available_amount=available_amount,
        )
    )

    if not live_decision.allowed:
        mark_transfer_request(
            request.request_id,
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
            owner_request_id=request.request_id,
        )

        raise HTTPException(
            status_code=403,
            detail={
                **live_decision.safe_dict(),
                "write_performed": False,
            },
        )

    mark_transfer_request(
        request.request_id,
        status="submitting",
    )

    # MONEY-MOVING BOUNDARY.
    #
    # There is exactly one Gate POST below. Any exception after
    # reaching it is treated as UNCERTAIN. The operation lock is
    # deliberately retained and this code never retries the POST.
    try:
        async with GateClient(
            settings,
            treasury_account,
        ) as client:
            response = (
                await client.create_sub_account_transfer(
                    gate_payload
                )
            )

    except GateAPIError as exc:
        submission_decision = (
            interpret_transfer_submission_error(
                exc.status_code
            )
        )

        updated = mark_transfer_request(
            request.request_id,
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
            lock_released = release_transfer_lock(
                source_account_id=(
                    source_account_id
                ),
                currency=selected_currency,
                owner_request_id=(
                    request.request_id
                ),
            )

        detail = {
            "message": submission_decision.summary,
            "request_id": request.request_id,
            "status": (
                submission_decision.request_status
            ),
            "write_performed": True,
            "lock_released": lock_released,
            "gate_error": str(exc),
        }

        if not submission_decision.definitive:
            detail["reconcile_path"] = (
                "/api/treasury/transfers/"
                f"{request.request_id}/reconcile"
            )

        raise HTTPException(
            status_code=502,
            detail=detail,
        ) from exc

    except Exception as exc:
        mark_transfer_request(
            request.request_id,
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
                "request_id": request.request_id,
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
        request.request_id,
        status="submitted",
        response=response.raw,
        gate_transfer_id=tx_id,
        write_performed=True,
        completed=False,
    )

    reconciliation = (
        await _reconcile_live_transfer(
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
        "request_id": request.request_id,
        "source_account_id": source_account_id,
        "destination_account_id": (
            settings.treasury_main_account
        ),
        "policy": live_decision.safe_dict(),
        "transfer": preflight,
        "gate_payload": gate_payload,
        "operation_lock": operation_lock,
        **reconciliation,
    }


@router.post(
    "/transfers/{request_id}/reconcile"
)
async def reconcile_treasury_transfer(
    request_id: str,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    record = get_transfer_request(
        request_id
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Treasury transfer request not found",
        )

    require_account_access(
        user,
        record["source_account_id"],
    )

    if record["simulation"]:
        raise HTTPException(
            status_code=409,
            detail=(
                "Simulation records do not require "
                "Gate transfer reconciliation."
            ),
        )

    if record["status"] in {
        "success",
        "failed",
    }:
        return {
            "phase": "T2B_TRANSFER_CONTROL",
            "status": record["status"],
            "idempotent_replay": True,
            "gate_read_performed": False,
            "audit": record,
            "reconciliations": (
                list_transfer_reconciliations(
                    request_id
                )
            ),
        }

    _enforce_treasury_rate_limit(
        user=user,
        source_account_id=(
            record["source_account_id"]
        ),
        action="reconcile",
    )

    treasury_account = (
        _treasury_account_or_http()
    )

    result = await _reconcile_live_transfer(
        record=record,
        treasury_account=treasury_account,
    )

    return {
        "phase": "T2B_TRANSFER_CONTROL",
        "idempotent_replay": False,
        "gate_read_performed": True,
        **result,
    }


@router.get("/transfers/requests")
def treasury_transfer_requests(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
):
    account_ids = (
        None
        if user.is_super_admin
        else set(user.account_ids)
    )

    return {
        "phase": "T2B_TRANSFER_CONTROL",
        "items": list_transfer_requests(
            limit=limit,
            account_ids=account_ids,
        ),
    }


@router.get("/transfers/requests/{request_id}")
def treasury_transfer_request_detail(
    request_id: str,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    row = get_transfer_request(request_id)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Treasury transfer request not found",
        )

    require_account_access(
        user,
        row["source_account_id"],
    )

    return {
        "phase": "T2B_TRANSFER_CONTROL",
        "item": row,
        "reconciliations": (
            list_transfer_reconciliations(
                request_id
            )
        ),
        "operation_lock": (
            get_transfer_lock_for_request(
                request_id
            )
        ),
        "lock_resolutions": (
            list_lock_resolutions(
                request_id
            )
        ),
    }


class TreasuryManualLockReleaseRequest(BaseModel):
    confirmation: str = Field(
        min_length=1,
        max_length=255,
    )

    reason: str = Field(
        min_length=20,
        max_length=1000,
    )


@router.get("/transfers/locks")
def treasury_transfer_locks(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    source_account_ids = (
        None
        if user.is_super_admin
        else set(user.account_ids)
    )

    return {
        "phase": "T2B_TRANSFER_CONTROL",
        "items": list_transfer_locks(
            source_account_ids=(
                source_account_ids
            )
        ),
    }


@router.post(
    "/transfers/{request_id}/lock/release"
)
def release_treasury_transfer_lock(
    request_id: str,
    request: TreasuryManualLockReleaseRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_super_admin),
    ],
):
    row = get_transfer_request(request_id)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Treasury transfer request not found",
        )

    required_confirmation = (
        "RELEASE TREASURY LOCK "
        + request_id
    )

    if request.confirmation != required_confirmation:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Invalid Treasury lock-release "
                    "confirmation text."
                ),
                "required_confirmation": (
                    required_confirmation
                ),
                "write_performed": False,
            },
        )

    _enforce_treasury_rate_limit(
        user=user,
        source_account_id=(
            row["source_account_id"]
        ),
        action="lock_release",
    )

    try:
        result = manual_release_transfer_lock(
            request_id=request_id,
            username=user.username,
            reason=request.reason,
            live_armed=(
                settings
                .treasury_transfers_live_armed
            ),
        )

    except TreasuryLockResolutionError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "write_performed": False,
            },
        ) from exc

    return {
        "phase": "T2B_TRANSFER_CONTROL",
        "gate_write_performed": False,
        **result,
    }


@router.get("/status")
def treasury_status(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    _require_treasury_access(user)

    payload = safe_treasury_config()

    return {
        **payload,
        "mode": (
            "demo"
            if settings.demo_mode
            else "live"
        ),
        "authorized_user": user.safe_dict(),
    }


@router.get("/balance")
async def treasury_balance(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    currency: str = Query(
        default="USDT",
        min_length=1,
        max_length=20,
    ),
):
    _require_treasury_access(user)

    account = _treasury_account_or_http()
    selected_currency = _currency(currency)

    try:
        async with GateClient(
            settings,
            account,
        ) as client:
            total = await client.get_total_balance(
                selected_currency
            )
            spot = await client.list_spot_accounts()

    except GateAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    return {
        "phase": "T2B_TRANSFER_CONTROL",
        "main_account": settings.treasury_main_account,
        "currency": selected_currency,
        "account": account.safe_dict(),
        "total_balance": total.raw,
        "spot_accounts": spot.raw,
        "transfers_enabled": False,
        "withdrawals_enabled": False,
    }


@router.get("/chains/{currency}")
async def treasury_currency_chains(
    currency: str,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    _require_treasury_access(user)

    account = _treasury_account_or_http()
    selected_currency = _currency(currency)

    try:
        async with GateClient(
            settings,
            account,
        ) as client:
            response = await client.list_currency_chains(
                selected_currency
            )

    except GateAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    return {
        "phase": "T2B_TRANSFER_CONTROL",
        "main_account": settings.treasury_main_account,
        "currency": selected_currency,
        "chains": response.raw,
        "transfers_enabled": False,
        "withdrawals_enabled": False,
    }
