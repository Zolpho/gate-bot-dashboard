from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import utcnow
from .deposits import normalize_currency_symbol
from .donations import (
    DonationDestinationIdentity,
    donation_destination_identity,
    published_destination_state,
)
from .models import PublicDonationDestination


TRUSTED_STATUS = "trusted"
BLOCKED_STATUS = "blocked"


class DonationDestinationBootstrapError(
    RuntimeError
):
    """Operator bootstrap refused without replacing trust."""


@dataclass(
    frozen=True,
    slots=True,
)
class DonationDestinationDecision:
    state: str
    destination_id: int | None


def _text(value: Any) -> str:
    return str(
        value
        if value is not None
        else ""
    ).strip()


def _chain_key(value: Any) -> str:
    return re.sub(
        r"[^A-Z0-9]",
        "",
        _text(value).upper(),
    )


def _network(
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    value = payload.get("network")

    if not isinstance(
        value,
        Mapping,
    ):
        raise ValueError(
            "Donation network is missing"
        )

    return value


def _stored_payload(
    row: PublicDonationDestination,
) -> dict[str, Any]:
    return {
        "currency": row.currency,
        "network": {
            "chain": row.chain,
            "address": row.address,
            "payment_id": (
                row.memo
                or None
            ),
        },
    }


def _current_values(
    payload: Mapping[str, Any],
) -> tuple[
    DonationDestinationIdentity,
    str,
    str,
    str,
]:
    identity = (
        donation_destination_identity(
            payload
        )
    )

    network = _network(
        payload
    )

    chain = _text(
        network.get("chain")
        or network.get("name")
    )

    address = _text(
        network.get("address")
    )

    memo = _text(
        network.get("payment_id")
    )

    return (
        identity,
        chain,
        address,
        memo,
    )


def _trust_row(
    session: Session,
    *,
    currency: str,
    chain_key: str,
) -> PublicDonationDestination | None:
    return session.scalar(
        select(
            PublicDonationDestination
        ).where(
            PublicDonationDestination.currency
            == currency,
            PublicDonationDestination.chain_key
            == chain_key,
        )
    )


def has_trusted_public_destination(
    session: Session,
    *,
    currency: str,
    chain: str,
) -> bool:
    """
    Cheap fail-closed trust gate used before a signed Gate read.

    This never creates or mutates durable state.
    """

    symbol = normalize_currency_symbol(
        currency
    )

    chain_key = _chain_key(
        chain
    )

    if not chain_key:
        return False

    row = _trust_row(
        session,
        currency=symbol,
        chain_key=chain_key,
    )

    return bool(
        row is not None
        and row.status == TRUSTED_STATUS
    )


def verify_public_destination(
    session: Session,
    payload: Mapping[str, Any],
) -> DonationDestinationDecision:
    """
    Verify one Gate-observed destination against existing trust.

    Missing trusted row:
      fail closed without creating any durable trust.

    Existing identical trusted row:
      refresh verification metadata.

    Existing changed trusted row:
      preserve the original destination and permanently block
      public publication until separate administrative review.

    Existing blocked row:
      remain blocked; never auto-recover.

    Initial trust creation is intentionally excluded from this
    public verification primitive. Only
    bootstrap_public_destination() may establish it.
    """

    (
        identity,
        chain,
        address,
        memo,
    ) = _current_values(
        payload
    )

    row = _trust_row(
        session,
        currency=identity.currency,
        chain_key=identity.chain_key,
    )

    if row is None:
        return DonationDestinationDecision(
            state="untrusted",
            destination_id=None,
        )

    now = utcnow()

    row.updated_at = now

    if row.status != TRUSTED_STATUS:
        row.observed_address = address
        row.observed_memo = memo

        session.flush()

        return DonationDestinationDecision(
            state="blocked",
            destination_id=row.id,
        )

    state = published_destination_state(
        payload,
        [
            _stored_payload(
                row
            )
        ],
    )

    if state == "verified":
        row.chain = chain
        row.last_verified_at = now
        row.observed_address = ""
        row.observed_memo = ""
        row.blocked_reason = ""
        row.blocked_at = None

        session.flush()

        return DonationDestinationDecision(
            state="verified",
            destination_id=row.id,
        )

    row.status = BLOCKED_STATUS
    row.observed_address = address
    row.observed_memo = memo
    row.blocked_at = now
    row.blocked_reason = (
        "Gate returned a public donation "
        "address or memo different from the "
        "trusted destination."
    )

    session.flush()

    return DonationDestinationDecision(
        state="blocked",
        destination_id=row.id,
    )


def bootstrap_public_destination(
    session: Session,
    payload: Mapping[str, Any],
) -> DonationDestinationDecision:
    """
    Establish one destination trust anchor from a controlled
    local operator workflow.

    Missing row:
      create the initial trusted destination.

    Existing identical trusted row:
      return idempotently without changing durable state.

    Existing trusted mismatch:
      refuse; never overwrite or block the existing trust row.

    Existing blocked row:
      refuse; bootstrap is not an administrative unblock tool.
    """

    (
        identity,
        chain,
        address,
        memo,
    ) = _current_values(
        payload
    )

    row = _trust_row(
        session,
        currency=identity.currency,
        chain_key=identity.chain_key,
    )

    if row is None:
        now = utcnow()

        row = PublicDonationDestination(
            currency=identity.currency,
            chain_key=identity.chain_key,
            chain=chain,
            address=address,
            memo=memo,
            status=TRUSTED_STATUS,
            first_published_at=now,
            last_verified_at=now,
            updated_at=now,
        )

        session.add(
            row
        )

        session.flush()

        return DonationDestinationDecision(
            state="bootstrapped",
            destination_id=row.id,
        )

    if row.status != TRUSTED_STATUS:
        raise DonationDestinationBootstrapError(
            "Donation destination trust row is blocked; "
            "bootstrap cannot replace or unblock it."
        )

    state = published_destination_state(
        payload,
        [
            _stored_payload(
                row
            )
        ],
    )

    if state != "verified":
        raise DonationDestinationBootstrapError(
            "Observed destination differs from the existing "
            "trusted destination; bootstrap refused."
        )

    return DonationDestinationDecision(
        state="already_trusted",
        destination_id=row.id,
    )
