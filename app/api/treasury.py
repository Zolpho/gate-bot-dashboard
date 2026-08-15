from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

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
from ..treasury_ownership import (
    custody_liability_amount,
    ownership_amount,
    list_ownership_entries,
    ownership_balances,
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
from ..treasury_withdrawal import (
    bind_destination_to_preflight,
    build_withdrawal_capabilities,
    build_withdrawal_preflight,
)
from ..treasury_withdrawal_destinations import (
    TreasuryWithdrawalDestinationError,
    approve_destination,
    create_candidate_destination,
    get_destination,
    list_destination_events,
    list_destinations,
    revoke_destination,
)
from ..treasury_withdrawal_audit import (
    TreasuryWithdrawalIdempotencyConflict,
    TreasuryWithdrawalStateError,
    find_matching_withdrawal_request,
    get_withdrawal_request,
    list_withdrawal_reconciliations,
    list_withdrawal_request_events,
    list_withdrawal_requests,
    record_withdrawal_simulation,
    transition_withdrawal_request,
)
from ..treasury_withdrawal_locks import (
    TreasuryWithdrawalLocked,
    acquire_withdrawal_lock,
    get_withdrawal_lock_for_request,
    list_withdrawal_locks,
    release_withdrawal_lock,
)
from ..treasury_withdrawal_jit import (
    TreasuryWithdrawalJitPlanError,
    build_withdrawal_jit_plan,
    withdrawal_jit_preparation_confirmation_text,
)
from ..treasury_withdrawal_workflow import (
    destination_snapshot_mismatches,
    withdrawal_cancel_confirmation_text,
    withdrawal_confirmation_text,
    withdrawal_reservation_confirmation_text,
)
from ..treasury_transfer_reconcile import (
    interpret_transfer_order_status,
    interpret_transfer_submission_error,
)
from ..treasury_transfer_execution import (
    execute_reserved_live_transfer,
    existing_live_transfer_result,
    reconcile_live_transfer,
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



class TreasuryWithdrawalDestinationCandidateRequest(
    BaseModel
):
    owner_account_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$",
    )

    currency: str = Field(
        min_length=1,
        max_length=20,
        pattern=r"^[A-Za-z0-9_]+$",
    )

    chain: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )

    address: str = Field(
        min_length=1,
        max_length=512,
    )

    memo: str = Field(
        default="",
        max_length=512,
    )

    label: str = Field(
        default="",
        max_length=128,
    )


class TreasuryWithdrawalDestinationDecisionRequest(
    BaseModel
):
    confirmation: str = Field(
        min_length=1,
        max_length=255,
    )

    reason: str = Field(
        min_length=20,
        max_length=1000,
    )


class TreasuryWithdrawalSimulationRequest(
    BaseModel
):
    # Fail closed rather than silently accepting obsolete
    # client fields such as chain/address/memo.
    model_config = ConfigDict(
        extra="forbid",
    )

    request_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=(
            r"^[A-Za-z0-9]"
            r"[A-Za-z0-9._:-]{7,127}$"
        ),
    )

    owner_account_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=(
            r"^[a-z0-9]"
            r"[a-z0-9_-]{0,63}$"
        ),
    )

    destination_id: str = Field(
        min_length=4,
        max_length=128,
        pattern=(
            r"^[A-Za-z0-9]"
            r"[A-Za-z0-9._:-]{3,127}$"
        ),
    )

    currency: str = Field(
        min_length=1,
        max_length=20,
        pattern=r"^[A-Za-z0-9_]+$",
    )

    amount: Decimal = Field(
        gt=0,
    )


class TreasuryWithdrawalReservationRequest(
    BaseModel
):
    model_config = ConfigDict(
        extra="forbid",
    )

    confirmation: str = Field(
        min_length=1,
        max_length=500,
    )


class TreasuryWithdrawalConfirmationRequest(
    BaseModel
):
    model_config = ConfigDict(
        extra="forbid",
    )

    confirmation: str = Field(
        min_length=1,
        max_length=500,
    )


