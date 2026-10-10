from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
from collections import deque
from datetime import timedelta
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path as ApiPath,
    Query,
    Request,
    Response,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
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
from ..db import (
    get_db,
    utcnow,
)
from ..donation_ledger import (
    DONATION_TXID_MAX_LENGTH,
    INTENT_SUBMITTED,
    PUBLIC_LEDGER_DEFAULT_LIMIT,
    PUBLIC_LEDGER_MAX_LIMIT,
    PUBLIC_LEDGER_MAX_OFFSET,
    DonationLedgerInvariantError,
    create_donation_intent,
    read_public_donation_ledger,
    reconcile_external_donation_intent,
    submit_donation_intent_txid,
)
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

# Public intent creation/submission/reconciliation writes only
# local donation state. The current deployment uses one Uvicorn
# process, so serialize these small transactions here as well.
#
# If multiple application workers are introduced later, this
# must gain a database-level concurrency strategy before those
# workers are enabled.
_donation_intent_write_lock = asyncio.Lock()

# Anonymous DonationIntent writes have their own isolated
# process-local limiter. Do not reuse authentication rate
# storage: donation traffic must never consume login buckets.
_donation_rate_lock = asyncio.Lock()

_donation_rate_buckets: dict[
    tuple[
        str,
        str,
        str,
    ],
    deque[float],
] = {}

_donation_rate_last_cleanup_at = 0.0

_last_signed_refresh_at = 0.0

# Prevent anonymous enumeration from creating an
# unbounded burst of signed Gate address requests.
SIGNED_REFRESH_MIN_INTERVAL_SECONDS = 1.0

# Correlation capability lifetime. This is intentionally short:
# enough time for the donor to send and submit a transaction,
# while stale unclaimed intents naturally expire.
PUBLIC_DONATION_INTENT_TTL_SECONDS = 30 * 60

# Claim authority stays short-lived. Once a valid txid is
# submitted, the one-time claim is consumed and only local
# correlation for that immutable txid remains possible.
PUBLIC_DONATION_MATCH_TTL_SECONDS = (
    7 * 24 * 60 * 60
)

PUBLIC_DONATION_RATE_WINDOW_SECONDS = 60 * 60
PUBLIC_DONATION_RATE_CLEANUP_INTERVAL_SECONDS = 60

PUBLIC_DONATION_RATE_INTENT_CREATE = (
    "intent_create"
)
PUBLIC_DONATION_RATE_TXID_SUBMIT = (
    "txid_submit"
)
PUBLIC_DONATION_RATE_RECONCILE = (
    "reconcile"
)

PUBLIC_DONATION_RATE_POLICIES = {
    PUBLIC_DONATION_RATE_INTENT_CREATE: {
        "client_limit": 12,
        "global_limit": 60,
    },
    PUBLIC_DONATION_RATE_TXID_SUBMIT: {
        "client_limit": 60,
        "global_limit": 600,
    },
    PUBLIC_DONATION_RATE_RECONCILE: {
        "client_limit": 360,
        "global_limit": 3600,
    },
}


class DonationPublicRateLimitExceeded(
    RuntimeError
):
    def __init__(
        self,
        *,
        action: str,
        scope: str,
        retry_after_seconds: int,
    ) -> None:
        self.action = action
        self.scope = scope
        self.retry_after_seconds = max(
            1,
            int(
                retry_after_seconds
            ),
        )

        super().__init__(
            "Public donation rate limit exceeded"
        )


class DonationIntentCreateRequest(
    BaseModel
):
    model_config = ConfigDict(
        extra="forbid"
    )

    currency: str = Field(
        min_length=1,
        max_length=32,
    )

    chain: str = Field(
        min_length=1,
        max_length=128,
    )


class DonationIntentTxidRequest(
    BaseModel
):
    model_config = ConfigDict(
        extra="forbid"
    )

    claim_token: str = Field(
        min_length=1,
        max_length=1024,
    )

    txid: str = Field(
        min_length=1,
        max_length=DONATION_TXID_MAX_LENGTH,
    )


