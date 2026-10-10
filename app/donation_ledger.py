from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .db import utcnow
from .exact_decimal import exact_decimal_text
from .models import (
    DonationAttribution,
    DonationEvent,
    DonationIntent,
)


DONATION_ACCOUNT_ID = "eqtydao"

SOURCE_EXTERNAL_DEPOSIT = "external_deposit"
SOURCE_INTERNAL_TRANSFER = "internal_transfer"
SOURCE_DEMO = "demo"

DONATION_SOURCE_TYPES = frozenset(
    {
        SOURCE_EXTERNAL_DEPOSIT,
        SOURCE_INTERNAL_TRANSFER,
        SOURCE_DEMO,
    }
)

INTENT_PENDING = "pending"

CLAIM_TOKEN_BYTES = 32


class DonationLedgerInvariantError(ValueError):
    pass


def _required_text(
    value: Any,
    *,
    field: str,
    max_length: int,
) -> str:
    text = str(
        value
        or ""
    ).strip()

    if not text:
        raise DonationLedgerInvariantError(
            f"{field} is required"
        )

    if len(text) > max_length:
        raise DonationLedgerInvariantError(
            f"{field} exceeds {max_length} characters"
        )

    return text


def _utc_datetime(
    value: datetime,
    *,
    field: str,
) -> datetime:
    if not isinstance(
        value,
        datetime,
    ):
        raise DonationLedgerInvariantError(
            f"{field} must be a datetime"
        )

    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def _positive_amount(
    value: Any,
) -> Decimal:
    try:
        text = exact_decimal_text(
            value,
            precision=48,
            scale=24,
        )
    except ValueError as exc:
        raise DonationLedgerInvariantError(
            "Donation amount is invalid"
        ) from exc

    amount = Decimal(text)

    if amount <= 0:
        raise DonationLedgerInvariantError(
            "Donation amount must be greater than zero"
        )

    return amount


def normalize_currency(
    currency: str,
) -> str:
    return _required_text(
        currency,
        field="currency",
        max_length=32,
    ).upper()


def normalize_chain_key(
    chain_key: str,
) -> str:
    return _required_text(
        chain_key,
        field="chain_key",
        max_length=128,
    ).upper()


def normalize_chain(
    chain: str,
) -> str:
    return _required_text(
        chain,
        field="chain",
        max_length=128,
    )


def external_deposit_source_key(
    account_id: str,
    gate_deposit_id: str,
) -> str:
    account = _required_text(
        account_id,
        field="account_id",
        max_length=64,
    ).lower()

    if account != DONATION_ACCOUNT_ID:
        raise DonationLedgerInvariantError(
            "External donation source account must be eqtydao"
        )

    deposit_id = _required_text(
        gate_deposit_id,
        field="gate_deposit_id",
        max_length=128,
    )

    return (
        DONATION_ACCOUNT_ID
        + ":"
        + deposit_id
    )


def internal_transfer_source_key(
    request_id: str,
) -> str:
    request = _required_text(
        request_id,
        field="request_id",
        max_length=128,
    )

    return "request:" + request


def demo_source_key(
    demo_id: str,
) -> str:
    identifier = _required_text(
        demo_id,
        field="demo_id",
        max_length=128,
    )

    return "demo:" + identifier


def donation_event_id(
    source_type: str,
    source_key: str,
) -> str:
    source = _required_text(
        source_type,
        field="source_type",
        max_length=32,
    ).lower()

    if source not in DONATION_SOURCE_TYPES:
        raise DonationLedgerInvariantError(
            "Unsupported donation source type"
        )

    key = _required_text(
        source_key,
        field="source_key",
        max_length=320,
    )

    digest = hashlib.sha256(
        (
            source
            + "\0"
            + key
        ).encode("utf-8")
    ).hexdigest()

    return "don_evt_" + digest


def _validate_source_key(
    source_type: str,
    source_key: str,
) -> None:
    if (
        source_type
        == SOURCE_EXTERNAL_DEPOSIT
        and not source_key.startswith(
            DONATION_ACCOUNT_ID + ":"
        )
    ):
        raise DonationLedgerInvariantError(
            "External donation source key must be EQTYDAO deposit identity"
        )

    if (
        source_type
        == SOURCE_INTERNAL_TRANSFER
        and not source_key.startswith(
            "request:"
        )
    ):
        raise DonationLedgerInvariantError(
            "Internal donation source key must derive from request_id"
        )

    if (
        source_type
        == SOURCE_DEMO
        and not source_key.startswith(
            "demo:"
        )
    ):
        raise DonationLedgerInvariantError(
            "Demo donation source key must derive from demo id"
        )