class TreasuryWithdrawalCancellationRequest(
    BaseModel
):
    model_config = ConfigDict(
        extra="forbid",
    )

    confirmation: str = Field(
        min_length=1,
        max_length=500,
    )

    reason: str = Field(
        min_length=20,
        max_length=1000,
    )


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
        return existing_live_transfer_result(
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

    return await execute_reserved_live_transfer(
        settings=settings,
        source_account=source_account,
        treasury_account=treasury_account,
        request_id=request.request_id,
        username=user.username,
        currency=selected_currency,
        amount=request.amount,
        audit_payload=audit_payload,
        gate_payload=gate_payload,
    )


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

    result = await reconcile_live_transfer(
        settings=settings,
        record=record,
        treasury_account=treasury_account,
    )

    return {
        "phase": "T2B_TRANSFER_CONTROL",
        "idempotent_replay": False,
        "gate_read_performed": True,
        **result,
    }


@router.get("/ownership/balances")
def treasury_ownership_balances(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    account_ids = (
        None
        if user.is_super_admin
        else set(user.account_ids)
    )

    return {
        "phase": "T2B_TRANSFER_CONTROL",
        "items": ownership_balances(
            account_ids=account_ids,
        ),
    }


@router.get("/ownership/ledger")
def treasury_ownership_ledger(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    limit: int = Query(
        default=200,
        ge=1,
        le=500,
    ),
):
    account_ids = (
        None
        if user.is_super_admin
        else set(user.account_ids)
    )

    return {
        "phase": "T2B_TRANSFER_CONTROL",
        "items": list_ownership_entries(
            account_ids=account_ids,
            limit=limit,
        ),
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


@router.post(
    "/withdrawals/destinations"
)
def create_treasury_withdrawal_destination(
    request: TreasuryWithdrawalDestinationCandidateRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    owner = require_account_access(
        user,
        request.owner_account_id,
    )

    try:
        result = create_candidate_destination(
            owner_account_id=owner,
            currency=request.currency,
            chain=request.chain,
            address=request.address,
            memo=request.memo,
            label=request.label,
            username=user.username,
        )

    except TreasuryWithdrawalDestinationError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "local_write_performed": False,
                "gate_write_performed": False,
            },
        ) from exc

    return {
        "phase": "T2C2A_DESTINATION_REGISTRY",
        "withdrawals_enabled": False,
        "local_write_performed": bool(
            result["created"]
        ),
        "gate_write_performed": False,
        **result,
    }


@router.get(
    "/withdrawals/destinations"
)
def treasury_withdrawal_destinations(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    owner_account_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=64,
    ),
    status: str | None = Query(
        default=None,
        min_length=1,
        max_length=32,
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
):
    if owner_account_id:
        selected_owner = require_account_access(
            user,
            owner_account_id,
        )
        owner_ids: set[str] | None = {
            selected_owner
        }

    else:
        owner_ids = (
            None
            if user.is_super_admin
            else set(user.account_ids)
        )

    try:
        items = list_destinations(
            owner_account_ids=owner_ids,
            status=status,
            limit=limit,
        )

    except TreasuryWithdrawalDestinationError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "phase": "T2C2A_DESTINATION_REGISTRY",
        "withdrawals_enabled": False,
        "gate_write_performed": False,
        "items": items,
    }


@router.get(
    "/withdrawals/destinations/{destination_id}"
)
def treasury_withdrawal_destination_detail(
    destination_id: str,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    row = get_destination(destination_id)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Withdrawal destination not found",
        )

    require_account_access(
        user,
        row["owner_account_id"],
    )

    return {
        "phase": "T2C2A_DESTINATION_REGISTRY",
        "withdrawals_enabled": False,
        "gate_write_performed": False,
        "item": row,
        "events": list_destination_events(
            destination_id
        ),
    }


@router.post(
    "/withdrawals/destinations/"
    "{destination_id}/approve"
)
def approve_treasury_withdrawal_destination(
    destination_id: str,
    request: TreasuryWithdrawalDestinationDecisionRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_super_admin),
    ],
):
    required_confirmation = (
        "APPROVE WITHDRAWAL DESTINATION "
        + destination_id
    )

    if request.confirmation != required_confirmation:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Invalid withdrawal destination "
                    "approval confirmation text."
                ),
                "required_confirmation": (
                    required_confirmation
                ),
                "local_write_performed": False,
                "gate_write_performed": False,
            },
        )

    try:
        result = approve_destination(
            destination_id=destination_id,
            username=user.username,
            reason=request.reason,
        )

    except TreasuryWithdrawalDestinationError as exc:
        status_code = (
            404
            if str(exc)
            == "Withdrawal destination not found"
            else 409
        )

        raise HTTPException(
            status_code=status_code,
            detail={
                "message": str(exc),
                "local_write_performed": False,
                "gate_write_performed": False,
            },
        ) from exc

    return {
        "phase": "T2C2A_DESTINATION_REGISTRY",
        "withdrawals_enabled": False,
        "local_write_performed": bool(
            result["changed"]
        ),
        "gate_write_performed": False,
        **result,
    }


@router.post(
    "/withdrawals/destinations/"
    "{destination_id}/revoke"
)
def revoke_treasury_withdrawal_destination(
    destination_id: str,
    request: TreasuryWithdrawalDestinationDecisionRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_super_admin),
    ],
):
    required_confirmation = (
        "REVOKE WITHDRAWAL DESTINATION "
        + destination_id
    )

    if request.confirmation != required_confirmation:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Invalid withdrawal destination "
                    "revocation confirmation text."
                ),
                "required_confirmation": (
                    required_confirmation
                ),
                "local_write_performed": False,
                "gate_write_performed": False,
            },
        )

    try:
        result = revoke_destination(
            destination_id=destination_id,
            username=user.username,
            reason=request.reason,
        )

    except TreasuryWithdrawalDestinationError as exc:
        status_code = (
            404
            if str(exc)
            == "Withdrawal destination not found"
            else 409
        )

        raise HTTPException(
            status_code=status_code,
            detail={
                "message": str(exc),
                "local_write_performed": False,
                "gate_write_performed": False,
            },
        ) from exc

    return {
        "phase": "T2C2A_DESTINATION_REGISTRY",
        "withdrawals_enabled": False,
        "local_write_performed": bool(
            result["changed"]
        ),
        "gate_write_performed": False,
        **result,
    }