def reset_donation_runtime_caches() -> None:
    """
    Test/runtime maintenance helper.

    This clears only process-memory read caches.
    It never alters durable destination trust.
    """

    global _catalog_cache
    global _last_signed_refresh_at
    global _donation_rate_last_cleanup_at

    _catalog_cache = None

    _network_cache.clear()
    _address_cache.clear()

    _network_locks.clear()
    _address_locks.clear()

    _donation_rate_buckets.clear()
    _donation_rate_last_cleanup_at = 0.0

    _last_signed_refresh_at = 0.0


def _no_store(
    response: Response,
) -> None:
    response.headers[
        "Cache-Control"
    ] = "no-store"


def _request_client_identifier(
    request: Request,
) -> str:
    """
    Use only Starlette/Uvicorn's normalized socket identity.

    The application deliberately does not parse forwarding
    headers. Proxy trust belongs exclusively at the Uvicorn
    boundary.
    """
    client = request.client

    if client is None:
        return "<unknown>"

    value = str(
        client.host
        or ""
    ).strip()

    return value or "<unknown>"


def _public_donation_client_key(
    client_identifier: str,
) -> str:
    normalized = str(
        client_identifier
        or "<unknown>"
    ).strip().lower()

    if not normalized:
        normalized = "<unknown>"

    return hashlib.sha256(
        normalized.encode(
            "utf-8"
        )
    ).hexdigest()


def _prune_public_donation_bucket(
    bucket: deque[float],
    *,
    now: float,
) -> None:
    cutoff = (
        now
        - PUBLIC_DONATION_RATE_WINDOW_SECONDS
    )

    while (
        bucket
        and bucket[0] <= cutoff
    ):
        bucket.popleft()


def _public_donation_retry_after(
    bucket: deque[float],
    *,
    now: float,
) -> int:
    if not bucket:
        return 1

    remaining = (
        PUBLIC_DONATION_RATE_WINDOW_SECONDS
        - (
            now
            - bucket[0]
        )
    )

    return max(
        1,
        int(
            math.ceil(
                remaining
            )
        ),
    )


def _cleanup_public_donation_rate_buckets(
    *,
    now: float,
) -> None:
    for key, bucket in list(
        _donation_rate_buckets.items()
    ):
        _prune_public_donation_bucket(
            bucket,
            now=now,
        )

        if not bucket:
            _donation_rate_buckets.pop(
                key,
                None,
            )


async def _reserve_public_donation_rate_slot(
    *,
    action: str,
    client_identifier: str,
    now: float | None = None,
) -> None:
    """
    Reserve one anonymous public-write attempt.

    Both client and global ceilings are enforced. A global
    bucket means rotating source addresses cannot remove the
    aggregate bound.

    Only a SHA-256 client key is retained in process memory.
    """
    global _donation_rate_last_cleanup_at

    policy = (
        PUBLIC_DONATION_RATE_POLICIES.get(
            action
        )
    )

    if policy is None:
        raise RuntimeError(
            "Unknown public donation rate-limit action"
        )

    reference = (
        float(
            now
        )
        if now is not None
        else time.monotonic()
    )

    client_key = (
        _public_donation_client_key(
            client_identifier
        )
    )

    async with _donation_rate_lock:
        if (
            reference
            < _donation_rate_last_cleanup_at
            or (
                reference
                - _donation_rate_last_cleanup_at
            )
            >= (
                PUBLIC_DONATION_RATE_CLEANUP_INTERVAL_SECONDS
            )
        ):
            _cleanup_public_donation_rate_buckets(
                now=reference
            )

            _donation_rate_last_cleanup_at = (
                reference
            )

        global_key = (
            action,
            "global",
            "*",
        )

        global_bucket = (
            _donation_rate_buckets.setdefault(
                global_key,
                deque(),
            )
        )

        _prune_public_donation_bucket(
            global_bucket,
            now=reference,
        )

        if (
            len(
                global_bucket
            )
            >= int(
                policy[
                    "global_limit"
                ]
            )
        ):
            raise DonationPublicRateLimitExceeded(
                action=action,
                scope="global",
                retry_after_seconds=(
                    _public_donation_retry_after(
                        global_bucket,
                        now=reference,
                    )
                ),
            )

        client_bucket_key = (
            action,
            "client",
            client_key,
        )

        client_bucket = (
            _donation_rate_buckets.setdefault(
                client_bucket_key,
                deque(),
            )
        )

        _prune_public_donation_bucket(
            client_bucket,
            now=reference,
        )

        if (
            len(
                client_bucket
            )
            >= int(
                policy[
                    "client_limit"
                ]
            )
        ):
            raise DonationPublicRateLimitExceeded(
                action=action,
                scope="client",
                retry_after_seconds=(
                    _public_donation_retry_after(
                        client_bucket,
                        now=reference,
                    )
                ),
            )

        global_bucket.append(
            reference
        )

        client_bucket.append(
            reference
        )