def _event_snapshot(
    row: DonationEvent,
) -> dict[str, Any]:
    return {
        "event_id": row.event_id,
        "source_type": row.source_type,
        "source_key": row.source_key,
        "currency": row.currency,
        "chain_key": row.chain_key,
        "chain": row.chain,
        "amount": exact_decimal_text(
            row.amount,
            precision=48,
            scale=24,
        ),
        "occurred_at": _utc_datetime(
            row.occurred_at,
            field="occurred_at",
        ).isoformat(),
        "demo": bool(row.demo),
        "created_at": (
            _utc_datetime(
                row.created_at,
                field="created_at",
            ).isoformat()
            if row.created_at
            else None
        ),
    }


def ensure_donation_event(
    db: Session,
    *,
    source_type: str,
    source_key: str,
    currency: str,
    amount: Any,
    occurred_at: datetime,
    chain_key: str = "",
    chain: str = "",
    demo: bool = False,
) -> tuple[
    dict[str, Any],
    bool,
]:
    source = _required_text(
        source_type,
        field="source_type",
        max_length=32,
    ).lower()

    if source not in DONATION_SOURCE_TYPES:
        raise DonationLedgerInvariantError(
            "Unsupported donation source type"
        )

    key = _required_text(
        source_key,
        field="source_key",
        max_length=320,
    )

    _validate_source_key(
        source,
        key,
    )

    is_demo = bool(
        demo
    )

    if (
        source == SOURCE_DEMO
    ) != is_demo:
        raise DonationLedgerInvariantError(
            "Demo source type and demo flag must agree"
        )

    symbol = normalize_currency(
        currency
    )

    normalized_amount = _positive_amount(
        amount
    )

    occurred = _utc_datetime(
        occurred_at,
        field="occurred_at",
    )

    normalized_chain_key = (
        str(
            chain_key
            or ""
        )
        .strip()
        .upper()
    )

    normalized_chain = str(
        chain
        or ""
    ).strip()

    if source == SOURCE_EXTERNAL_DEPOSIT:
        normalized_chain_key = normalize_chain_key(
            normalized_chain_key
        )

        normalized_chain = normalize_chain(
            normalized_chain
        )

    if len(
        normalized_chain_key
    ) > 128:
        raise DonationLedgerInvariantError(
            "chain_key exceeds 128 characters"
        )

    if len(
        normalized_chain
    ) > 128:
        raise DonationLedgerInvariantError(
            "chain exceeds 128 characters"
        )

    event_id = donation_event_id(
        source,
        key,
    )

    existing = db.scalar(
        select(
            DonationEvent
        ).where(
            DonationEvent.source_type
            == source,
            DonationEvent.source_key
            == key,
        )
    )

    expected = {
        "event_id": event_id,
        "source_type": source,
        "source_key": key,
        "currency": symbol,
        "chain_key": normalized_chain_key,
        "chain": normalized_chain,
        "amount": exact_decimal_text(
            normalized_amount,
            precision=48,
            scale=24,
        ),
        "occurred_at": occurred.isoformat(),
        "demo": is_demo,
    }

    if existing is not None:
        current = _event_snapshot(
            existing
        )

        comparable = {
            key_name: current[
                key_name
            ]
            for key_name in expected
        }

        if comparable != expected:
            raise DonationLedgerInvariantError(
                "Donation source identity conflicts with existing immutable event"
            )

        return current, False

    collision = db.scalar(
        select(
            DonationEvent
        ).where(
            DonationEvent.event_id
            == event_id
        )
    )

    if collision is not None:
        raise DonationLedgerInvariantError(
            "Donation event id collision"
        )

    row = DonationEvent(
        event_id=event_id,
        source_type=source,
        source_key=key,
        currency=symbol,
        chain_key=normalized_chain_key,
        chain=normalized_chain,
        amount=normalized_amount,
        occurred_at=occurred,
        demo=is_demo,
        created_at=utcnow(),
    )

    db.add(
        row
    )

    db.flush()

    return (
        _event_snapshot(
            row
        ),
        True,
    )


def _claim_hash(
    raw_token: str,
) -> str:
    token = _required_text(
        raw_token,
        field="claim_token",
        max_length=1024,
    )

    return hashlib.sha256(
        token.encode(
            "utf-8"
        )
    ).hexdigest()


