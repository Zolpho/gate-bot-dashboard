#!/usr/bin/env python3
"""
Preview or establish one public donation destination trust anchor.

The Wallet account is permanently fixed to EQTYDAO.

The operator must independently provide the expected address
(and memo/tag when applicable). The current Gate observation
must match that expected identity before --apply may create
the local trust row.

This command deliberately does not run database migrations.
The M4.14 application startup must create the trust table
before --apply is used.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.accounts import (
    AccountConfigError,
    get_gate_account,
)
from app.config import get_settings
from app.db import (
    SessionLocal,
    engine,
)
from app.deposits import (
    build_deposit_details,
    merge_deposit_networks,
    normalize_currency_symbol,
    select_network,
)
from app.donation_destinations import (
    DonationDestinationBootstrapError,
    bootstrap_public_destination,
)
from app.donations import (
    DONATION_ACCOUNT_ID,
    DONATION_DISPLAY_NAME,
    donation_destination_identity,
)
from app.gate_client import (
    GateAPIError,
    GateClient,
)
from app.models import (
    PublicDonationDestination,
)


EXIT_USAGE = 2
EXIT_EXPECTED_MISMATCH = 3
EXIT_SCHEMA_MISSING = 4
EXIT_BOOTSTRAP_REFUSED = 5
EXIT_GATE_READ_FAILED = 6


class BootstrapCliError(
    RuntimeError
):
    """Operator bootstrap could not safely continue."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
    )

    parser.add_argument(
        "--currency",
        required=True,
        help="Gate currency symbol, for example EQTY or USDT",
    )

    parser.add_argument(
        "--chain",
        required=True,
        help="Gate chain identifier, for example BASEEVM",
    )

    parser.add_argument(
        "--expected-address",
        required=True,
        help=(
            "Independently verified deposit address that "
            "the fresh Gate observation must match"
        ),
    )

    parser.add_argument(
        "--expected-memo",
        default="",
        help=(
            "Independently verified memo/tag/payment ID; "
            "omit when none is expected"
        ),
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Persist missing trust after all checks pass. "
            "Without this flag the command is preview-only."
        ),
    )

    return parser


def _donation_account():  # type: ignore[no-untyped-def]
    try:
        account = get_gate_account(
            DONATION_ACCOUNT_ID
        )
    except AccountConfigError as exc:
        raise BootstrapCliError(
            "EQTYDAO Gate account configuration "
            f"could not be read: {exc}"
        ) from exc

    if (
        account is None
        or not account.enabled
        or not account.configured
    ):
        raise BootstrapCliError(
            "EQTYDAO Gate account is not enabled/configured"
        )

    return account


async def observe_public_donation_destination(
    *,
    currency: str,
    chain: str,
) -> dict[str, Any]:
    """
    Read one current destination directly from Gate.

    Surface:
      one unsigned currency-chain read
      one signed EQTYDAO deposit-address read
      zero Gate writes
    """

    symbol = normalize_currency_symbol(
        currency
    )

    settings = get_settings()

    try:
        async with GateClient(
            settings
        ) as client:
            raw_chains = (
                await client.list_currency_chains(
                    symbol
                )
            ).data
    except GateAPIError as exc:
        raise BootstrapCliError(
            "Gate network discovery failed"
        ) from exc

    try:
        selected = select_network(
            merge_deposit_networks(
                raw_chains
            ),
            chain,
        )
    except LookupError as exc:
        raise BootstrapCliError(
            "Requested donation network was not returned by Gate"
        ) from exc

    if not selected.get(
        "deposit_enabled"
    ):
        raise BootstrapCliError(
            "Deposits are disabled for the requested network"
        )

    account = _donation_account()

    try:
        async with GateClient(
            settings,
            account,
        ) as client:
            raw_address = (
                await client.get_deposit_address(
                    symbol
                )
            ).data
    except GateAPIError as exc:
        raise BootstrapCliError(
            "Gate deposit-address read failed"
        ) from exc

    try:
        return build_deposit_details(
            account_id=DONATION_ACCOUNT_ID,
            display_name=DONATION_DISPLAY_NAME,
            currency=symbol,
            selected_chain=chain,
            raw_chains=raw_chains,
            raw_address=raw_address,
            source="gate",
        )
    except (
        LookupError,
        PermissionError,
        RuntimeError,
    ) as exc:
        raise BootstrapCliError(
            "Gate observation could not be converted "
            "into a usable donation destination"
        ) from exc


