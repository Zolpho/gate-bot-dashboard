#!/usr/bin/env python3
"""
Create or apply a controlled full-catalog donation trust plan.

PLAN MODE

  --plan-file PATH

Reads the Gate deposit catalog for the fixed EQTYDAO Wallet
account and writes a root-only reviewed plan.

The plan operation:
  - performs only Gate GET operations
  - performs no donation trust DB writes
  - uses unsigned catalog/network discovery
  - uses at most one signed deposit-address GET per currency
  - records every currently deposit-enabled network
  - records unavailable addresses without trusting them
  - can resume an interrupted/incomplete plan

APPLY MODE

  --apply-plan PATH --confirm-digest SHA256

Performs no Gate requests. It applies only the exact reviewed
complete plan whose digest was explicitly supplied.

All ready routes are applied in one local DB transaction.
A blocked or mismatching existing trust row aborts and rolls
back the complete transaction.

The Wallet account is permanently fixed to EQTYDAO.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import stat
from datetime import (
    datetime,
    timezone,
)
from pathlib import Path
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
    merge_deposit_networks,
    normalize_currency_catalog,
    normalize_currency_chains,
)
from app.donation_destinations import (
    DonationDestinationBootstrapError,
    bootstrap_public_destination,
)
from app.donations import (
    DONATION_ACCOUNT_ID,
    donation_destination_identity,
)
from app.gate_client import (
    GateAPIError,
    GateClient,
)
from app.models import (
    PublicDonationDestination,
)


PLAN_SCHEMA = (
    "gate-bot-dashboard."
    "donation-bootstrap-plan.v1"
)

PLAN_MAX_AGE_SECONDS = 6 * 60 * 60

# Conservative pacing. The real full-catalog acceptance can
# take tens of minutes rather than hammering Gate.
BULK_UNSIGNED_DELAY_SECONDS = 0.05
BULK_SIGNED_DELAY_SECONDS = 1.00


EXIT_USAGE = 2
EXIT_PLAN_INVALID = 7
EXIT_PLAN_INCOMPLETE = 8
EXIT_CONFIRMATION_MISMATCH = 9
EXIT_BOOTSTRAP_REFUSED = 10


class DonationCatalogBootstrapError(
    RuntimeError
):
    """Bulk bootstrap operation refused safely."""


def _utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _parse_utc_timestamp(
    value: Any,
    *,
    label: str,
) -> datetime:
    text = str(
        value
        if value is not None
        else ""
    ).strip()

    if not text:
        raise DonationCatalogBootstrapError(
            f"{label} is missing"
        )

    try:
        parsed = datetime.fromisoformat(
            text
        )

    except ValueError as exc:
        raise DonationCatalogBootstrapError(
            f"{label} is invalid"
        ) from exc

    if parsed.tzinfo is None:
        raise DonationCatalogBootstrapError(
            f"{label} has no timezone"
        )

    return parsed.astimezone(
        timezone.utc
    )


def _chain_key(
    value: Any,
) -> str:
    return re.sub(
        r"[^A-Z0-9]",
        "",
        str(
            value
            if value is not None
            else ""
        )
        .strip()
        .upper(),
    )


def _donation_account():  # type: ignore[no-untyped-def]
    try:
        account = get_gate_account(
            DONATION_ACCOUNT_ID
        )

    except AccountConfigError as exc:
        raise DonationCatalogBootstrapError(
            "EQTYDAO Gate account configuration "
            f"could not be read: {exc}"
        ) from exc

    if (
        account is None
        or not account.enabled
        or not account.configured
    ):
        raise DonationCatalogBootstrapError(
            "EQTYDAO Gate account is not "
            "enabled/configured"
        )

    return account


def _require_root() -> None:
    if os.geteuid() != 0:
        raise DonationCatalogBootstrapError(
            "Full-catalog donation bootstrap "
            "must be run by root"
        )


def _operator_plan_path(
    value: str,
) -> Path:
    """
    Normalize the plan parent without dereferencing the
    final path component.

    This keeps a final-component symlink visible to the
    explicit is_symlink() checks in _write_plan/_load_plan.
    """

    raw = Path(
        value
    ).expanduser()

    if not raw.is_absolute():
        raw = (
            Path.cwd()
            / raw
        )

    try:
        parent = raw.parent.resolve(
            strict=True
        )

    except (
        OSError,
        RuntimeError,
    ) as exc:
        raise DonationCatalogBootstrapError(
            "Plan parent directory cannot be resolved"
        ) from exc

    return (
        parent
        / raw.name
    )


def _canonical_plan_bytes(
    plan: dict[str, Any],
) -> bytes:
    payload = dict(
        plan
    )

    payload.pop(
        "digest",
        None,
    )

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode(
        "utf-8"
    )


def plan_digest(
    plan: dict[str, Any],
) -> str:
    return hashlib.sha256(
        _canonical_plan_bytes(
            plan
        )
    ).hexdigest()


def _catalog_symbols_digest(
    symbols: list[str],
) -> str:
    payload = "\n".join(
        symbols
    ).encode(
        "utf-8"
    )

    return hashlib.sha256(
        payload
    ).hexdigest()


def _seal_plan(
    plan: dict[str, Any],
) -> None:
    plan["digest"] = (
        plan_digest(
            plan
        )
    )


def _validate_plan_structure(
    plan: dict[str, Any],
    *,
    require_complete: bool = False,
) -> None:
    if plan.get(
        "schema"
    ) != PLAN_SCHEMA:
        raise DonationCatalogBootstrapError(
            "Unsupported donation bootstrap plan schema"
        )

    if plan.get(
        "wallet_account"
    ) != DONATION_ACCOUNT_ID:
        raise DonationCatalogBootstrapError(
            "Plan Wallet account is not eqtydao"
        )

    catalog = plan.get(
        "catalog"
    )

    if not isinstance(
        catalog,
        dict,
    ):
        raise DonationCatalogBootstrapError(
            "Plan catalog metadata is invalid"
        )

    symbols = catalog.get(
        "candidate_symbols"
    )

    if not isinstance(
        symbols,
        list,
    ):
        raise DonationCatalogBootstrapError(
            "Plan candidate symbol list is invalid"
        )

    if (
        symbols
        != sorted(
            set(
                str(
                    value
                )
                for value in symbols
            )
        )
    ):
        raise DonationCatalogBootstrapError(
            "Plan candidate symbols are not "
            "sorted and unique"
        )

    if (
        catalog.get(
            "candidate_symbols_sha256"
        )
        != _catalog_symbols_digest(
            symbols
        )
    ):
        raise DonationCatalogBootstrapError(
            "Plan catalog symbol digest is invalid"
        )

    routes = plan.get(
        "routes"
    )

    if not isinstance(
        routes,
        list,
    ):
        raise DonationCatalogBootstrapError(
            "Plan routes are invalid"
        )

    seen: set[
        tuple[str, str]
    ] = set()

    for route in routes:
        if not isinstance(
            route,
            dict,
        ):
            raise DonationCatalogBootstrapError(
                "Plan route is invalid"
            )

        currency = str(
            route.get(
                "currency"
            )
            or ""
        ).strip()

        chain = str(
            route.get(
                "chain"
            )
            or ""
        ).strip()

        chain_key = str(
            route.get(
                "chain_key"
            )
            or ""
        ).strip()

        status_value = str(
            route.get(
                "status"
            )
            or ""
        ).strip()

        if (
            not currency
            or not chain
            or not chain_key
        ):
            raise DonationCatalogBootstrapError(
                "Plan route identity is incomplete"
            )

        if (
            chain_key
            != _chain_key(
                chain
            )
        ):
            raise DonationCatalogBootstrapError(
                "Plan route chain key is invalid"
            )

        _parse_utc_timestamp(
            route.get(
                "observed_at"
            ),
            label=(
                "Plan route observation timestamp "
                f"for {currency}/{chain_key}"
            ),
        )

        identity = (
            currency,
            chain_key,
        )

        if identity in seen:
            raise DonationCatalogBootstrapError(
                "Plan contains a duplicate "
                f"route: {currency}/{chain_key}"
            )

        seen.add(
            identity
        )

        if status_value not in {
            "ready",
            "unavailable",
        }:
            raise DonationCatalogBootstrapError(
                "Plan route has an invalid status"
            )

        if status_value == "ready":
            address = str(
                route.get(
                    "address"
                )
                or ""
            ).strip()

            if not address:
                raise DonationCatalogBootstrapError(
                    "Ready plan route has no address"
                )

            payload = {
                "currency": currency,
                "network": {
                    "chain": chain,
                    "address": address,
                    "payment_id": (
                        route.get(
                            "memo"
                        )
                        or None
                    ),
                },
            }

            donation_destination_identity(
                payload
            )

    errors = plan.get(
        "errors"
    )

    if not isinstance(
        errors,
        list,
    ):
        raise DonationCatalogBootstrapError(
            "Plan errors field is invalid"
        )

    if (
        require_complete
        and (
            plan.get(
                "complete"
            )
            is not True
            or bool(
                errors
            )
        )
    ):
        raise DonationCatalogBootstrapError(
            "Donation bootstrap plan is incomplete"
        )


def _refresh_summary(
    plan: dict[str, Any],
) -> None:
    routes = plan.get(
        "routes",
        [],
    )

    results = plan.get(
        "currency_results",
        {},
    )

    errors = plan.get(
        "errors",
        [],
    )

    plan["summary"] = {
        "candidate_currencies":
            len(
                plan[
                    "catalog"
                ][
                    "candidate_symbols"
                ]
            ),
        "processed_currencies":
            len(
                results
            ),
        "error_currencies":
            sum(
                1
                for value in results.values()
                if value.get(
                    "status"
                )
                == "error"
            ),
        "ready_routes":
            sum(
                1
                for route in routes
                if route.get(
                    "status"
                )
                == "ready"
            ),
        "unavailable_routes":
            sum(
                1
                for route in routes
                if route.get(
                    "status"
                )
                == "unavailable"
            ),
        "errors":
            len(
                errors
            ),
    }


def _write_plan(
    path: Path,
    plan: dict[str, Any],
) -> None:
    if path.is_symlink():
        raise DonationCatalogBootstrapError(
            "Refusing to write plan through a symlink"
        )

    if not path.parent.exists():
        raise DonationCatalogBootstrapError(
            "Plan parent directory does not exist"
        )

    _refresh_summary(
        plan
    )

    _seal_plan(
        plan
    )

    temporary = path.with_name(
        "." + path.name + ".tmp"
    )

    if temporary.is_symlink():
        raise DonationCatalogBootstrapError(
            "Refusing temporary plan symlink"
        )

    payload = (
        json.dumps(
            plan,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_TRUNC
    )

    fd = os.open(
        temporary,
        flags,
        0o600,
    )

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(
                payload
            )

            handle.flush()

            os.fsync(
                handle.fileno()
            )

    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass

        raise

    os.chmod(
        temporary,
        0o600,
    )

    os.replace(
        temporary,
        path,
    )

    os.chmod(
        path,
        0o600,
    )


def _load_plan(
    path: Path,
) -> dict[str, Any]:
    if path.is_symlink():
        raise DonationCatalogBootstrapError(
            "Refusing to read plan through a symlink"
        )

    info = path.stat()

    if not stat.S_ISREG(
        info.st_mode
    ):
        raise DonationCatalogBootstrapError(
            "Plan is not a regular file"
        )

    if (
        stat.S_IMODE(
            info.st_mode
        )
        & 0o077
    ):
        raise DonationCatalogBootstrapError(
            "Plan permissions must be 0600 "
            "or more restrictive"
        )

    with path.open(
        "r",
        encoding="utf-8",
    ) as handle:
        plan = json.load(
            handle
        )

    if not isinstance(
        plan,
        dict,
    ):
        raise DonationCatalogBootstrapError(
            "Plan root is invalid"
        )

    supplied = str(
        plan.get(
            "digest"
        )
        or ""
    ).strip()

    calculated = plan_digest(
        plan
    )

    if (
        not supplied
        or supplied != calculated
    ):
        raise DonationCatalogBootstrapError(
            "Plan digest does not match contents"
        )

    _validate_plan_structure(
        plan
    )

    return plan


def _new_plan(
    symbols: list[str],
) -> dict[str, Any]:
    return {
        "schema": PLAN_SCHEMA,
        "wallet_account":
            DONATION_ACCOUNT_ID,
        "generated_at":
            _utc_now(),
        "completed_at": None,
        "complete": False,
        "catalog": {
            "candidate_count":
                len(
                    symbols
                ),
            "candidate_symbols":
                symbols,
            "candidate_symbols_sha256":
                _catalog_symbols_digest(
                    symbols
                ),
        },
        "currency_results": {},
        "routes": [],
        "errors": [],
        "summary": {},
    }


def _remove_currency_state(
    plan: dict[str, Any],
    currency: str,
) -> None:
    plan["routes"] = [
        route
        for route in plan[
            "routes"
        ]
        if route.get(
            "currency"
        )
        != currency
    ]

    plan["errors"] = [
        item
        for item in plan[
            "errors"
        ]
        if item.get(
            "currency"
        )
        != currency
    ]


def _set_currency_error(
    plan: dict[str, Any],
    *,
    currency: str,
    stage: str,
    message: str,
) -> None:
    _remove_currency_state(
        plan,
        currency,
    )

    plan[
        "currency_results"
    ][
        currency
    ] = {
        "status": "error",
        "stage": stage,
        "message": message,
    }

    plan[
        "errors"
    ].append(
        {
            "currency": currency,
            "stage": stage,
            "message": message,
        }
    )


async def _pace(
    seconds: float,
) -> None:
    if seconds > 0:
        await asyncio.sleep(
            seconds
        )


def _candidate_symbols(
    raw_catalog: Any,
    favorites: list[str],
) -> list[str]:
    normalized = (
        normalize_currency_catalog(
            raw_catalog,
            favorites,
        )
    )

    return sorted(
        {
            str(
                item.get(
                    "currency"
                )
                or ""
            ).strip()
            for item in normalized.get(
                "currencies",
                [],
            )
            if (
                item.get(
                    "deposit_available"
                )
                and str(
                    item.get(
                        "currency"
                    )
                    or ""
                ).strip()
            )
        }
    )


def _enabled_authoritative_networks(
    raw_chains: Any,
) -> list[dict[str, Any]]:
    return [
        item
        for item in normalize_currency_chains(
            raw_chains
        )
        if item.get(
            "deposit_enabled"
        )
    ]


def _merged_by_key(
    raw_chains: Any,
    raw_address: Any,
) -> dict[str, dict[str, Any]]:
    result: dict[
        str,
        dict[str, Any]
    ] = {}

    for item in merge_deposit_networks(
        raw_chains,
        raw_address,
    ):
        for value in (
            item.get(
                "chain"
            ),
            item.get(
                "name"
            ),
        ):
            key = _chain_key(
                value
            )

            if key:
                result.setdefault(
                    key,
                    item,
                )

    return result


async def generate_catalog_plan(
    path: Path,
    *,
    resume: bool,
) -> dict[str, Any]:
    _require_root()

    settings = get_settings()

    account = (
        _donation_account()
    )

    async with GateClient(
        settings
    ) as public_client, GateClient(
        settings,
        account,
    ) as signed_client:

        catalog_response = (
            await public_client
            .list_spot_currencies()
        )

        await _pace(
            BULK_UNSIGNED_DELAY_SECONDS
        )

        symbols = (
            _candidate_symbols(
                catalog_response.data,
                list(
                    settings.deposit_favorite_list
                ),
            )
        )

        if resume:
            if not path.exists():
                raise DonationCatalogBootstrapError(
                    "Cannot resume: plan file does not exist"
                )

            plan = _load_plan(
                path
            )

            expected = (
                plan[
                    "catalog"
                ][
                    "candidate_symbols_sha256"
                ]
            )

            observed = (
                _catalog_symbols_digest(
                    symbols
                )
            )

            if expected != observed:
                raise DonationCatalogBootstrapError(
                    "Gate deposit catalog changed since "
                    "this plan was created; start a new plan"
                )

            if (
                plan.get(
                    "complete"
                )
                is True
            ):
                return plan

        else:
            if path.exists():
                raise DonationCatalogBootstrapError(
                    "Plan already exists; use --resume "
                    "or choose another path"
                )

            plan = _new_plan(
                symbols
            )

            _write_plan(
                path,
                plan,
            )

        for currency in symbols:
            current = (
                plan[
                    "currency_results"
                ].get(
                    currency
                )
            )

            if (
                current
                and current.get(
                    "status"
                )
                in {
                    "complete",
                    "no_enabled_networks",
                }
            ):
                continue

            _remove_currency_state(
                plan,
                currency,
            )

            try:
                networks_response = (
                    await public_client
                    .list_currency_chains(
                        currency
                    )
                )

                await _pace(
                    BULK_UNSIGNED_DELAY_SECONDS
                )

            except GateAPIError as exc:
                _set_currency_error(
                    plan,
                    currency=currency,
                    stage="networks",
                    message=str(
                        exc
                    ),
                )

                _write_plan(
                    path,
                    plan,
                )

                continue

            raw_chains = (
                networks_response.data
            )

            enabled = (
                _enabled_authoritative_networks(
                    raw_chains
                )
            )

            if not enabled:
                plan[
                    "currency_results"
                ][
                    currency
                ] = {
                    "status":
                        "no_enabled_networks",
                    "enabled_networks": 0,
                    "ready_routes": 0,
                    "unavailable_routes": 0,
                }

                _write_plan(
                    path,
                    plan,
                )

                continue

            try:
                address_response = (
                    await signed_client
                    .get_deposit_address(
                        currency
                    )
                )

                await _pace(
                    BULK_SIGNED_DELAY_SECONDS
                )

            except GateAPIError as exc:
                _set_currency_error(
                    plan,
                    currency=currency,
                    stage="address",
                    message=str(
                        exc
                    ),
                )

                _write_plan(
                    path,
                    plan,
                )

                continue

            observed_at = (
                _utc_now()
            )

            merged = (
                _merged_by_key(
                    raw_chains,
                    address_response.data,
                )
            )

            ready_count = 0
            unavailable_count = 0

            for network in enabled:
                chain = str(
                    network.get(
                        "chain"
                    )
                    or ""
                ).strip()

                chain_key = _chain_key(
                    chain
                )

                possible_keys = [
                    chain_key,
                    _chain_key(
                        network.get(
                            "name"
                        )
                    ),
                ]

                observed = next(
                    (
                        merged[key]
                        for key in possible_keys
                        if (
                            key
                            and key in merged
                        )
                    ),
                    None,
                )

                route = {
                    "currency":
                        currency,
                    "chain":
                        chain,
                    "chain_key":
                        chain_key,
                    "observed_at":
                        observed_at,
                    "name":
                        str(
                            network.get(
                                "name"
                            )
                            or chain
                        ).strip(),
                }

                if (
                    observed is None
                    or not observed.get(
                        "address_available"
                    )
                ):
                    route.update(
                        {
                            "status":
                                "unavailable",
                            "reason":
                                "Gate did not return "
                                "an available deposit "
                                "address for this "
                                "deposit-enabled network",
                        }
                    )

                    unavailable_count += 1

                else:
                    address = str(
                        observed.get(
                            "address"
                        )
                        or ""
                    ).strip()

                    memo = str(
                        observed.get(
                            "payment_id"
                        )
                        or ""
                    ).strip()

                    payload = {
                        "currency":
                            currency,
                        "network": {
                            "chain":
                                chain,
                            "address":
                                address,
                            "payment_id":
                                memo
                                or None,
                        },
                    }

                    donation_destination_identity(
                        payload
                    )

                    route.update(
                        {
                            "status":
                                "ready",
                            "address":
                                address,
                            "memo":
                                memo,
                        }
                    )

                    ready_count += 1

                plan[
                    "routes"
                ].append(
                    route
                )

            plan[
                "routes"
            ].sort(
                key=lambda value: (
                    value[
                        "currency"
                    ],
                    value[
                        "chain_key"
                    ],
                )
            )

            plan[
                "currency_results"
            ][
                currency
            ] = {
                "status": "complete",
                "enabled_networks":
                    len(
                        enabled
                    ),
                "ready_routes":
                    ready_count,
                "unavailable_routes":
                    unavailable_count,
            }

            _write_plan(
                path,
                plan,
            )

    error_count = sum(
        1
        for value in plan[
            "currency_results"
        ].values()
        if value.get(
            "status"
        )
        == "error"
    )

    fully_processed = (
        len(
            plan[
                "currency_results"
            ]
        )
        == len(
            symbols
        )
    )

    plan["complete"] = bool(
        fully_processed
        and error_count == 0
    )

    plan[
        "completed_at"
    ] = (
        _utc_now()
        if plan[
            "complete"
        ]
        else None
    )

    _write_plan(
        path,
        plan,
    )

    return plan


def _trust_table_exists() -> bool:
    return inspect(
        engine
    ).has_table(
        PublicDonationDestination
        .__tablename__
    )


def _completed_age_seconds(
    plan: dict[str, Any],
) -> float:
    completed = (
        _parse_utc_timestamp(
            plan.get(
                "completed_at"
            ),
            label=(
                "Plan completion timestamp"
            ),
        )
    )

    return (
        datetime.now(
            timezone.utc
        )
        - completed
    ).total_seconds()


def _oldest_ready_route_age_seconds(
    plan: dict[str, Any],
) -> float:
    now = datetime.now(
        timezone.utc
    )

    ages = []

    for route in plan.get(
        "routes",
        [],
    ):
        if route.get(
            "status"
        ) != "ready":
            continue

        observed = (
            _parse_utc_timestamp(
                route.get(
                    "observed_at"
                ),
                label=(
                    "Ready route observation timestamp "
                    f"for {route.get('currency')}/"
                    f"{route.get('chain_key')}"
                ),
            )
        )

        ages.append(
            (
                now
                - observed
            ).total_seconds()
        )

    if not ages:
        return 0.0

    return max(
        ages
    )

def apply_catalog_plan(
    path: Path,
    *,
    confirm_digest: str,
) -> tuple[
    int,
    int,
]:
    _require_root()

    plan = _load_plan(
        path
    )

    _validate_plan_structure(
        plan,
        require_complete=True,
    )

    supplied = str(
        confirm_digest
        or ""
    ).strip().lower()

    actual = str(
        plan.get(
            "digest"
        )
        or ""
    ).strip().lower()

    if (
        not supplied
        or supplied != actual
    ):
        raise DonationCatalogBootstrapError(
            "Confirmed digest does not match "
            "the reviewed plan"
        )

    age = _completed_age_seconds(
        plan
    )

    if (
        age < 0
        or age > PLAN_MAX_AGE_SECONDS
    ):
        raise DonationCatalogBootstrapError(
            "Reviewed plan is stale; generate a new plan"
        )

    oldest_route_age = (
        _oldest_ready_route_age_seconds(
            plan
        )
    )

    if (
        oldest_route_age < 0
        or oldest_route_age
        > PLAN_MAX_AGE_SECONDS
    ):
        raise DonationCatalogBootstrapError(
            "One or more reviewed donation routes "
            "are stale; generate a new plan"
        )

    if not _trust_table_exists():
        raise DonationCatalogBootstrapError(
            "public_donation_destinations does not exist; "
            "start the M4.14 application first"
        )

    ready_routes = [
        route
        for route in plan[
            "routes"
        ]
        if route.get(
            "status"
        )
        == "ready"
    ]

    session = SessionLocal()

    bootstrapped = 0
    already_trusted = 0

    try:
        try:
            for route in ready_routes:
                payload = {
                    "currency":
                        route[
                            "currency"
                        ],
                    "network": {
                        "chain":
                            route[
                                "chain"
                            ],
                        "address":
                            route[
                                "address"
                            ],
                        "payment_id":
                            (
                                route.get(
                                    "memo"
                                )
                                or None
                            ),
                    },
                }

                decision = (
                    bootstrap_public_destination(
                        session,
                        payload,
                    )
                )

                if (
                    decision.state
                    == "bootstrapped"
                ):
                    bootstrapped += 1

                elif (
                    decision.state
                    == "already_trusted"
                ):
                    already_trusted += 1

                else:
                    raise DonationCatalogBootstrapError(
                        "Unexpected bootstrap state: "
                        f"{decision.state}"
                    )

            session.commit()

        except (
            DonationDestinationBootstrapError,
            IntegrityError,
            DonationCatalogBootstrapError,
        ):
            session.rollback()

            raise

    finally:
        session.close()

    return (
        bootstrapped,
        already_trusted,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
    )

    mode = (
        parser
        .add_mutually_exclusive_group(
            required=True
        )
    )

    mode.add_argument(
        "--plan-file",
        help=(
            "Create or resume a full-catalog "
            "GET-only bootstrap plan"
        ),
    )

    mode.add_argument(
        "--apply-plan",
        help=(
            "Apply one complete reviewed plan "
            "without making Gate requests"
        ),
    )

    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume an incomplete --plan-file"
        ),
    )

    parser.add_argument(
        "--confirm-digest",
        help=(
            "Exact SHA256 digest required with "
            "--apply-plan"
        ),
    )

    return parser


def _print_plan_summary(
    path: Path,
    plan: dict[str, Any],
) -> None:
    summary = plan.get(
        "summary",
        {},
    )

    print()
    print(
        "FULL-CATALOG DONATION PLAN:"
    )

    print(
        f"  file: {path}"
    )

    print(
        f"  wallet_account: {plan['wallet_account']}"
    )

    print(
        "  candidate_currencies: "
        f"{summary.get('candidate_currencies', 0)}"
    )

    print(
        "  processed_currencies: "
        f"{summary.get('processed_currencies', 0)}"
    )

    print(
        "  error_currencies: "
        f"{summary.get('error_currencies', 0)}"
    )

    print(
        "  ready_routes: "
        f"{summary.get('ready_routes', 0)}"
    )

    print(
        "  unavailable_routes: "
        f"{summary.get('unavailable_routes', 0)}"
    )

    print(
        f"  complete: {plan.get('complete') is True}"
    )

    print(
        f"  digest: {plan.get('digest')}"
    )

    print()
    print(
        "Raw deposit addresses are stored only "
        "inside the root-only plan file."
    )

    print(
        "Review the plan before applying it."
    )


async def run(
    args: argparse.Namespace,
) -> int:
    try:
        if args.plan_file:
            if args.confirm_digest:
                print(
                    "REFUSED: --confirm-digest is "
                    "only valid with --apply-plan"
                )

                return EXIT_USAGE

            path = (
                _operator_plan_path(
                    args.plan_file
                )
            )

            plan = (
                await generate_catalog_plan(
                    path,
                    resume=bool(
                        args.resume
                    ),
                )
            )

            _print_plan_summary(
                path,
                plan,
            )

            if not plan.get(
                "complete"
            ):
                print()
                print(
                    "PLAN INCOMPLETE:"
                )

                print(
                    "Re-run with the same "
                    "--plan-file and --resume."
                )

                return EXIT_PLAN_INCOMPLETE

            print()
            print(
                "PLAN COMPLETE:"
            )

            print(
                "Apply only after reviewing the plan:"
            )

            print(
                "  --apply-plan "
                f"{path} "
                "--confirm-digest "
                f"{plan['digest']}"
            )

            return 0

        if args.resume:
            print(
                "REFUSED: --resume is valid only "
                "with --plan-file"
            )

            return EXIT_USAGE

        if not args.confirm_digest:
            print(
                "REFUSED: --apply-plan requires "
                "--confirm-digest"
            )

            return EXIT_USAGE

        path = (
            _operator_plan_path(
                args.apply_plan
            )
        )

        (
            bootstrapped,
            already_trusted,
        ) = apply_catalog_plan(
            path,
            confirm_digest=
                args.confirm_digest,
        )

        print()
        print(
            "FULL-CATALOG BOOTSTRAP APPLY COMPLETE:"
        )

        print(
            f"  bootstrapped: {bootstrapped}"
        )

        print(
            f"  already_trusted: {already_trusted}"
        )

        print(
            "  Gate requests: 0"
        )

        return 0

    except DonationCatalogBootstrapError as exc:
        print(
            f"REFUSED: {exc}"
        )

        return EXIT_PLAN_INVALID

    except DonationDestinationBootstrapError as exc:
        print(
            f"REFUSED: {exc}"
        )

        return EXIT_BOOTSTRAP_REFUSED

    except IntegrityError as exc:
        print(
            "REFUSED: database integrity "
            f"error: {exc}"
        )

        return EXIT_BOOTSTRAP_REFUSED


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
