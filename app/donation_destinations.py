from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import utcnow
from .donations import (
    DonationDestinationIdentity,
    donation_destination_identity,
    published_destination_state,
)
from .models import PublicDonationDestination


TRUSTED_STATUS = "trusted"
BLOCKED_STATUS = "blocked"


@dataclass(
    frozen=True,
    slots=True,
)
class DonationDestinationDecision:
    state: str
    destination_id: int


def _text(value: Any) -> str:
    return str(
        value
        if value is not None
        else ""
    ).strip()


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


def verify_or_pin_public_destination(
    session: Session,
    payload: Mapping[str, Any],
) -> DonationDestinationDecision:
    """
    Verify one Gate-observed donation destination.

    First successful observation:
      trust-on-first-use and persist the identity.

    Later identical observation:
      refresh last_verified_at.

    Later changed address or memo:
      preserve the original trusted destination,
      record the changed observation,
      permanently block publication until a
      separate administrative review exists.

    A blocked row never auto-recovers merely because
    Gate later returns the original address again.
    """

    (
        identity,
        chain,
        address,
        memo,
    ) = _current_values(
        payload
    )

    now = utcnow()

    row = session.scalar(
        select(
            PublicDonationDestination
        ).where(
            PublicDonationDestination.currency
            == identity.currency,
            PublicDonationDestination.chain_key
            == identity.chain_key,
        )
    )

    if row is None:
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

        session.add(row)
        session.flush()

        return DonationDestinationDecision(
            state="first_seen",
            destination_id=row.id,
        )

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