async def _enforce_public_donation_rate_limit(
    request: Request,
    *,
    action: str,
) -> None:
    try:
        await _reserve_public_donation_rate_slot(
            action=action,
            client_identifier=(
                _request_client_identifier(
                    request
                )
            ),
        )

    except DonationPublicRateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="Too many donation requests",
            headers={
                "Retry-After":
                    str(
                        exc.retry_after_seconds
                    ),
                "Cache-Control":
                    "no-store",
            },
        ) from exc


def _intent_http_error(
    exc: DonationLedgerInvariantError,
    *,
    operation: str,
) -> HTTPException:
    """
    Map internal correlation invariants to a small public error
    surface without exposing private matching details.
    """
    message = str(
        exc
    )

    if message == "Donation intent not found":
        return HTTPException(
            status_code=404,
            detail="Donation intent not found",
        )

    if message == "Invalid donation claim token":
        return HTTPException(
            status_code=403,
            detail="Invalid donation claim token",
        )

    if operation == "create":
        return HTTPException(
            status_code=400,
            detail="Invalid donation intent",
        )

    return HTTPException(
        status_code=409,
        detail="Donation intent cannot be updated",
    )


def _public_created_intent(
    public: dict[str, Any],
) -> dict[str, Any]:
    """
    Give creation the same safe public shape used by later
    correlation responses.

    No claim hash or submitted txid is ever included.
    """
    result = dict(
        public
    )

    result[
        "txid_submitted"
    ] = False

    result[
        "matched_event_id"
    ] = None

    result[
        "matched_at"
    ] = None

    result[
        "updated_at"
    ] = result.get(
        "created_at"
    )

    result[
        "match_status"
    ] = "pending"

    return result


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


@router.get("/ledger")
def public_donation_ledger_view(
    response: Response,
    include_demo: bool = Query(
        default=False,
    ),
    limit: int = Query(
        default=PUBLIC_LEDGER_DEFAULT_LIMIT,
        ge=1,
        le=PUBLIC_LEDGER_MAX_LIMIT,
    ),
    offset: int = Query(
        default=0,
        ge=0,
        le=PUBLIC_LEDGER_MAX_OFFSET,
    ),
    db: Session = Depends(
        get_db
    ),
) -> dict[str, Any]:
    """
    Public read-only Donation Ledger.

    This endpoint reads only locally confirmed DonationEvent
    rows and their optional display attribution.

    It performs no Gate request and contains no write path.
    """

    _no_store(
        response
    )

    return read_public_donation_ledger(
        db,
        include_demo=include_demo,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/intents",
    status_code=201,
)
async def public_create_donation_intent(
    payload: DonationIntentCreateRequest,
    request: Request,
    response: Response,
    db: Session = Depends(
        get_db
    ),
) -> dict[str, Any]:
    """
    Create one short-lived external donation correlation intent.

    The requested destination must already exist in operator-
    controlled public donation trust.

    This endpoint performs no Gate request.
    """
    _no_store(
        response
    )

    await _enforce_public_donation_rate_limit(
        request,
        action=(
            PUBLIC_DONATION_RATE_INTENT_CREATE
        ),
    )

    symbol = _normalize_symbol(
        payload.currency
    )

    chain = str(
        payload.chain
    ).strip()

    if not chain:
        raise HTTPException(
            status_code=400,
            detail="Invalid donation network",
        )

    if not has_trusted_public_destination(
        db,
        currency=symbol,
        chain=chain,
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Donation destination "
                "temporarily unavailable"
            ),
        )

    now = utcnow()

    async with _donation_intent_write_lock:
        try:
            public, claim_token = (
                create_donation_intent(
                    db,
                    currency=symbol,
                    chain_key=chain,
                    chain=chain,
                    expires_at=(
                        now
                        + timedelta(
                            seconds=(
                                PUBLIC_DONATION_INTENT_TTL_SECONDS
                            )
                        )
                    ),
                    now=now,
                )
            )

            db.commit()

        except DonationLedgerInvariantError as exc:
            db.rollback()

            raise _intent_http_error(
                exc,
                operation="create",
            ) from exc

        except Exception:
            db.rollback()
            raise

    return {
        "intent":
            _public_created_intent(
                public
            ),
        # Returned once. Only its SHA-256 hash was persisted
        # before create_donation_intent() committed.
        "claim_token":
            claim_token,
    }


