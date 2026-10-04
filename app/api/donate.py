from __future__ import annotations

import asyncio
import logging
import time
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
)
from sqlalchemy.orm import Session

from ..accounts import (
    AccountConfigError,
    GateAccountConfig,
    get_gate_account,
)
from ..config import (
    Settings,
    get_settings,
)
from ..db import get_db
from ..donation_destinations import (
    has_trusted_public_destination,
    verify_public_destination,
)
from ..donations import (
    DONATION_ACCOUNT_ID,
    project_public_donation_catalog,
    project_public_donation_details,
)
from ..deposits import (
    build_deposit_details,
    merge_deposit_networks,
    normalize_currency_catalog,
    normalize_currency_symbol,
    select_network,
    utc_now_iso,
)
from ..gate_client import (
    GateAPIError,
    GateClient,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/donate",
    tags=["public donate"],
)


# Anonymous clients never receive a cache bypass.
# Cache the server-side Gate reads instead.
_catalog_cache: (
    tuple[
        float,
        Any,
        str,
    ]
    | None
) = None

_network_cache: dict[
    str,
    tuple[
        float,
        Any,
        str,
    ],
] = {}

_address_cache: dict[
    str,
    tuple[
        float,
        Any,
        str,
    ],
] = {}

_catalog_lock = asyncio.Lock()

_network_locks: dict[
    str,
    asyncio.Lock,
] = {}

_address_locks: dict[
    str,
    asyncio.Lock,
] = {}

_signed_refresh_lock = asyncio.Lock()

# The current deployment runs one Uvicorn application
# process. Serialize only the tiny durable trust
# verify+commit transaction used after a signed Gate read.
#
# Initial trust creation is never performed by public HTTP.
# Gate discovery and signed address reads remain outside
# this lock. If the deployment later adds multiple worker
# processes, add database-level conflict handling as well.
_destination_trust_lock = asyncio.Lock()

_last_signed_refresh_at = 0.0

# Prevent anonymous enumeration from creating an
# unbounded burst of signed Gate address requests.
SIGNED_REFRESH_MIN_INTERVAL_SECONDS = 1.0


def reset_donation_runtime_caches() -> None:
    """
    Test/runtime maintenance helper.

    This clears only process-memory read caches.
    It never alters durable destination trust.
    """

    global _catalog_cache
    global _last_signed_refresh_at

    _catalog_cache = None

    _network_cache.clear()
    _address_cache.clear()

    _network_locks.clear()
    _address_locks.clear()

    _last_signed_refresh_at = 0.0


def _no_store(
    response: Response,
) -> None:
    response.headers[
        "Cache-Control"
    ] = "no-store"


def _normalize_symbol(
    currency: str,
) -> str:
    try:
        return normalize_currency_symbol(
            currency
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid currency",
        ) from exc


def _donation_account() -> GateAccountConfig:
    try:
        account = get_gate_account(
            DONATION_ACCOUNT_ID
        )
    except AccountConfigError as exc:
        logger.error(
            "Public Donate account configuration "
            "could not be read: %s",
            exc,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "Donation destination "
                "temporarily unavailable"
            ),
        ) from exc

    if (
        account is None
        or not account.enabled
        or not account.configured
    ):
        logger.error(
            "Public Donate account is not "
            "enabled/configured"
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Donation destination "
                "temporarily unavailable"
            ),
        )

    return account


def _gate_unavailable(
    exc: GateAPIError,
) -> HTTPException:
    logger.warning(
        "Public Donate Gate read failed: %s",
        exc,
    )

    return HTTPException(
        status_code=503,
        detail=(
            "Donation data temporarily "
            "unavailable"
        ),
    )


async def _load_catalog(
    settings: Settings,
) -> tuple[Any, str]:
    global _catalog_cache

    ttl = max(
        1,
        settings.deposit_catalog_cache_seconds,
    )

    now = time.monotonic()

    if (
        _catalog_cache is not None
        and now - _catalog_cache[0]
        < ttl
    ):
        return (
            _catalog_cache[1],
            _catalog_cache[2],
        )

    async with _catalog_lock:
        now = time.monotonic()

        if (
            _catalog_cache is not None
            and now - _catalog_cache[0]
            < ttl
        ):
            return (
                _catalog_cache[1],
                _catalog_cache[2],
            )

        async with GateClient(
            settings
        ) as client:
            response = (
                await client.list_spot_currencies()
            )

        fetched_at = utc_now_iso()

        _catalog_cache = (
            time.monotonic(),
            response.data,
            fetched_at,
        )

        return (
            response.data,
            fetched_at,
        )


