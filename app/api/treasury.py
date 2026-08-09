from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

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
        "phase": "T1_READ_ONLY",
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
        "phase": "T1_READ_ONLY",
        "main_account": settings.treasury_main_account,
        "currency": selected_currency,
        "chains": response.raw,
        "transfers_enabled": False,
        "withdrawals_enabled": False,
    }