@router.get(
    "/withdrawals/preflight/{currency}"
)
async def treasury_withdrawal_preflight(
    currency: str,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    owner_account_id: str = Query(
        ...,
        min_length=1,
        max_length=64,
    ),
    destination_id: str = Query(
        ...,
        min_length=4,
        max_length=128,
    ),
    amount: Decimal = Query(
        ...,
        gt=0,
    ),
):
    owner = require_account_access(
        user,
        owner_account_id,
    )

    selected_currency = _currency(currency)

    destination = get_destination(
        destination_id
    )

    # Do not disclose another owner's destination even
    # if the caller somehow knows its opaque ID.
    if (
        destination is None
        or str(
            destination.get(
                "owner_account_id"
            )
            or ""
        ).strip().lower()
        != owner
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "Withdrawal destination not found"
            ),
        )

    destination_currency = str(
        destination.get("currency")
        or ""
    ).strip().upper()

    if (
        destination_currency
        != selected_currency
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Withdrawal destination currency "
                    "does not match the requested currency"
                ),
                "preflight_valid": False,
                "executable": False,
                "gate_write_performed": False,
            },
        )

    # The chain is security-sensitive and comes only from
    # the stored destination. The caller cannot override it.
    selected_chain = str(
        destination.get("chain")
        or ""
    ).strip().upper()

    if not selected_chain:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Withdrawal destination does not "
                    "contain a valid chain"
                ),
                "preflight_valid": False,
                "executable": False,
                "gate_write_performed": False,
            },
        )

    source_account = get_gate_account(owner)

    if (
        source_account is None
        or not source_account.enabled
        or not source_account.configured
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Monitor credentials are not configured "
                f"for {owner}"
            ),
        )

    treasury_account = (
        _treasury_account_or_http()
    )

    owner_main_held = ownership_amount(
        owner_account_id=owner,
        custody_account_id=(
            settings.treasury_main_account
        ),
        currency=selected_currency,
    )

    custody_liabilities = (
        custody_liability_amount(
            custody_account_id=(
                settings.treasury_main_account
            ),
            currency=selected_currency,
        )
    )

    try:
        async with GateClient(
            settings,
            source_account,
        ) as client:
            source_spot = (
                await client.list_spot_accounts()
            )

        async with GateClient(
            settings,
            treasury_account,
        ) as client:
            main_spot = (
                await client.list_spot_accounts()
            )

            chains = (
                await client.list_currency_chains(
                    selected_currency
                )
            )

            withdrawal_status = (
                await client.get_withdraw_status(
                    selected_currency
                )
            )

    except GateAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    capabilities = build_withdrawal_capabilities(
        owner_account_id=owner,
        main_account_id=(
            settings.treasury_main_account
        ),
        currency=selected_currency,
        spot_accounts=source_spot.data,
        main_spot_accounts=main_spot.data,
        raw_chains=chains.data,
        raw_withdraw_status=(
            withdrawal_status.data
        ),
        owner_main_held=owner_main_held,
        custody_liabilities=(
            custody_liabilities
        ),
    )

    preflight = build_withdrawal_preflight(
        capabilities=capabilities,
        chain=selected_chain,
        amount=amount,
    )

    preflight = bind_destination_to_preflight(
        preflight=preflight,
        destination=destination,
        owner_account_id=owner,
        currency=selected_currency,
    )

    return {
        "phase": "T2B_TRANSFER_CONTROL",
        "withdrawal_phase": (
            "T2C2B_DESTINATION_BOUND_PREFLIGHT"
        ),
        "gate_write_performed": False,
        "transfers_enabled": False,
        "withdrawals_enabled": False,
        "credential_profiles": {
            "source_balance": "monitor",
            "main_liquidity": (
                "treasury_read_only"
            ),
            "withdrawal_status": (
                "treasury_read_only"
            ),
        },
        "preflight": preflight,
    }