def create_donation_intent(
    db: Session,
    *,
    currency: str,
    chain_key: str,
    chain: str,
    expires_at: datetime,
    now: datetime | None = None,
) -> tuple[
    dict[str, Any],
    str,
]:
    symbol = normalize_currency(
        currency
    )

    normalized_chain_key = normalize_chain_key(
        chain_key
    )

    normalized_chain = normalize_chain(
        chain
    )

    current = _utc_datetime(
        now or utcnow(),
        field="now",
    )

    expires = _utc_datetime(
        expires_at,
        field="expires_at",
    )

    if expires <= current:
        raise DonationLedgerInvariantError(
            "Donation intent expiry must be in the future"
        )

    raw_claim = secrets.token_urlsafe(
        CLAIM_TOKEN_BYTES
    )

    claim_hash = _claim_hash(
        raw_claim
    )

    row = DonationIntent(
        intent_id=(
            "don_int_"
            + uuid.uuid4().hex
        ),
        claim_token_hash=claim_hash,
        currency=symbol,
        chain_key=normalized_chain_key,
        chain=normalized_chain,
        submitted_txid="",
        status=INTENT_PENDING,
        matched_event_id=None,
        created_at=current,
        expires_at=expires,
        matched_at=None,
        updated_at=current,
    )

    db.add(
        row
    )

    db.flush()

    return (
        {
            "intent_id": row.intent_id,
            "currency": row.currency,
            "chain_key": row.chain_key,
            "chain": row.chain,
            "status": row.status,
            "created_at": _utc_datetime(
                row.created_at,
                field="created_at",
            ).isoformat(),
            "expires_at": _utc_datetime(
                row.expires_at,
                field="expires_at",
            ).isoformat(),
        },
        raw_claim,
    )


def donation_intent_claim_matches(
    intent: DonationIntent,
    raw_token: str,
) -> bool:
    try:
        candidate = _claim_hash(
            raw_token
        )
    except DonationLedgerInvariantError:
        return False

    stored = str(
        intent.claim_token_hash
        or ""
    )

    return hmac.compare_digest(
        stored,
        candidate,
    )



PUBLIC_ATTRIBUTION_MODES = frozenset(
    {
        "anonymous",
        "nickname",
        "telegram",
        "x",
        "telegram_x",
    }
)

REAL_DONATION_SOURCE_TYPES = frozenset(
    {
        SOURCE_EXTERNAL_DEPOSIT,
        SOURCE_INTERNAL_TRANSFER,
    }
)

PUBLIC_LEDGER_DEFAULT_LIMIT = 50
PUBLIC_LEDGER_MAX_LIMIT = 100
PUBLIC_LEDGER_MAX_OFFSET = 10_000


def _valid_public_event_predicate():
    """
    Publish only internally consistent event/source pairs.

    This is deliberately stricter than merely trusting the
    demo boolean. A malformed manually-created row is omitted
    rather than projected publicly.
    """

    return or_(
        and_(
            DonationEvent.demo.is_(False),
            DonationEvent.source_type.in_(
                tuple(
                    sorted(
                        REAL_DONATION_SOURCE_TYPES
                    )
                )
            ),
        ),
        and_(
            DonationEvent.demo.is_(True),
            DonationEvent.source_type
            == SOURCE_DEMO,
        ),
    )


def _clean_public_text(
    value: Any,
    *,
    max_length: int,
) -> str:
    text = str(
        value
        or ""
    ).strip()

    if len(text) > max_length:
        return ""

    return text


def _public_attribution(
    row: DonationAttribution | None,
) -> dict[str, str]:
    """
    Project only display metadata.

    Unknown or internally incomplete attribution states fail
    closed to anonymous rather than leaking stale hidden fields.
    """

    anonymous = {
        "display_mode": "anonymous",
        "nickname": "",
        "telegram_handle": "",
        "x_handle": "",
    }

    if row is None:
        return anonymous

    mode = str(
        row.display_mode
        or ""
    ).strip().lower()

    if mode not in PUBLIC_ATTRIBUTION_MODES:
        return anonymous

    nickname = _clean_public_text(
        row.nickname,
        max_length=128,
    )

    telegram = _clean_public_text(
        row.telegram_handle,
        max_length=128,
    )

    x_handle = _clean_public_text(
        row.x_handle,
        max_length=128,
    )

    if mode == "anonymous":
        return anonymous

    if mode == "nickname":
        if not nickname:
            return anonymous

        return {
            "display_mode": "nickname",
            "nickname": nickname,
            "telegram_handle": "",
            "x_handle": "",
        }

    if mode == "telegram":
        if not telegram:
            return anonymous

        return {
            "display_mode": "telegram",
            "nickname": "",
            "telegram_handle": telegram,
            "x_handle": "",
        }

    if mode == "x":
        if not x_handle:
            return anonymous

        return {
            "display_mode": "x",
            "nickname": "",
            "telegram_handle": "",
            "x_handle": x_handle,
        }

    if (
        mode == "telegram_x"
        and telegram
        and x_handle
    ):
        return {
            "display_mode": "telegram_x",
            "nickname": "",
            "telegram_handle": telegram,
            "x_handle": x_handle,
        }

    return anonymous


