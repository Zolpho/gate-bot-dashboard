from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..accounts import AccountConfigError, get_gate_account
from ..config import Settings, get_settings
from ..db import get_db, session_scope
from ..deposits import (
    DEMO_CURRENCIES,
    build_deposit_details,
    demo_address,
    demo_chains,
    merge_deposit_networks,
    normalize_currency_catalog,
    normalize_currency_symbol,
    utc_now_iso,
)
from ..deposit_history import persist_deposit_address
from ..gate_client import GateAPIError, GateClient
from ..models import GateAccount
from ..security import DashboardUser, require_user, resolve_authorized_account


router = APIRouter(prefix="/api/deposit", tags=["deposit"])
private_router = APIRouter(
    prefix="/api/me/deposit",
    tags=["private account deposit"],
)

_catalog_cache: tuple[float, dict[str, Any]] | None = None
_catalog_lock = asyncio.Lock()
_address_cache: dict[
    tuple[str, str, str],
    tuple[float, dict[str, Any]],
] = {}
_address_locks: dict[tuple[str, str, str], asyncio.Lock] = {}


def _account_context(
    user: DashboardUser,
    requested_account_id: str | None,
    db: Session,
) -> tuple[str, str]:
    selected_account_id = resolve_authorized_account(
        user,
        requested_account_id,
    )
    if selected_account_id is None:
        raise HTTPException(
            status_code=400,
            detail="Select one assigned account",
        )

    account_row = db.get(GateAccount, selected_account_id)
    display_name = (
        account_row.name
        if account_row is not None
        else selected_account_id
    )
    return selected_account_id, display_name


@router.get("/currencies")
async def deposit_currencies(
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    global _catalog_cache

    favorites = settings.deposit_favorite_list

    if settings.demo_mode:
        payload = normalize_currency_catalog(DEMO_CURRENCIES, favorites)
        payload["source"] = "demo"
        payload["cache"] = {"hit": False, "ttl_seconds": 0}
        return payload

    now = time.monotonic()
    if (
        _catalog_cache
        and now - _catalog_cache[0]
        < settings.deposit_catalog_cache_seconds
    ):
        payload = dict(_catalog_cache[1])
        payload["cache"] = {
            "hit": True,
            "ttl_seconds": settings.deposit_catalog_cache_seconds,
        }
        return payload

    async with _catalog_lock:
        now = time.monotonic()
        if (
            _catalog_cache
            and now - _catalog_cache[0]
            < settings.deposit_catalog_cache_seconds
        ):
            payload = dict(_catalog_cache[1])
            payload["cache"] = {
                "hit": True,
                "ttl_seconds": settings.deposit_catalog_cache_seconds,
            }
            return payload

        try:
            async with GateClient(settings) as client:
                response = await client.list_spot_currencies()
        except GateAPIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        payload = normalize_currency_catalog(response.data, favorites)
        payload["source"] = "gate"
        payload["cache"] = {
            "hit": False,
            "ttl_seconds": settings.deposit_catalog_cache_seconds,
        }
        _catalog_cache = (time.monotonic(), payload)
        return payload


@private_router.get("/{currency}/networks")
async def my_deposit_networks(
    currency: str,
    user: Annotated[DashboardUser, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    account_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    selected_account_id, display_name = _account_context(
        user,
        account_id,
        db,
    )

    try:
        symbol = normalize_currency_symbol(currency)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if settings.demo_mode:
        networks = merge_deposit_networks(demo_chains(symbol))
    else:
        try:
            async with GateClient(settings) as client:
                response = await client.list_currency_chains(symbol)
        except GateAPIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        networks = merge_deposit_networks(response.data)

    return {
        "account_id": selected_account_id,
        "display_name": display_name,
        "currency": symbol,
        "as_of": utc_now_iso(),
        "networks": networks,
        "authorized_user": user.safe_dict(),
    }


@private_router.get("/{currency}")
async def my_deposit_address(
    currency: str,
    user: Annotated[DashboardUser, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    chain: str = Query(min_length=1, max_length=64),
    account_id: str | None = Query(default=None),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    selected_account_id, display_name = _account_context(
        user,
        account_id,
        db,
    )

    try:
        symbol = normalize_currency_symbol(currency)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    cache_key = (
        selected_account_id,
        symbol,
        chain.upper(),
    )
    now = time.monotonic()
    cached = _address_cache.get(cache_key)

    if (
        not refresh
        and cached
        and now - cached[0]
        < settings.deposit_address_cache_seconds
    ):
        payload = dict(cached[1])
        payload["cache"] = {
            "hit": True,
            "ttl_seconds": settings.deposit_address_cache_seconds,
        }
        payload["authorized_user"] = user.safe_dict()
        return payload

    lock = _address_locks.setdefault(cache_key, asyncio.Lock())

    async with lock:
        now = time.monotonic()
        cached = _address_cache.get(cache_key)

        if (
            not refresh
            and cached
            and now - cached[0]
            < settings.deposit_address_cache_seconds
        ):
            payload = dict(cached[1])
            payload["cache"] = {
                "hit": True,
                "ttl_seconds": settings.deposit_address_cache_seconds,
            }
            payload["authorized_user"] = user.safe_dict()
            return payload

        if settings.demo_mode:
            raw_chains = demo_chains(symbol)
            raw_address = demo_address(symbol)
            source = "demo"
        else:
            try:
                account = get_gate_account(selected_account_id)
            except AccountConfigError as exc:
                raise HTTPException(
                    status_code=503,
                    detail=str(exc),
                ) from exc

            if (
                account is None
                or not account.enabled
                or not account.configured
            ):
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Gate credentials are not configured for "
                        f"account {selected_account_id}"
                    ),
                )

            try:
                async with GateClient(settings, account) as client:
                    chain_response, address_response = await asyncio.gather(
                        client.list_currency_chains(symbol),
                        client.get_deposit_address(symbol),
                    )
            except GateAPIError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=str(exc),
                ) from exc

            raw_chains = chain_response.data
            raw_address = address_response.data
            source = "gate"

        try:
            payload = build_deposit_details(
                account_id=selected_account_id,
                display_name=display_name,
                currency=symbol,
                selected_chain=chain,
                raw_chains=raw_chains,
                raw_address=raw_address,
                source=source,
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=404,
                detail=str(exc),
            ) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=502,
                detail=str(exc),
            ) from exc

        with session_scope() as address_session:
            persist_deposit_address(
                address_session,
                account_id=selected_account_id,
                currency=symbol,
                network=payload["network"],
                minimum_deposit_amount=payload.get("minimum_deposit_amount"),
            )

        payload["cache"] = {
            "hit": False,
            "ttl_seconds": settings.deposit_address_cache_seconds,
        }
        _address_cache[cache_key] = (time.monotonic(), payload)
        payload["authorized_user"] = user.safe_dict()
        return payload