@router.post(
    "/withdrawals/requests/simulate"
)
async def simulate_treasury_withdrawal_request(
    request: TreasuryWithdrawalSimulationRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    owner = require_account_access(
        user,
        request.owner_account_id,
    )

    selected_currency = _currency(
        request.currency
    )

    # Fingerprint contains only caller intent. Security-
    # sensitive destination identity is resolved from the
    # approved local registry and snapshotted separately.
    audit_payload = {
        "operation": "external_withdrawal_simulation",
        "owner_account_id": owner,
        "custody_account_id": (
            settings.treasury_main_account
        ),
        "destination_id": request.destination_id,
        "currency": selected_currency,
        "amount": format(
            request.amount,
            "f",
        ),
    }

    # Idempotency is checked before any fresh Gate read.
    # A replay never creates another request record.
    try:
        existing = (
            find_matching_withdrawal_request(
                request_id=request.request_id,
                owner_account_id=owner,
                username=user.username,
                payload=audit_payload,
            )
        )

    except TreasuryWithdrawalIdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "gate_write_performed": False,
            },
        ) from exc

    if existing is not None:
        return {
            "phase": (
                "T2C3A_WITHDRAWAL_REQUEST_AUDIT"
            ),
            "status": "simulated_replay",
            "simulation": True,
            "idempotent_replay": True,
            "current_preflight_rechecked": False,
            "audit_recorded": True,
            "audit_created": False,
            "gate_write_performed": False,
            "transfers_enabled": False,
            "withdrawals_enabled": False,
            "executable": False,
            "audit": existing,
            "preflight": existing["preflight"],
        }

    # Reuse the exact destination-bound preflight accepted
    # in T2C.2B. This performs Gate GETs only.
    preflight_response = (
        await treasury_withdrawal_preflight(
            selected_currency,
            user=user,
            owner_account_id=owner,
            destination_id=(
                request.destination_id
            ),
            amount=request.amount,
        )
    )

    preflight = preflight_response[
        "preflight"
    ]

    base_response = {
        "phase": (
            "T2C3A_WITHDRAWAL_REQUEST_AUDIT"
        ),
        "status": (
            "ready"
            if preflight.get(
                "preflight_valid"
            )
            else "invalid"
        ),
        "simulation": True,
        "idempotent_replay": False,
        "gate_write_performed": False,
        "transfers_enabled": False,
        "withdrawals_enabled": False,
        "executable": False,
        "preflight": preflight,
    }

    if not preflight.get(
        "preflight_valid"
    ):
        return {
            **base_response,
            "audit_recorded": False,
            "audit_created": False,
        }

    destination = dict(
        preflight.get("destination")
        or {}
    )

    funding = dict(
        preflight.get("funding")
        or {}
    )

    fee = dict(
        preflight.get("fee")
        or {}
    )

    try:
        estimated_fee = Decimal(
            str(
                fee["estimated_fee"]
            )
        )

        conservative_required = Decimal(
            str(
                funding[
                    "conservative_funding_required"
                ]
            )
        )

        minimum_jit_transfer = Decimal(
            str(
                funding[
                    "minimum_jit_transfer"
                ]
            )
        )

        jit_required = bool(
            funding["jit_required"]
        )

        chain = str(
            destination["chain"]
        )

        address = str(
            destination["address"]
        )

        memo = str(
            destination.get("memo")
            or ""
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "message": (
                    "Valid withdrawal preflight "
                    "was missing required audit fields"
                ),
                "gate_write_performed": False,
            },
        ) from exc

    try:
        audit, created = (
            record_withdrawal_simulation(
                request_id=request.request_id,
                owner_account_id=owner,
                custody_account_id=(
                    settings.treasury_main_account
                ),
                username=user.username,
                destination_id=(
                    request.destination_id
                ),
                currency=selected_currency,
                chain=chain,
                address=address,
                memo=memo,
                amount=request.amount,
                estimated_fee=estimated_fee,
                conservative_funding_required=(
                    conservative_required
                ),
                minimum_jit_transfer=(
                    minimum_jit_transfer
                ),
                jit_required=jit_required,
                payload=audit_payload,
                preflight=preflight,
                destination_snapshot=(
                    destination
                ),
            )
        )

    except TreasuryWithdrawalIdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "gate_write_performed": False,
            },
        ) from exc

    return {
        **base_response,
        "audit_recorded": True,
        "audit_created": created,
        "audit": audit,
    }


@router.get(
    "/withdrawals/requests"
)
def treasury_withdrawal_requests(
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
        "phase": (
            "T2C3A_WITHDRAWAL_REQUEST_AUDIT"
        ),
        "withdrawals_enabled": False,
        "gate_write_performed": False,
        "items": list_withdrawal_requests(
            limit=limit,
            account_ids=account_ids,
        ),
    }


@router.get(
    "/withdrawals/requests/{request_id}"
)
def treasury_withdrawal_request_detail(
    request_id: str,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    row = get_withdrawal_request(
        request_id
    )

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Treasury withdrawal request "
                "not found"
            ),
        )

    require_account_access(
        user,
        row["owner_account_id"],
    )

    return {
        "phase": (
            "T2C3A_WITHDRAWAL_REQUEST_AUDIT"
        ),
        "withdrawals_enabled": False,
        "gate_write_performed": False,
        "item": row,
        "reconciliations": (
            list_withdrawal_reconciliations(
                request_id
            )
        ),
        "events": (
            list_withdrawal_request_events(
                request_id
            )
        ),
        "operation_lock": (
            get_withdrawal_lock_for_request(
                request_id
            )
        ),
    }


def _withdrawal_request_or_http(
    request_id: str,
) -> dict:
    row = get_withdrawal_request(
        request_id
    )

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Treasury withdrawal request "
                "not found"
            ),
        )

    return row


async def _fresh_request_preflight(
    *,
    row: dict,
    user: DashboardUser,
) -> dict:
    # The Numeric(48, 24) SQLite column can return a
    # logically integral amount such as 5 as
    # Decimal("5.000000000000000000000000").
    #
    # Withdrawal precision validation deliberately checks
    # the Decimal exponent, so do not use the DB storage
    # scale as the user's requested precision.
    #
    # request_json is the immutable, fingerprinted T2C.3A
    # caller-intent snapshot and preserves the canonical
    # amount text used during the original valid preflight.
    request_payload = row.get("request")

    if not isinstance(request_payload, dict):
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Stored withdrawal request is missing "
                    "its immutable request payload."
                ),
                "gate_write_performed": False,
            },
        )

    canonical_amount = as_decimal(
        request_payload.get("amount")
    )

    stored_amount = as_decimal(
        row.get("amount")
    )

    if (
        canonical_amount is None
        or stored_amount is None
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Stored withdrawal amount could not "
                    "be validated."
                ),
                "gate_write_performed": False,
            },
        )

    # Fail closed if the numeric DB column and immutable
    # caller-intent snapshot ever disagree.
    if stored_amount != canonical_amount:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Stored withdrawal amount does not "
                    "match the immutable request payload."
                ),
                "reason": (
                    "withdrawal_amount_snapshot_mismatch"
                ),
                "gate_write_performed": False,
            },
        )

    response = (
        await treasury_withdrawal_preflight(
            row["currency"],
            user=user,
            owner_account_id=(
                row["owner_account_id"]
            ),
            destination_id=(
                row["destination_id"]
            ),
            amount=canonical_amount,
        )
    )

    return response["preflight"]


