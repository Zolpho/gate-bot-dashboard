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
    require_user,
)
from ..treasury import (
    TreasuryConfigError,
    get_treasury_account,
    safe_treasury_config,
)
from ..treasury_transfer import (
    TreasuryTransferValidationError,
    build_subaccount_to_main_preflight,
    gate_client_order_id,
)
from ..treasury_transfer_audit import (
    TreasuryTransferIdempotencyConflict,
    get_transfer_request,
    list_transfer_requests,
    record_simulation,
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
        "phase": "T2A_SIMULATION",
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
        "phase": "T2A_SIMULATION",
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
        "phase": "T2A_SIMULATION",
        "item": row,
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
        "phase": "T2A_SIMULATION",
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
        "phase": "T2A_SIMULATION",
        "main_account": settings.treasury_main_account,
        "currency": selected_currency,
        "chains": response.raw,
        "transfers_enabled": False,
        "withdrawals_enabled": False,
    }