@router.post(
    "/intents/{intent_id}/txid",
)
async def public_submit_donation_txid(
    payload: DonationIntentTxidRequest,
    request: Request,
    response: Response,
    intent_id: str = ApiPath(
        min_length=1,
        max_length=96,
    ),
    db: Session = Depends(
        get_db
    ),
) -> dict[str, Any]:
    """
    Bind one txid through the one-time claim token.

    The accepted binding is committed before correlation is
    attempted. If local deposit history does not contain the
    deposit yet, the intent remains submitted and can be
    reconciled later.

    No Gate request or deposit sync occurs.
    """
    _no_store(
        response
    )

    await _enforce_public_donation_rate_limit(
        request,
        action=(
            PUBLIC_DONATION_RATE_TXID_SUBMIT
        ),
    )

    now = utcnow()

    async with _donation_intent_write_lock:
        try:
            submitted = (
                submit_donation_intent_txid(
                    db,
                    intent_id=intent_id,
                    claim_token=(
                        payload.claim_token
                    ),
                    txid=payload.txid,
                    now=now,
                    match_expires_at=(
                        now
                        + timedelta(
                            seconds=(
                                PUBLIC_DONATION_MATCH_TTL_SECONDS
                            )
                        )
                    ),
                )
            )

            # Persist claim consumption / txid binding first.
            # This survives a later inconclusive correlation.
            db.commit()

        except DonationLedgerInvariantError as exc:
            db.rollback()

            raise _intent_http_error(
                exc,
                operation="submit",
            ) from exc

        except Exception:
            db.rollback()
            raise

        if (
            submitted.get(
                "status"
            )
            != INTENT_SUBMITTED
        ):
            return {
                "intent": submitted
            }

        try:
            reconciled = (
                reconcile_external_donation_intent(
                    db,
                    intent_id=intent_id,
                )
            )

            db.commit()

        except DonationLedgerInvariantError as exc:
            # The submitted binding was already committed.
            # Roll back only this reconciliation transaction.
            db.rollback()

            raise _intent_http_error(
                exc,
                operation="reconcile",
            ) from exc

        except Exception:
            db.rollback()
            raise

    return {
        "intent": reconciled
    }


@router.post(
    "/intents/{intent_id}/reconcile",
)
async def public_reconcile_donation_intent(
    request: Request,
    response: Response,
    intent_id: str = ApiPath(
        min_length=1,
        max_length=96,
    ),
    db: Session = Depends(
        get_db
    ),
) -> dict[str, Any]:
    """
    Retry local-only correlation for one submitted intent.

    The opaque intent id is the retry capability after the
    one-time claim token has been consumed.

    No Gate request or deposit sync occurs.
    """
    _no_store(
        response
    )

    await _enforce_public_donation_rate_limit(
        request,
        action=(
            PUBLIC_DONATION_RATE_RECONCILE
        ),
    )

    async with _donation_intent_write_lock:
        try:
            result = (
                reconcile_external_donation_intent(
                    db,
                    intent_id=intent_id,
                )
            )

            db.commit()

        except DonationLedgerInvariantError as exc:
            db.rollback()

            raise _intent_http_error(
                exc,
                operation="reconcile",
            ) from exc

        except Exception:
            db.rollback()
            raise

    return {
        "intent": result
    }


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