@router.post(
    "/withdrawals/requests/{request_id}/reserve"
)
async def reserve_treasury_withdrawal_request(
    request_id: str,
    request: TreasuryWithdrawalReservationRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    row = _withdrawal_request_or_http(
        request_id
    )

    require_account_access(
        user,
        row["owner_account_id"],
    )

    if row["status"] in {
        "reserved",
        "confirmed_ready",
    }:
        lock = (
            get_withdrawal_lock_for_request(
                request_id
            )
        )

        if lock is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        "Withdrawal request state "
                        "requires an operation lock, "
                        "but no lock exists."
                    ),
                    "gate_write_performed": False,
                },
            )

        return {
            "phase": (
                "T2C3B_WITHDRAWAL_RESERVATION"
            ),
            "status": row["status"],
            "idempotent_replay": True,
            "current_preflight_rechecked": False,
            "gate_write_performed": False,
            "transfers_enabled": False,
            "withdrawals_enabled": False,
            "executable": False,
            "audit": row,
            "operation_lock": lock,
        }

    if row["status"] != "simulated":
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Withdrawal request is not "
                    "eligible for reservation."
                ),
                "status": row["status"],
                "gate_write_performed": False,
            },
        )

    required_confirmation = (
        withdrawal_reservation_confirmation_text(
            request_id
        )
    )

    if (
        request.confirmation
        != required_confirmation
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Invalid withdrawal reservation "
                    "confirmation text."
                ),
                "required_confirmation": (
                    required_confirmation
                ),
                "gate_write_performed": False,
            },
        )

    # Fresh Gate GET-only preflight. No lock exists yet.
    preflight = await _fresh_request_preflight(
        row=row,
        user=user,
    )

    if not preflight.get(
        "preflight_valid"
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Current withdrawal preflight "
                    "rejected the reservation."
                ),
                "errors": (
                    preflight.get("errors")
                    or []
                ),
                "gate_write_performed": False,
            },
        )

    mismatches = (
        destination_snapshot_mismatches(
            row,
            preflight,
        )
    )

    if mismatches:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Current withdrawal destination "
                    "does not match the immutable "
                    "request snapshot."
                ),
                "reason": (
                    "destination_snapshot_mismatch"
                ),
                "mismatches": mismatches,
                "gate_write_performed": False,
            },
        )

    try:
        lock = acquire_withdrawal_lock(
            owner_account_id=(
                row["owner_account_id"]
            ),
            custody_account_id=(
                row["custody_account_id"]
            ),
            currency=row["currency"],
            owner_request_id=request_id,
            username=user.username,
        )

    except TreasuryWithdrawalLocked as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Another unresolved withdrawal "
                    "already owns the main-account "
                    "custody/currency lock."
                ),
                "conflicting_lock": exc.lock,
                "gate_write_performed": False,
            },
        ) from exc

    try:
        audit, event, changed = (
            transition_withdrawal_request(
                request_id,
                expected_statuses={
                    "simulated",
                },
                new_status="reserved",
                username=user.username,
                action="reserved",
                details={
                    "preflight": preflight,
                    "operation_lock": lock,
                    "gate_write_performed": False,
                },
                simulation=False,
                completed=False,
            )
        )

    except TreasuryWithdrawalStateError as exc:
        # No Gate write has happened. Release only the
        # lock owned by this exact request.
        release_withdrawal_lock(
            custody_account_id=(
                row["custody_account_id"]
            ),
            currency=row["currency"],
            owner_request_id=request_id,
        )

        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "gate_write_performed": False,
            },
        ) from exc

    return {
        "phase": (
            "T2C3B_WITHDRAWAL_RESERVATION"
        ),
        "status": "reserved",
        "reservation_created": changed,
        "idempotent_replay": False,
        "current_preflight_rechecked": True,
        "gate_write_performed": False,
        "transfers_enabled": False,
        "withdrawals_enabled": False,
        "executable": False,
        "execution_block_reason": (
            "withdrawal_execution_not_enabled"
        ),
        "audit": audit,
        "event": event,
        "operation_lock": lock,
        "required_confirmation": (
            withdrawal_confirmation_text(
                audit
            )
        ),
    }