async def _load_networks(
    symbol: str,
    settings: Settings,
) -> tuple[Any, str]:
    ttl = max(
        1,
        settings.deposit_catalog_cache_seconds,
    )

    cached = _network_cache.get(
        symbol
    )

    now = time.monotonic()

    if (
        cached is not None
        and now - cached[0] < ttl
    ):
        return (
            cached[1],
            cached[2],
        )

    lock = _network_locks.setdefault(
        symbol,
        asyncio.Lock(),
    )

    async with lock:
        cached = _network_cache.get(
            symbol
        )

        now = time.monotonic()

        if (
            cached is not None
            and now - cached[0] < ttl
        ):
            return (
                cached[1],
                cached[2],
            )

        async with GateClient(
            settings
        ) as client:
            response = (
                await client.list_currency_chains(
                    symbol
                )
            )

        fetched_at = utc_now_iso()

        _network_cache[symbol] = (
            time.monotonic(),
            response.data,
            fetched_at,
        )

        return (
            response.data,
            fetched_at,
        )


async def _load_address(
    symbol: str,
    settings: Settings,
    account: GateAccountConfig,
) -> tuple[Any, str]:
    global _last_signed_refresh_at

    ttl = max(
        1,
        settings.deposit_address_cache_seconds,
    )

    cached = _address_cache.get(
        symbol
    )

    now = time.monotonic()

    if (
        cached is not None
        and now - cached[0] < ttl
    ):
        return (
            cached[1],
            cached[2],
        )

    lock = _address_locks.setdefault(
        symbol,
        asyncio.Lock(),
    )

    async with lock:
        cached = _address_cache.get(
            symbol
        )

        now = time.monotonic()

        if (
            cached is not None
            and now - cached[0] < ttl
        ):
            return (
                cached[1],
                cached[2],
            )

        async with _signed_refresh_lock:
            now = time.monotonic()

            wait_seconds = (
                SIGNED_REFRESH_MIN_INTERVAL_SECONDS
                - (
                    now
                    - _last_signed_refresh_at
                )
            )

            if wait_seconds > 0:
                await asyncio.sleep(
                    wait_seconds
                )

            # Rate-limit failed signed reads as well.
            _last_signed_refresh_at = (
                time.monotonic()
            )

            async with GateClient(
                settings,
                account,
            ) as client:
                response = (
                    await client.get_deposit_address(
                        symbol
                    )
                )

        fetched_at = utc_now_iso()

        _address_cache[symbol] = (
            time.monotonic(),
            response.data,
            fetched_at,
        )

        return (
            response.data,
            fetched_at,
        )


@router.get("/currencies")
async def public_donation_currencies(
    response: Response,
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
) -> dict[str, Any]:
    """
    Public sanitized Gate deposit-asset discovery.

    No authentication is required.
    No account-specific Gate credential is used.
    """

    _no_store(
        response
    )

    try:
        (
            raw,
            fetched_at,
        ) = await _load_catalog(
            settings
        )
    except GateAPIError as exc:
        raise _gate_unavailable(
            exc
        ) from exc

    normalized = normalize_currency_catalog(
        raw,
        settings.deposit_favorite_list,
    )

    normalized[
        "as_of"
    ] = fetched_at

    return project_public_donation_catalog(
        normalized
    )


