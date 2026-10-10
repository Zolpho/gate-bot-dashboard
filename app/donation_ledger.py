from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .db import session_scope, utcnow
from .exact_decimal import exact_decimal_text
from .models import (
    DepositRecord,
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
INTENT_SUBMITTED = "submitted"
INTENT_MATCHED = "matched"
INTENT_EXPIRED = "expired"

DONE_DEPOSIT_STATUS = "DONE"
DONATION_TXID_MAX_LENGTH = 512

CLAIM_TOKEN_BYTES = 32


class DonationLedgerInvariantError(ValueError):
    pass


class DonationAttributionValidationError(
    DonationLedgerInvariantError
):
    """
    Donor-controlled display metadata is malformed.
    """


class DonationAttributionCapabilityError(
    DonationLedgerInvariantError
):
    """
    The caller has no valid capability for this attribution.
    """


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


def materialize_internal_transfer_donation(
    record: dict[str, Any],
) -> tuple[
    dict[str, Any] | None,
    bool,
]:
    """
    Materialize one confirmed dashboard Wallet-account transfer
    into the immutable Donation Ledger.

    Only a real, successfully completed user-account transfer
    whose destination is exactly EQTYDAO qualifies.

    Non-qualifying records are ignored. A qualifying record
    that is internally inconsistent fails closed.
    """
    status = str(
        record.get("status")
        or ""
    ).strip().lower()

    direction = str(
        record.get("direction")
        or ""
    ).strip().lower()

    destination = str(
        record.get(
            "destination_account_id"
        )
        or ""
    ).strip().lower()

    if (
        status != "success"
        or direction
        != "user_account_transfer"
        or destination
        != DONATION_ACCOUNT_ID
    ):
        return None, False

    request_payload = (
        record.get("request")
        or {}
    )

    if (
        not isinstance(
            request_payload,
            dict,
        )
        or request_payload.get(
            "donation"
        )
        is not True
    ):
        return None, False

    if bool(
        record.get("simulation")
    ):
        raise DonationLedgerInvariantError(
            "Simulated transfer cannot become a donation"
        )

    if not bool(
        record.get("write_performed")
    ):
        raise DonationLedgerInvariantError(
            "Successful internal donation has no "
            "recorded Gate write"
        )

    request_id = _required_text(
        record.get("request_id"),
        field="request_id",
        max_length=128,
    )

    symbol = normalize_currency(
        str(
            record.get("currency")
            or ""
        )
    )

    amount = _positive_amount(
        record.get("amount")
    )

    completed_value = (
        record.get("completed_at")
    )

    if isinstance(
        completed_value,
        datetime,
    ):
        completed_at = (
            _utc_datetime(
                completed_value,
                field="completed_at",
            )
        )
    else:
        completed_text = (
            _required_text(
                completed_value,
                field="completed_at",
                max_length=128,
            )
        )

        try:
            parsed = (
                datetime.fromisoformat(
                    completed_text.replace(
                        "Z",
                        "+00:00",
                    )
                )
            )
        except ValueError as exc:
            raise DonationLedgerInvariantError(
                "Internal donation completed_at "
                "is invalid"
            ) from exc

        completed_at = (
            _utc_datetime(
                parsed,
                field="completed_at",
            )
        )

    with session_scope() as db:
        return ensure_donation_event(
            db,
            source_type=(
                SOURCE_INTERNAL_TRANSFER
            ),
            source_key=(
                internal_transfer_source_key(
                    request_id
                )
            ),
            currency=symbol,
            amount=amount,
            occurred_at=completed_at,
            chain_key="",
            chain="",
            demo=False,
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



def _normalized_chain_identity(
    value: Any,
) -> str:
    """
    Normalize only presentation punctuation/case.

    No chain aliasing or cross-network heuristic is allowed.
    """
    return re.sub(
        r"[^A-Z0-9]",
        "",
        str(
            value
            or ""
        ).strip().upper(),
    )


def _intent_snapshot(
    row: DonationIntent,
    *,
    match_status: str | None = None,
) -> dict[str, Any]:
    """
    Safe correlation state.

    The donor-submitted txid and claim hash are deliberately
    never returned by this projection.
    """
    result: dict[str, Any] = {
        "intent_id": row.intent_id,
        "currency": row.currency,
        "chain_key": row.chain_key,
        "chain": row.chain,
        "status": row.status,
        "txid_submitted": bool(
            row.submitted_txid
        ),
        "matched_event_id":
            row.matched_event_id,
        "created_at": _utc_datetime(
            row.created_at,
            field="created_at",
        ).isoformat(),
        "expires_at": _utc_datetime(
            row.expires_at,
            field="expires_at",
        ).isoformat(),
        "matched_at": (
            _utc_datetime(
                row.matched_at,
                field="matched_at",
            ).isoformat()
            if row.matched_at
            else None
        ),
        "updated_at": (
            _utc_datetime(
                row.updated_at,
                field="updated_at",
            ).isoformat()
            if row.updated_at
            else None
        ),
    }

    if match_status is not None:
        result[
            "match_status"
        ] = match_status

    return result


def _load_donation_intent(
    db: Session,
    intent_id: str,
) -> DonationIntent:
    identifier = _required_text(
        intent_id,
        field="intent_id",
        max_length=128,
    )

    row = db.scalar(
        select(
            DonationIntent
        ).where(
            DonationIntent.intent_id
            == identifier
        )
    )

    if row is None:
        raise DonationLedgerInvariantError(
            "Donation intent not found"
        )

    return row


def _intent_is_expired(
    row: DonationIntent,
    now: datetime,
) -> bool:
    expires = _utc_datetime(
        row.expires_at,
        field="expires_at",
    )

    return now >= expires


def _retire_donation_intent_claim(
    row: DonationIntent,
    *,
    reason: str,
) -> None:
    """
    Irreversibly consume the stored claim authority while
    preserving DonationIntent.claim_token_hash uniqueness.

    A real claim hash is exactly 64 lowercase hexadecimal
    SHA-256 characters.

    Tombstones intentionally contain punctuation, so they can
    never equal the output of _claim_hash(). Intent identity
    makes each tombstone unique without requiring a schema
    change.
    """
    normalized_reason = str(
        reason
        or ""
    ).strip().lower()

    if normalized_reason not in {
        "consumed",
        "expired",
    }:
        raise DonationLedgerInvariantError(
            "Unsupported donation claim retirement reason"
        )

    identifier = _required_text(
        row.intent_id,
        field="intent_id",
        max_length=96,
    )

    tombstone = (
        "!"
        + normalized_reason
        + ":"
        + identifier
    )

    if len(tombstone) > 64:
        raise DonationLedgerInvariantError(
            "Donation claim tombstone exceeds "
            "storage limit"
        )

    row.claim_token_hash = tombstone


def _expire_intent(
    row: DonationIntent,
    *,
    now: datetime,
) -> None:
    row.status = INTENT_EXPIRED

    # A claim token is one-time correlation authority.
    # Once an intent expires it can never authorize a txid.
    _retire_donation_intent_claim(
        row,
        reason="expired",
    )

    row.updated_at = now


def submit_donation_intent_txid(
    db: Session,
    *,
    intent_id: str,
    claim_token: str,
    txid: str,
    now: datetime | None = None,
    match_expires_at: datetime | None = None,
) -> dict[str, Any]:
    """
    Bind one donor-supplied txid to one pending intent.

    This performs no Gate request and no deposit-history sync.

    The raw claim token is valid only while the intent is
    pending. After a successful submission its durable hash is
    removed, making the correlation authority one-time.

    A caller may optionally extend expires_at only after the
    claim has passed pending-expiry validation. This lets a
    short-lived claim authorize a longer local correlation
    window without reviving an already expired claim.
    """
    current = _utc_datetime(
        now or utcnow(),
        field="now",
    )

    row = _load_donation_intent(
        db,
        intent_id,
    )

    if (
        row.status
        == INTENT_PENDING
        and _intent_is_expired(
            row,
            current,
        )
    ):
        _expire_intent(
            row,
            now=current,
        )

        db.flush()

        return _intent_snapshot(
            row,
            match_status="expired",
        )

    if row.status != INTENT_PENDING:
        raise DonationLedgerInvariantError(
            "Donation intent is not pending"
        )

    if not donation_intent_claim_matches(
        row,
        claim_token,
    ):
        raise DonationLedgerInvariantError(
            "Invalid donation claim token"
        )

    submitted_txid = _required_text(
        txid,
        field="txid",
        max_length=DONATION_TXID_MAX_LENGTH,
    )

    requested_match_expiry = None

    if match_expires_at is not None:
        requested_match_expiry = (
            _utc_datetime(
                match_expires_at,
                field="match_expires_at",
            )
        )

        if requested_match_expiry <= current:
            raise DonationLedgerInvariantError(
                "Donation match expiry must be "
                "in the future"
            )

    existing_claim = db.scalar(
        select(
            DonationIntent
        ).where(
            DonationIntent.intent_id
            != row.intent_id,
            DonationIntent.submitted_txid
            == submitted_txid,
            DonationIntent.status.in_(
                (
                    INTENT_SUBMITTED,
                    INTENT_MATCHED,
                )
            ),
        )
    )

    if existing_claim is not None:
        raise DonationLedgerInvariantError(
            "Donation txid is already associated "
            "with another intent"
        )

    if requested_match_expiry is not None:
        current_expiry = _utc_datetime(
            row.expires_at,
            field="expires_at",
        )

        if requested_match_expiry > current_expiry:
            row.expires_at = (
                requested_match_expiry
            )

    row.submitted_txid = submitted_txid
    row.status = INTENT_SUBMITTED

    # Consume the one-time secret immediately after the txid
    # has been accepted. Only the opaque intent id remains.
    _retire_donation_intent_claim(
        row,
        reason="consumed",
    )

    row.updated_at = current

    db.flush()

    return _intent_snapshot(
        row,
        match_status="awaiting_match",
    )


def _exact_deposit_amount(
    deposit: DepositRecord,
) -> str:
    """
    Recover the exact Gate deposit amount from the persisted
    original payload.

    DepositRecord.amount historically uses SQLite NUMERIC,
    which may round-trip fractional values through binary
    floating point. DonationEvent accounting must never copy
    that loss of precision.

    Fail closed rather than guessing if the original amount
    is unavailable or not represented exactly.
    """
    try:
        payload = json.loads(
            str(
                deposit.raw_json
                or "{}"
            )
        )
    except (
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise DonationLedgerInvariantError(
            "Matched donation deposit has invalid "
            "raw Gate payload"
        ) from exc

    if not isinstance(
        payload,
        dict,
    ):
        raise DonationLedgerInvariantError(
            "Matched donation deposit has invalid "
            "raw Gate payload"
        )

    if "amount" not in payload:
        raise DonationLedgerInvariantError(
            "Matched donation deposit has no exact "
            "raw Gate amount"
        )

    raw_amount = payload[
        "amount"
    ]

    # JSON floating point has already discarded source
    # precision. Gate deposit amounts are expected to be
    # decimal strings; integral JSON numbers remain exact.
    if (
        isinstance(
            raw_amount,
            bool,
        )
        or not isinstance(
            raw_amount,
            (
                str,
                int,
            ),
        )
    ):
        raise DonationLedgerInvariantError(
            "Matched donation deposit raw amount "
            "is not exactly represented"
        )

    try:
        return exact_decimal_text(
            raw_amount,
            precision=48,
            scale=24,
        )
    except ValueError as exc:
        raise DonationLedgerInvariantError(
            "Matched donation deposit has invalid "
            "exact raw amount"
        ) from exc


def reconcile_external_donation_intent(
    db: Session,
    *,
    intent_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Correlate one explicit submitted intent with local deposits.

    Match requirements are intentionally narrow:
      - account_id is exactly eqtydao
      - txid is exactly the donor-submitted txid
      - currency is exactly the selected intent currency
      - normalized Gate chain equals the intent chain_key
      - status is exactly DONE
      - exactly one deposit row matches

    No amount, time, address or memo heuristic is used.
    No Gate request is made.
    No historical row is scanned into the ledger unless an
    explicit submitted intent names its txid.
    """
    current = _utc_datetime(
        now or utcnow(),
        field="now",
    )

    row = _load_donation_intent(
        db,
        intent_id,
    )

    if row.status == INTENT_MATCHED:
        return _intent_snapshot(
            row,
            match_status="matched",
        )

    if _intent_is_expired(
        row,
        current,
    ):
        _expire_intent(
            row,
            now=current,
        )

        db.flush()

        return _intent_snapshot(
            row,
            match_status="expired",
        )

    if row.status != INTENT_SUBMITTED:
        raise DonationLedgerInvariantError(
            "Donation intent has no submitted txid"
        )

    submitted_txid = _required_text(
        row.submitted_txid,
        field="submitted_txid",
        max_length=DONATION_TXID_MAX_LENGTH,
    )

    expected_chain_key = (
        _normalized_chain_identity(
            row.chain_key
        )
    )

    if not expected_chain_key:
        raise DonationLedgerInvariantError(
            "Donation intent has no network identity"
        )

    possible = db.scalars(
        select(
            DepositRecord
        ).where(
            DepositRecord.account_id
            == DONATION_ACCOUNT_ID,
            DepositRecord.txid
            == submitted_txid,
            DepositRecord.currency
            == row.currency,
            DepositRecord.status
            == DONE_DEPOSIT_STATUS,
        )
    ).all()

    candidates = [
        deposit
        for deposit in possible
        if _normalized_chain_identity(
            deposit.chain
        )
        == expected_chain_key
    ]

    if not candidates:
        return _intent_snapshot(
            row,
            match_status="not_found",
        )

    if len(candidates) != 1:
        raise DonationLedgerInvariantError(
            "Donation txid match is ambiguous"
        )

    deposit = candidates[0]

    if deposit.deposited_at is None:
        raise DonationLedgerInvariantError(
            "Matched donation deposit has no timestamp"
        )

    deposit_chain = _required_text(
        deposit.chain,
        field="deposit.chain",
        max_length=128,
    )

    source_key = external_deposit_source_key(
        DONATION_ACCOUNT_ID,
        deposit.gate_deposit_id,
    )

    expected_event_id = donation_event_id(
        SOURCE_EXTERNAL_DEPOSIT,
        source_key,
    )

    other_intent = db.scalar(
        select(
            DonationIntent
        ).where(
            DonationIntent.intent_id
            != row.intent_id,
            DonationIntent.matched_event_id
            == expected_event_id,
        )
    )

    if other_intent is not None:
        raise DonationLedgerInvariantError(
            "Donation event is already associated "
            "with another intent"
        )

    event, _ = ensure_donation_event(
        db,
        source_type=
            SOURCE_EXTERNAL_DEPOSIT,
        source_key=source_key,
        currency=deposit.currency,
        chain_key=(
            _normalized_chain_identity(
                deposit_chain
            )
        ),
        chain=deposit_chain,
        amount=_exact_deposit_amount(
            deposit
        ),
        occurred_at=deposit.deposited_at,
        demo=False,
    )

    row.status = INTENT_MATCHED
    row.matched_event_id = event[
        "event_id"
    ]
    row.matched_at = current
    row.updated_at = current

    db.flush()

    return _intent_snapshot(
        row,
        match_status="matched",
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


_SELF_DECLARED_HANDLE_RE = re.compile(
    r"^[A-Za-z0-9_]{1,64}$"
)


def _normalize_attribution_nickname(
    value: Any,
) -> str:
    text = str(
        value
        or ""
    ).strip()

    if (
        not text
        or len(text) > 128
        or any(
            ord(character) < 32
            or ord(character) == 127
            for character in text
        )
    ):
        raise DonationAttributionValidationError(
            "Nickname is invalid"
        )

    return text


def _normalize_self_declared_handle(
    value: Any,
    *,
    field: str,
) -> str:
    """
    Validate only a conservative display-handle grammar.

    These values are self-declared display metadata. This
    deliberately does not claim platform ownership or identity
    verification.
    """
    text = str(
        value
        or ""
    ).strip()

    if text.startswith(
        "@"
    ):
        text = text[1:]

    if not _SELF_DECLARED_HANDLE_RE.fullmatch(
        text
    ):
        raise DonationAttributionValidationError(
            f"{field} is invalid"
        )

    return "@" + text


def normalize_donation_attribution(
    *,
    display_mode: str = "anonymous",
    nickname: Any = "",
    telegram_handle: Any = "",
    x_handle: Any = "",
) -> dict[str, str]:
    mode = str(
        display_mode
        or "anonymous"
    ).strip().lower()

    if mode not in PUBLIC_ATTRIBUTION_MODES:
        raise DonationAttributionValidationError(
            "Unsupported donation attribution mode"
        )

    result = {
        "display_mode": mode,
        "nickname": "",
        "telegram_handle": "",
        "x_handle": "",
    }

    if mode == "anonymous":
        return result

    if mode == "nickname":
        result[
            "nickname"
        ] = _normalize_attribution_nickname(
            nickname
        )

        return result

    if mode == "telegram":
        result[
            "telegram_handle"
        ] = _normalize_self_declared_handle(
            telegram_handle,
            field="Telegram handle",
        )

        return result

    if mode == "x":
        result[
            "x_handle"
        ] = _normalize_self_declared_handle(
            x_handle,
            field="X handle",
        )

        return result

    result[
        "telegram_handle"
    ] = _normalize_self_declared_handle(
        telegram_handle,
        field="Telegram handle",
    )

    result[
        "x_handle"
    ] = _normalize_self_declared_handle(
        x_handle,
        field="X handle",
    )

    return result


def upsert_donation_attribution(
    db: Session,
    *,
    event_id: str,
    display_mode: str = "anonymous",
    nickname: Any = "",
    telegram_handle: Any = "",
    x_handle: Any = "",
    updated_by: str,
) -> dict[str, Any]:
    identifier = _required_text(
        event_id,
        field="event_id",
        max_length=96,
    )

    actor = _required_text(
        updated_by,
        field="updated_by",
        max_length=128,
    )

    event = db.scalar(
        select(
            DonationEvent
        ).where(
            DonationEvent.event_id
            == identifier
        )
    )

    if event is None:
        raise DonationAttributionCapabilityError(
            "Donation event not found"
        )

    normalized = normalize_donation_attribution(
        display_mode=display_mode,
        nickname=nickname,
        telegram_handle=telegram_handle,
        x_handle=x_handle,
    )

    row = db.scalar(
        select(
            DonationAttribution
        ).where(
            DonationAttribution.event_id
            == identifier
        )
    )

    current = utcnow()

    if row is None:
        row = DonationAttribution(
            event_id=identifier,
            display_mode=(
                normalized[
                    "display_mode"
                ]
            ),
            nickname=(
                normalized[
                    "nickname"
                ]
            ),
            telegram_handle=(
                normalized[
                    "telegram_handle"
                ]
            ),
            x_handle=(
                normalized[
                    "x_handle"
                ]
            ),
            updated_by=actor,
            created_at=current,
            updated_at=current,
        )

        db.add(
            row
        )

    else:
        row.display_mode = (
            normalized[
                "display_mode"
            ]
        )

        row.nickname = (
            normalized[
                "nickname"
            ]
        )

        row.telegram_handle = (
            normalized[
                "telegram_handle"
            ]
        )

        row.x_handle = (
            normalized[
                "x_handle"
            ]
        )

        row.updated_by = actor
        row.updated_at = current

    db.flush()

    return {
        "event_id":
            event.event_id,
        "attribution":
            _public_attribution(
                row
            ),
    }


def set_matched_intent_attribution(
    db: Session,
    *,
    intent_id: str,
    display_mode: str = "anonymous",
    nickname: Any = "",
    telegram_handle: Any = "",
    x_handle: Any = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Set attribution through the opaque matched-intent capability.

    The raw one-time claim token is not required or reintroduced.
    The capability remains valid only until the intent's existing
    correlation expiry.
    """
    current = _utc_datetime(
        now or utcnow(),
        field="now",
    )

    try:
        intent = _load_donation_intent(
            db,
            intent_id,
        )

    except DonationLedgerInvariantError as exc:
        raise DonationAttributionCapabilityError(
            "Donation intent not found"
        ) from exc

    if (
        intent.status
        != INTENT_MATCHED
        or not intent.matched_event_id
    ):
        raise DonationAttributionCapabilityError(
            "Donation intent is not matched"
        )

    if _intent_is_expired(
        intent,
        current,
    ):
        raise DonationAttributionCapabilityError(
            "Donation attribution capability expired"
        )

    return upsert_donation_attribution(
        db,
        event_id=(
            intent.matched_event_id
        ),
        display_mode=display_mode,
        nickname=nickname,
        telegram_handle=telegram_handle,
        x_handle=x_handle,
        # Deliberately generic. Never persist the opaque
        # capability or raw claim token as audit metadata.
        updated_by="public-intent",
    )


def set_internal_transfer_donation_attribution(
    record: dict[str, Any],
    *,
    display_mode: str = "anonymous",
    nickname: Any = "",
    telegram_handle: Any = "",
    x_handle: Any = "",
    updated_by: str,
) -> dict[str, Any]:
    """
    Attribute one already-confirmed explicit internal donation.

    materialize_internal_transfer_donation() is deterministic by
    request_id, so this can safely repair a missing DonationEvent
    before applying display metadata.
    """
    try:
        event, _ = (
            materialize_internal_transfer_donation(
                record
            )
        )

    except DonationLedgerInvariantError as exc:
        raise DonationAttributionCapabilityError(
            "Internal donation cannot be attributed"
        ) from exc

    if event is None:
        raise DonationAttributionCapabilityError(
            "Transfer is not a confirmed explicit donation"
        )

    with session_scope() as db:
        return upsert_donation_attribution(
            db,
            event_id=(
                event[
                    "event_id"
                ]
            ),
            display_mode=display_mode,
            nickname=nickname,
            telegram_handle=telegram_handle,
            x_handle=x_handle,
            updated_by=updated_by,
        )


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