@router.post(
    "/withdrawals/requests/{request_id}/confirm"
)
async def confirm_treasury_withdrawal_request(
    request_id: str,
    request: TreasuryWithdrawalConfirmationRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    row = _withdrawal_request_or_http(
        request_id
    )

    require_account_access(
        user,
        row["owner_account_id"],
    )

    if row["status"] == "confirmed_ready":
        lock = (
            get_withdrawal_lock_for_request(
                request_id
            )
        )

        if lock is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        "Confirmed withdrawal request "
                        "has no operation lock."
                    ),
                    "gate_write_performed": False,
                },
            )

        return {
            "phase": (
                "T2C3B_WITHDRAWAL_RESERVATION"
            ),
            "status": "confirmed_ready",
            "idempotent_replay": True,
            "current_preflight_rechecked": False,
            "gate_write_performed": False,
            "withdrawals_enabled": False,
            "executable": False,
            "audit": row,
            "operation_lock": lock,
        }

    if row["status"] != "reserved":
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Withdrawal request must be "
                    "reserved before confirmation."
                ),
                "status": row["status"],
                "gate_write_performed": False,
            },
        )

    lock = get_withdrawal_lock_for_request(
        request_id
    )

    if lock is None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Reserved withdrawal request "
                    "has no operation lock."
                ),
                "gate_write_performed": False,
            },
        )

    required_confirmation = (
        withdrawal_confirmation_text(
            row
        )
    )

    if (
        request.confirmation
        != required_confirmation
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Invalid withdrawal confirmation "
                    "text."
                ),
                "required_confirmation": (
                    required_confirmation
                ),
                "gate_write_performed": False,
            },
        )

    # Confirmation gets another fresh Gate GET-only
    # preflight. A transient Gate error leaves the request
    # reserved and its lock held so the operator can retry
    # safely; there is still no ambiguous Gate write.
    preflight = await _fresh_request_preflight(
        row=row,
        user=user,
    )

    mismatches = (
        destination_snapshot_mismatches(
            row,
            preflight,
        )
    )

    if (
        not preflight.get(
            "preflight_valid"
        )
        or mismatches
    ):
        reason = (
            "Withdrawal confirmation was blocked "
            "by the fresh safety preflight."
        )

        try:
            audit, event, _changed = (
                transition_withdrawal_request(
                    request_id,
                    expected_statuses={
                        "reserved",
                    },
                    new_status="blocked",
                    username=user.username,
                    action="confirmation_blocked",
                    details={
                        "preflight": preflight,
                        "destination_snapshot_mismatches": (
                            mismatches
                        ),
                        "gate_write_performed": False,
                    },
                    error=reason,
                    simulation=False,
                    completed=True,
                )
            )

        except TreasuryWithdrawalStateError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(exc),
                    "gate_write_performed": False,
                },
            ) from exc

        released = (
            release_withdrawal_lock(
                custody_account_id=(
                    row["custody_account_id"]
                ),
                currency=row["currency"],
                owner_request_id=request_id,
            )
        )

        raise HTTPException(
            status_code=409,
            detail={
                "message": reason,
                "errors": (
                    preflight.get("errors")
                    or []
                ),
                "destination_snapshot_mismatches": (
                    mismatches
                ),
                "lock_released": released,
                "audit": audit,
                "event": event,
                "gate_write_performed": False,
            },
        )

    try:
        audit, event, changed = (
            transition_withdrawal_request(
                request_id,
                expected_statuses={
                    "reserved",
                },
                new_status="confirmed_ready",
                username=user.username,
                action="confirmed_ready",
                details={
                    "preflight": preflight,
                    "gate_write_performed": False,
                },
                simulation=False,
                completed=False,
            )
        )

    except TreasuryWithdrawalStateError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "gate_write_performed": False,
            },
        ) from exc

    return {
        "phase": (
            "T2C3B_WITHDRAWAL_RESERVATION"
        ),
        "status": "confirmed_ready",
        "confirmation_created": changed,
        "idempotent_replay": False,
        "current_preflight_rechecked": True,
        "gate_write_performed": False,
        "transfers_enabled": False,
        "withdrawals_enabled": False,
        "executable": False,
        "execution_block_reason": (
            "withdrawal_execution_not_enabled"
        ),
        "audit": audit,
        "event": event,
        "operation_lock": lock,
    }