def _public_event(
    row: DonationEvent,
    attribution: DonationAttribution | None,
) -> dict[str, Any]:
    """
    Explicit allowlist projection for one public ledger row.

    source_key, Gate identifiers, Wallet-account identifiers,
    transaction ids and audit metadata are intentionally absent.
    """

    return {
        "event_id": row.event_id,
        "source_type": row.source_type,
        "currency": row.currency,
        "chain": row.chain,
        "amount": exact_decimal_text(
            row.amount,
            precision=48,
            scale=24,
        ),
        "occurred_at": _utc_datetime(
            row.occurred_at,
            field="occurred_at",
        ).isoformat(),
        "demo": bool(
            row.demo
        ),
        "attribution": _public_attribution(
            attribution
        ),
    }


def _exact_real_totals(
    db: Session,
) -> list[dict[str, str]]:
    """
    Aggregate in Python Decimal space.

    SQLite SUM over TEXT/NUMERIC values can coerce through
    binary floating point. Public financial totals therefore
    never use SQL SUM.
    """

    rows = db.execute(
        select(
            DonationEvent.currency,
            DonationEvent.amount,
        ).where(
            DonationEvent.demo.is_(False),
            DonationEvent.source_type.in_(
                tuple(
                    sorted(
                        REAL_DONATION_SOURCE_TYPES
                    )
                )
            ),
        )
    ).all()

    totals: dict[
        str,
        Decimal,
    ] = {}

    for currency, amount in rows:
        symbol = normalize_currency(
            currency
        )

        canonical = exact_decimal_text(
            amount,
            precision=48,
            scale=24,
        )

        totals[symbol] = (
            totals.get(
                symbol,
                Decimal("0"),
            )
            + Decimal(
                canonical
            )
        )

    return [
        {
            "currency": symbol,
            "amount": exact_decimal_text(
                total,
                precision=72,
                scale=24,
            ),
        }
        for symbol, total in sorted(
            totals.items()
        )
    ]


def read_public_donation_ledger(
    db: Session,
    *,
    include_demo: bool = False,
    limit: int = PUBLIC_LEDGER_DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Read-only public Donation Ledger projection.

    This function performs only SELECT statements.
    It never flushes, commits, creates donation facts,
    changes attribution or contacts Gate.
    """

    if (
        limit < 1
        or limit > PUBLIC_LEDGER_MAX_LIMIT
    ):
        raise DonationLedgerInvariantError(
            "Public ledger limit is out of range"
        )

    if (
        offset < 0
        or offset > PUBLIC_LEDGER_MAX_OFFSET
    ):
        raise DonationLedgerInvariantError(
            "Public ledger offset is out of range"
        )

    publication_filter = (
        _valid_public_event_predicate()
    )

    filters = [
        publication_filter
    ]

    if not include_demo:
        filters.append(
            DonationEvent.demo.is_(False)
        )

    total_items = int(
        db.scalar(
            select(
                func.count(
                    DonationEvent.id
                )
            ).where(
                *filters
            )
        )
        or 0
    )

    rows = db.execute(
        select(
            DonationEvent,
            DonationAttribution,
        )
        .outerjoin(
            DonationAttribution,
            DonationAttribution.event_id
            == DonationEvent.event_id,
        )
        .where(
            *filters
        )
        .order_by(
            DonationEvent.occurred_at.desc(),
            DonationEvent.id.desc(),
        )
        .offset(
            offset
        )
        .limit(
            limit
        )
    ).all()

    real_event_count = int(
        db.scalar(
            select(
                func.count(
                    DonationEvent.id
                )
            ).where(
                DonationEvent.demo.is_(False),
                DonationEvent.source_type.in_(
                    tuple(
                        sorted(
                            REAL_DONATION_SOURCE_TYPES
                        )
                    )
                ),
            )
        )
        or 0
    )

    demo_event_count = int(
        db.scalar(
            select(
                func.count(
                    DonationEvent.id
                )
            ).where(
                DonationEvent.demo.is_(True),
                DonationEvent.source_type
                == SOURCE_DEMO,
            )
        )
        or 0
    )

    items = [
        _public_event(
            event,
            attribution,
        )
        for event, attribution in rows
    ]

    return {
        "as_of": datetime.now(
            timezone.utc
        ).isoformat(),
        "items": items,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(
                items
            ),
            "total_items": total_items,
            "include_demo": bool(
                include_demo
            ),
        },
        "summary": {
            "real_event_count":
                real_event_count,
            "demo_event_count":
                demo_event_count,
            "real_totals_by_currency":
                _exact_real_totals(
                    db
                ),
        },
    }