@router.get("/{currency}/networks")
async def public_donation_networks(
    currency: str,
    response: Response,
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
) -> dict[str, Any]:
    """
    Public sanitized network discovery.

    Gate's currency-chain endpoint is unsigned.
    No EQTYDAO private API request is needed.
    """

    _no_store(
        response
    )

    symbol = _normalize_symbol(
        currency
    )

    try:
        (
            raw_chains,
            fetched_at,
        ) = await _load_networks(
            symbol,
            settings,
        )
    except GateAPIError as exc:
        raise _gate_unavailable(
            exc
        ) from exc

    normalized = normalize_currency_catalog(
        [
            {
                "currency": symbol,
                "name": symbol,
                "chains": raw_chains,
            }
        ],
        [],
    )

    projected = (
        project_public_donation_catalog(
            normalized
        )
    )

    currencies = projected.get(
        "currencies"
    ) or []

    networks = (
        currencies[0].get(
            "chains",
            [],
        )
        if currencies
        else []
    )

    return {
        "destination":
            projected["destination"],
        "currency": symbol,
        "as_of": fetched_at,
        "networks": networks,
    }


@router.get("/{currency}")
async def public_donation_address(
    currency: str,
    response: Response,
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
    chain: str = Query(
        min_length=1,
        max_length=64,
    ),
    db: Session = Depends(
        get_db
    ),
) -> dict[str, Any]:
    """
    Resolve one real EQTYDAO donation address.

    This endpoint is public but the server-side
    Gate account is permanently pinned to EQTYDAO.

    Only Gate GET operations occur:
      - unsigned currency-chain discovery
      - signed deposit-address read

    No caller can select another Wallet account.
    No refresh/bypass option is public.
    """

    _no_store(
        response
    )

    symbol = _normalize_symbol(
        currency
    )

    try:
        (
            raw_chains,
            _,
        ) = await _load_networks(
            symbol,
            settings,
        )
    except GateAPIError as exc:
        raise _gate_unavailable(
            exc
        ) from exc

    # Validate the requested chain and current
    # deposit availability before spending a
    # signed account-specific Gate read.
    try:
        selected = select_network(
            merge_deposit_networks(
                raw_chains
            ),
            chain,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                "Donation network not found"
            ),
        ) from exc

    if not selected.get(
        "deposit_enabled"
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Deposits are currently "
                "disabled for this network"
            ),
        )

    # Initial destination trust is established only by the
    # local operator bootstrap CLI. Fail closed here before
    # using the private EQTYDAO Gate credential.
    trust_chain = str(
        selected.get("chain")
        or selected.get("name")
        or chain
    ).strip()

    if not has_trusted_public_destination(
        db,
        currency=symbol,
        chain=trust_chain,
    ):
        logger.warning(
            "Public Donate destination is not "
            "operator-bootstrapped for %s/%s",
            symbol,
            trust_chain,
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Donation destination "
                "temporarily unavailable"
            ),
        )

    account = _donation_account()

    try:
        (
            raw_address,
            fetched_at,
        ) = await _load_address(
            symbol,
            settings,
            account,
        )
    except GateAPIError as exc:
        raise _gate_unavailable(
            exc
        ) from exc

    try:
        payload = build_deposit_details(
            account_id=
                DONATION_ACCOUNT_ID,
            display_name=
                "EQTY DAO Market Making",
            currency=symbol,
            selected_chain=chain,
            raw_chains=raw_chains,
            raw_address=raw_address,
            source="gate",
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                "Donation network not found"
            ),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Deposits are currently "
                "disabled for this network"
            ),
        ) from exc
    except RuntimeError as exc:
        logger.warning(
            "Public Donate address could "
            "not be constructed for %s/%s: %s",
            symbol,
            chain,
            exc,
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Donation destination "
                "temporarily unavailable"
            ),
        ) from exc

    # The timestamp describes the Gate address
    # read, not the later local projection.
    payload["as_of"] = fetched_at

    public_payload = (
        project_public_donation_details(
            payload
        )
    )

    # Keep durable verification/blocking state atomic with
    # respect to other anonymous requests in this process.
    # Initial trust creation is impossible through this path.
    async with _destination_trust_lock:
        decision = (
            verify_public_destination(
                db,
                payload,
            )
        )

        # Persist last verification metadata or a fail-closed
        # mismatch block before another request can verify.
        db.commit()

    if decision.state != "verified":
        logger.error(
            "Public Donate destination refused "
            "after trust verification for %s/%s: %s",
            symbol,
            chain,
            decision.state,
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Donation destination "
                "temporarily unavailable"
            ),
        )

    return public_payload