@router.post(
    "/withdrawals/requests/{request_id}/jit/prepare"
)
async def prepare_treasury_withdrawal_jit(
    request_id: str,
    request: TreasuryWithdrawalReservationRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    row = _withdrawal_request_or_http(
        request_id
    )

    require_account_access(
        user,
        row["owner_account_id"],
    )

    # Exact replay of an already-prepared local JIT
    # snapshot. Do not re-read Gate and do not create
    # another lifecycle event.
    if row["status"] == "jit_prepared":
        lock = (
            get_withdrawal_lock_for_request(
                request_id
            )
        )

        if lock is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        "JIT-prepared withdrawal request "
                        "has no operation lock."
                    ),
                    "gate_write_performed": False,
                },
            )

        events = (
            list_withdrawal_request_events(
                request_id
            )
        )

        jit_event = next(
            (
                event
                for event in reversed(events)
                if event["action"]
                == "jit_prepared"
            ),
            None,
        )

        if jit_event is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        "JIT-prepared withdrawal request "
                        "has no preparation audit event."
                    ),
                    "gate_write_performed": False,
                },
            )

        jit_plan = (
            jit_event.get("details", {})
            .get("jit_plan")
        )

        if not isinstance(
            jit_plan,
            dict,
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        "Stored JIT preparation event "
                        "has no valid JIT plan."
                    ),
                    "gate_write_performed": False,
                },
            )

        return {
            "phase": (
                "T2C4B_JIT_PREPARATION"
            ),
            "status": "jit_prepared",
            "jit_preparation_created": False,
            "idempotent_replay": True,
            "current_preflight_rechecked": False,
            "gate_write_performed": False,
            "transfer_audit_created": False,
            "transfers_enabled": False,
            "withdrawals_enabled": False,
            "jit_execution_enabled": False,
            "executable": False,
            "execution_block_reason": (
                "jit_execution_not_enabled"
            ),
            "jit_plan": jit_plan,
            "audit": row,
            "event": jit_event,
            "operation_lock": lock,
        }

    if row["status"] != "confirmed_ready":
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Withdrawal request must be "
                    "confirmed before JIT preparation."
                ),
                "status": row["status"],
                "gate_write_performed": False,
            },
        )

    lock = get_withdrawal_lock_for_request(
        request_id
    )

    if lock is None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Confirmed withdrawal request "
                    "has no operation lock."
                ),
                "gate_write_performed": False,
            },
        )

    required_confirmation = (
        withdrawal_jit_preparation_confirmation_text(
            request_id
        )
    )

    if (
        request.confirmation
        != required_confirmation
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Invalid withdrawal JIT preparation "
                    "confirmation text."
                ),
                "required_confirmation": (
                    required_confirmation
                ),
                "gate_write_performed": False,
            },
        )

    # Another fresh GET-only withdrawal preflight.
    # This remains before any possible future JIT write.
    preflight = await _fresh_request_preflight(
        row=row,
        user=user,
    )

    mismatches = (
        destination_snapshot_mismatches(
            row,
            preflight,
        )
    )

    if (
        not preflight.get(
            "preflight_valid"
        )
        or mismatches
    ):
        reason = (
            "Withdrawal JIT preparation was blocked "
            "by the fresh safety preflight."
        )

        try:
            audit, event, _changed = (
                transition_withdrawal_request(
                    request_id,
                    expected_statuses={
                        "confirmed_ready",
                    },
                    new_status="blocked",
                    username=user.username,
                    action=(
                        "jit_preparation_blocked"
                    ),
                    details={
                        "preflight": preflight,
                        "destination_snapshot_mismatches": (
                            mismatches
                        ),
                        "gate_write_performed": False,
                        "transfer_audit_created": False,
                    },
                    error=reason,
                    simulation=False,
                    completed=True,
                )
            )

        except TreasuryWithdrawalStateError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(exc),
                    "gate_write_performed": False,
                },
            ) from exc

        released = (
            release_withdrawal_lock(
                custody_account_id=(
                    row["custody_account_id"]
                ),
                currency=row["currency"],
                owner_request_id=request_id,
            )
        )

        raise HTTPException(
            status_code=409,
            detail={
                "message": reason,
                "errors": (
                    preflight.get("errors")
                    or []
                ),
                "destination_snapshot_mismatches": (
                    mismatches
                ),
                "lock_released": released,
                "audit": audit,
                "event": event,
                "gate_write_performed": False,
                "transfer_audit_created": False,
            },
        )

    try:
        jit_plan = build_withdrawal_jit_plan(
            request=row,
            preflight=preflight,
        )

    except TreasuryWithdrawalJitPlanError as exc:
        reason = (
            "Withdrawal JIT preparation could not "
            "derive a safe JIT plan."
        )

        try:
            audit, event, _changed = (
                transition_withdrawal_request(
                    request_id,
                    expected_statuses={
                        "confirmed_ready",
                    },
                    new_status="blocked",
                    username=user.username,
                    action=(
                        "jit_preparation_blocked"
                    ),
                    details={
                        "preflight": preflight,
                        "jit_plan_error": str(exc),
                        "gate_write_performed": False,
                        "transfer_audit_created": False,
                    },
                    error=reason,
                    simulation=False,
                    completed=True,
                )
            )

        except TreasuryWithdrawalStateError as state_exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(state_exc),
                    "gate_write_performed": False,
                },
            ) from state_exc

        released = (
            release_withdrawal_lock(
                custody_account_id=(
                    row["custody_account_id"]
                ),
                currency=row["currency"],
                owner_request_id=request_id,
            )
        )

        raise HTTPException(
            status_code=409,
            detail={
                "message": reason,
                "jit_plan_error": str(exc),
                "lock_released": released,
                "audit": audit,
                "event": event,
                "gate_write_performed": False,
                "transfer_audit_created": False,
            },
        ) from exc

    try:
        audit, event, changed = (
            transition_withdrawal_request(
                request_id,
                expected_statuses={
                    "confirmed_ready",
                },
                new_status="jit_prepared",
                username=user.username,
                action="jit_prepared",
                details={
                    "preflight": preflight,
                    "jit_plan": jit_plan,
                    "gate_write_performed": False,
                    "transfer_audit_created": False,
                },
                simulation=False,
                completed=False,
            )
        )

    except TreasuryWithdrawalStateError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "gate_write_performed": False,
            },
        ) from exc

    return {
        "phase": "T2C4B_JIT_PREPARATION",
        "status": "jit_prepared",
        "jit_preparation_created": changed,
        "idempotent_replay": False,
        "current_preflight_rechecked": True,
        "gate_write_performed": False,
        "transfer_audit_created": False,
        "transfers_enabled": False,
        "withdrawals_enabled": False,
        "jit_execution_enabled": False,
        "executable": False,
        "execution_block_reason": (
            "jit_execution_not_enabled"
        ),
        "jit_plan": jit_plan,
        "audit": audit,
        "event": event,
        "operation_lock": lock,
    }