def destination_matches_expected(
    payload: dict[str, Any],
    *,
    expected_address: str,
    expected_memo: str,
) -> bool:
    network = payload.get(
        "network"
    )

    if not isinstance(
        network,
        dict,
    ):
        return False

    expected_payload = {
        "currency": payload.get(
            "currency"
        ),
        "network": {
            "chain": (
                network.get("chain")
                or network.get("name")
            ),
            "address": expected_address,
            "payment_id": (
                expected_memo
                or None
            ),
        },
    }

    try:
        return (
            donation_destination_identity(
                payload
            )
            == donation_destination_identity(
                expected_payload
            )
        )
    except ValueError:
        return False


def _print_observation(
    payload: dict[str, Any],
) -> None:
    identity = (
        donation_destination_identity(
            payload
        )
    )

    network = payload[
        "network"
    ]

    address = str(
        network.get(
            "address"
        )
        or ""
    )

    memo = str(
        network.get(
            "payment_id"
        )
        or ""
    )

    print(
        "Observed Gate destination:"
    )

    print(
        f"  Wallet account: {DONATION_ACCOUNT_ID}"
    )

    print(
        f"  currency: {identity.currency}"
    )

    print(
        f"  chain_key: {identity.chain_key}"
    )

    print(
        f"  address: {address}"
    )

    print(
        "  memo: "
        + (
            memo
            if memo
            else "<none>"
        )
    )


async def run(
    args: argparse.Namespace,
) -> int:
    expected_address = str(
        args.expected_address
        or ""
    ).strip()

    expected_memo = str(
        args.expected_memo
        or ""
    ).strip()

    if not expected_address:
        print(
            "REFUSED: --expected-address must not be empty"
        )

        return EXIT_USAGE

    try:
        payload = (
            await observe_public_donation_destination(
                currency=args.currency,
                chain=args.chain,
            )
        )
    except (
        BootstrapCliError,
        ValueError,
    ) as exc:
        print(
            f"REFUSED: {exc}"
        )

        return EXIT_GATE_READ_FAILED

    _print_observation(
        payload
    )

    if not destination_matches_expected(
        payload,
        expected_address=expected_address,
        expected_memo=expected_memo,
    ):
        print()
        print(
            "REFUSED: fresh Gate destination does not "
            "match the independently supplied expected "
            "address/memo."
        )

        return EXIT_EXPECTED_MISMATCH

    print()
    print(
        "PASS: Gate observation matches expected identity."
    )

    if not args.apply:
        print(
            "PREVIEW ONLY: no database write performed."
        )
        print(
            "Re-run with --apply only after reviewing "
            "the observation above."
        )

        return 0

    inspector = inspect(
        engine
    )

    if not inspector.has_table(
        PublicDonationDestination.__tablename__
    ):
        print()
        print(
            "REFUSED: public_donation_destinations "
            "does not exist."
        )

        print(
            "Start the M4.14 application once so its "
            "normal startup schema path creates the table. "
            "This bootstrap command never runs migrations."
        )

        return EXIT_SCHEMA_MISSING

    session = SessionLocal()

    try:
        try:
            decision = (
                bootstrap_public_destination(
                    session,
                    payload,
                )
            )

            session.commit()

        except (
            DonationDestinationBootstrapError,
            IntegrityError,
        ) as exc:
            session.rollback()

            print()
            print(
                f"REFUSED: {exc}"
            )

            return EXIT_BOOTSTRAP_REFUSED

    finally:
        session.close()

    print()
    print(
        "BOOTSTRAP COMPLETE:"
    )

    print(
        f"  state: {decision.state}"
    )

    print(
        f"  destination_id: {decision.destination_id}"
    )

    return 0


def main() -> int:
    parser = build_parser()

    args = parser.parse_args()

    return asyncio.run(
        run(
            args
        )
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