@router.post(
    "/withdrawals/requests/{request_id}/cancel"
)
def cancel_treasury_withdrawal_request(
    request_id: str,
    request: TreasuryWithdrawalCancellationRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    row = _withdrawal_request_or_http(
        request_id
    )

    require_account_access(
        user,
        row["owner_account_id"],
    )

    if row["status"] == "cancelled":
        return {
            "phase": (
                "T2C3B_WITHDRAWAL_RESERVATION"
            ),
            "status": "cancelled",
            "cancelled": False,
            "idempotent_replay": True,
            "gate_write_performed": False,
            "withdrawals_enabled": False,
            "executable": False,
            "audit": row,
            "operation_lock": (
                get_withdrawal_lock_for_request(
                    request_id
                )
            ),
        }

    if row["status"] not in {
        "reserved",
        "confirmed_ready",
        "jit_prepared",
    }:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Withdrawal request is not in "
                    "a cancellable state."
                ),
                "status": row["status"],
                "gate_write_performed": False,
            },
        )

    required_confirmation = (
        withdrawal_cancel_confirmation_text(
            request_id
        )
    )

    if (
        request.confirmation
        != required_confirmation
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Invalid withdrawal cancellation "
                    "confirmation text."
                ),
                "required_confirmation": (
                    required_confirmation
                ),
                "gate_write_performed": False,
            },
        )

    try:
        audit, event, changed = (
            transition_withdrawal_request(
                request_id,
                expected_statuses={
                    "reserved",
                    "confirmed_ready",
                    "jit_prepared",
                },
                new_status="cancelled",
                username=user.username,
                action="cancelled",
                details={
                    "reason": request.reason,
                    "gate_write_performed": False,
                },
                simulation=False,
                completed=True,
            )
        )

    except TreasuryWithdrawalStateError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "gate_write_performed": False,
            },
        ) from exc

    released = release_withdrawal_lock(
        custody_account_id=(
            row["custody_account_id"]
        ),
        currency=row["currency"],
        owner_request_id=request_id,
    )

    return {
        "phase": (
            "T2C3B_WITHDRAWAL_RESERVATION"
        ),
        "status": "cancelled",
        "cancelled": changed,
        "lock_released": released,
        "gate_write_performed": False,
        "withdrawals_enabled": False,
        "executable": False,
        "audit": audit,
        "event": event,
        "operation_lock": None,
    }


@router.get(
    "/withdrawals/locks"
)
def treasury_withdrawal_locks(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    owner_account_ids = (
        None
        if user.is_super_admin
        else set(user.account_ids)
    )

    return {
        "phase": (
            "T2C3B_WITHDRAWAL_RESERVATION"
        ),
        "gate_write_performed": False,
        "withdrawals_enabled": False,
        "items": list_withdrawal_locks(
            owner_account_ids=(
                owner_account_ids
            )
        ),
    }


@router.get(
    "/withdrawals/capabilities/{currency}"
)
async def treasury_withdrawal_capabilities(
    currency: str,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    owner_account_id: str = Query(
        ...,
        min_length=1,
        max_length=64,
    ),
):
    owner = require_account_access(
        user,
        owner_account_id,
    )

    source_account = get_gate_account(owner)

    if (
        source_account is None
        or not source_account.enabled
        or not source_account.configured
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Monitor credentials are not configured "
                f"for {owner}"
            ),
        )

    treasury_account = (
        _treasury_account_or_http()
    )

    selected_currency = _currency(currency)

    owner_main_held = ownership_amount(
        owner_account_id=owner,
        custody_account_id=(
            settings.treasury_main_account
        ),
        currency=selected_currency,
    )

    custody_liabilities = (
        custody_liability_amount(
            custody_account_id=(
                settings.treasury_main_account
            ),
            currency=selected_currency,
        )
    )

    try:
        # Economic owner's physical source balance:
        # always use that account's Monitor credential.
        async with GateClient(
            settings,
            source_account,
        ) as client:
            spot = await client.list_spot_accounts()

        # Withdrawal limits/status belong to the Gate main
        # account that would eventually execute withdrawal.
        # This remains a read-only Treasury operation.
        async with GateClient(
            settings,
            treasury_account,
        ) as client:
            main_spot = (
                await client.list_spot_accounts()
            )

            chains = await client.list_currency_chains(
                selected_currency
            )

            withdrawal_status = (
                await client.get_withdraw_status(
                    selected_currency
                )
            )

    except GateAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    capability = build_withdrawal_capabilities(
        owner_account_id=owner,
        main_account_id=(
            settings.treasury_main_account
        ),
        currency=selected_currency,
        spot_accounts=spot.data,
        main_spot_accounts=main_spot.data,
        raw_chains=chains.data,
        raw_withdraw_status=(
            withdrawal_status.data
        ),
        owner_main_held=owner_main_held,
        custody_liabilities=(
            custody_liabilities
        ),
    )

    return {
        "phase": "T2B_TRANSFER_CONTROL",
        "withdrawal_phase": (
            "T2C1A_CAPABILITIES_READ_ONLY"
        ),
        "gate_write_performed": False,
        "transfers_enabled": False,
        "withdrawals_enabled": False,
        "credential_profiles": {
            "source_balance": "monitor",
            "withdrawal_status": (
                "treasury_read_only"
            ),
        },
        **capability,
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
