from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from .demo_wallet import (
    DemoWalletStore,
)


DEMO_TRANSFER_PATH = (
    "demo_account_to_demo_account"
)


class DemoTreasuryConfirmationError(
    ValueError
):
    """Demo transfer confirmation text did not match."""


class DemoTreasuryTransferBlocked(
    ValueError
):
    """Demo transfer cannot be simulated safely."""


def _amount_text(
    value: Decimal | str | int,
) -> str:
    try:
        amount = Decimal(
            str(
                value
            )
        )

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "Invalid Demo transfer amount"
        ) from exc

    if (
        not amount.is_finite()
        or amount <= 0
    ):
        raise ValueError(
            "Demo transfer amount must be positive"
        )

    text = format(
        amount,
        "f",
    )

    if "." in text:
        text = (
            text
            .rstrip(
                "0"
            )
            .rstrip(
                "."
            )
        )

    return (
        text
        or "0"
    )


def _currency_text(
    value: str,
) -> str:
    currency = str(
        value or ""
    ).strip().upper()

    if not currency:
        raise ValueError(
            "Demo transfer currency is required"
        )

    return currency


def _known_accounts(
    store: DemoWalletStore,
) -> dict[
    str,
    dict[
        str,
        Any,
    ],
]:
    return {
        str(
            item[
                "account_id"
            ]
        ).strip().lower():
            item
        for item
        in store.list_accounts()
    }


def _require_account(
    store: DemoWalletStore,
    account_id: str,
) -> str:
    normalized = str(
        account_id or ""
    ).strip().lower()

    if (
        normalized
        not in _known_accounts(
            store
        )
    ):
        raise KeyError(
            "Unknown Demo Wallet account"
        )

    return normalized


def _scope(
    store: DemoWalletStore,
    account_ids: Iterable[str] | None,
) -> set[str]:
    known = set(
        _known_accounts(
            store
        )
    )

    if account_ids is None:
        return known

    result = {
        str(
            item or ""
        ).strip().lower()
        for item
        in account_ids
        if str(
            item or ""
        ).strip()
    }

    unknown = (
        result
        - known
    )

    if unknown:
        raise KeyError(
            "Unknown Demo Wallet account"
        )

    return result


def demo_user_transfer_confirmation_text(
    *,
    source_account_id: str,
    destination_account_id: str,
    currency: str,
    amount: Decimal | str | int,
) -> str:
    source = str(
        source_account_id or ""
    ).strip().lower()

    destination = str(
        destination_account_id or ""
    ).strip().lower()

    symbol = _currency_text(
        currency
    )

    amount_text = _amount_text(
        amount
    )

    return (
        "DEMO TRANSFER "
        f"{amount_text} "
        f"{symbol} "
        "FROM "
        f"{source} "
        "TO "
        f"{destination}"
    )


def demo_ownership_balances_payload(
    *,
    store: DemoWalletStore,
    account_ids: Iterable[str] | None,
) -> dict[
    str,
    Any,
]:
    scoped = _scope(
        store,
        account_ids,
    )

    return {
        "phase":
            "T2B_TRANSFER_CONTROL",
        "source":
            "demo",
        "gate_read_performed":
            False,
        "gate_write_performed":
            False,
        "items":
            store.ownership_balances(
                account_ids=scoped,
            ),
    }


def demo_ownership_ledger_payload(
    *,
    store: DemoWalletStore,
    account_ids: Iterable[str] | None,
    limit: int = 200,
) -> dict[
    str,
    Any,
]:
    scoped = _scope(
        store,
        account_ids,
    )

    return {
        "phase":
            "T2B_TRANSFER_CONTROL",
        "source":
            "demo",
        "gate_read_performed":
            False,
        "gate_write_performed":
            False,
        "items":
            store.list_ownership_entries(
                account_ids=scoped,
                limit=limit,
            ),
    }


def demo_transfer_requests_payload(
    *,
    store: DemoWalletStore,
    account_ids: Iterable[str] | None,
    limit: int = 50,
) -> dict[
    str,
    Any,
]:
    scoped = _scope(
        store,
        account_ids,
    )

    return {
        "phase":
            "T2B_TRANSFER_CONTROL",
        "source":
            "demo",
        "gate_read_performed":
            False,
        "gate_write_performed":
            False,
        "items":
            store.list_transfers(
                account_ids=scoped,
                limit=limit,
            ),
    }


def demo_transfer_request_detail_payload(
    *,
    store: DemoWalletStore,
    request_id: str,
    account_ids: Iterable[str] | None,
) -> dict[
    str,
    Any,
]:
    scoped = _scope(
        store,
        account_ids,
    )

    item = store.get_transfer(
        request_id,
        account_ids=scoped,
    )

    return {
        "phase":
            "T2B_TRANSFER_CONTROL",
        "source":
            "demo",
        "gate_read_performed":
            False,
        "gate_write_performed":
            False,
        "item":
            item,
        "reconciliations":
            [],
        "operation_lock":
            None,
        "lock_resolutions":
            [],
    }


def demo_transfer_events_payload(
    *,
    store: DemoWalletStore,
    request_id: str,
) -> dict[
    str,
    Any,
]:
    return {
        "phase":
            "USER_ACCOUNT_TRANSFER",
        "source":
            "demo",
        "request_id":
            request_id,
        "gate_read_performed":
            False,
        "gate_write_performed":
            False,
        "items":
            store.list_transfer_events(
                request_id
            ),
    }


def _available_balances(
    store: DemoWalletStore,
    account_id: str,
) -> list[
    dict[
        str,
        str,
    ]
]:
    state = store.get_balance_state(
        account_id
    )

    result = []

    for item in state[
        "assets"
    ]:
        available = Decimal(
            str(
                item[
                    "available"
                ]
            )
        )

        if available <= 0:
            continue

        result.append(
            {
                "currency":
                    item[
                        "currency"
                    ],
                "available":
                    item[
                        "available"
                    ],
            }
        )

    result.sort(
        key=lambda item:
            item[
                "currency"
            ]
    )

    return result


def demo_user_transfer_participants_payload(
    *,
    store: DemoWalletStore,
    source_account_ids: Iterable[str],
) -> dict[
    str,
    Any,
]:
    source_ids = _scope(
        store,
        source_account_ids,
    )

    items = []

    for account in store.list_accounts():
        account_id = str(
            account[
                "account_id"
            ]
        ).strip().lower()

        can_source = (
            account_id
            in source_ids
        )

        items.append(
            {
                "account_id":
                    account_id,
                "display_name":
                    account[
                        "display_name"
                    ],
                "usernames":
                    [
                        "demo",
                    ],
                "account_type":
                    "demo",
                "can_source":
                    can_source,
                # Demo intentionally allows another synthetic
                # Wallet account to be selected as recipient.
                # Same-account transfer is still rejected by
                # preview/execute.
                "can_receive":
                    True,
                "available_balances": (
                    _available_balances(
                        store,
                        account_id,
                    )
                    if can_source
                    else []
                ),
                "balance_error":
                    "",
            }
        )

    return {
        "phase":
            "USER_ACCOUNT_TRANSFER",
        "source":
            "demo",
        "simulation":
            True,
        "user_transfers_enabled":
            True,
        "execution_implemented":
            True,
        "gate_read_performed":
            False,
        "gate_write_performed":
            False,
        "items":
            items,
    }


def demo_user_transfer_preview_payload(
    *,
    store: DemoWalletStore,
    source_account_id: str,
    destination_account_id: str,
    currency: str,
    amount: Decimal | str | int,
    donation: bool = False,
) -> dict[
    str,
    Any,
]:
    source = _require_account(
        store,
        source_account_id,
    )

    destination = _require_account(
        store,
        destination_account_id,
    )

    preview = store.preview_transfer(
        source_account_id=source,
        destination_account_id=destination,
        currency=currency,
        amount=amount,
    )

    required_confirmation = (
        demo_user_transfer_confirmation_text(
            source_account_id=source,
            destination_account_id=(
                destination
            ),
            currency=preview[
                "currency"
            ],
            amount=preview[
                "amount"
            ],
        )
    )

    return {
        "phase":
            "USER_ACCOUNT_TRANSFER",
        "source":
            "demo",
        "simulation":
            True,
        "status":
            preview[
                "status"
            ],
        "user_transfers_enabled":
            True,
        "execution_implemented":
            True,
        "can_execute":
            bool(
                preview[
                    "can_transfer"
                ]
            ),
        "gate_read_performed":
            False,
        "gate_write_required":
            False,
        "gate_write_performed":
            False,
        "required_confirmation":
            required_confirmation,
        "preview": {
            "source_account_id":
                source,
            "destination_account_id":
                destination,
            "currency":
                preview[
                    "currency"
                ],
            "amount":
                preview[
                    "amount"
                ],
            "donation":
                bool(
                    donation
                ),
            "source_available_before":
                preview[
                    "source_available_before"
                ],
            "source_available_after":
                preview[
                    "source_available_after"
                ],
            "destination_available_before":
                preview[
                    "destination_available_before"
                ],
            "destination_available_after":
                preview[
                    "destination_available_after"
                ],
            "transfer_path":
                DEMO_TRANSFER_PATH,
            "source_account_type":
                "demo",
            "destination_account_type":
                "demo",
            "operation_blockers":
                preview[
                    "operation_blockers"
                ],
            "simulation":
                True,
            "ownership_changed":
                False,
            "gate_write_required":
                False,
            "gate_write_performed":
                False,
        },
    }


def demo_user_transfer_execute_payload(
    *,
    store: DemoWalletStore,
    request_id: str,
    source_account_id: str,
    destination_account_id: str,
    currency: str,
    amount: Decimal | str | int,
    username: str,
    donation: bool,
    confirmation: str,
    occurred_at: str | None = None,
) -> dict[
    str,
    Any,
]:
    source = _require_account(
        store,
        source_account_id,
    )

    destination = _require_account(
        store,
        destination_account_id,
    )

    if source == destination:
        raise ValueError(
            "Demo transfer source and destination must differ"
        )

    symbol = _currency_text(
        currency
    )

    amount_text = _amount_text(
        amount
    )

    # Match the live user-transfer ordering exactly:
    # bind/resolve the request ID before confirmation and before
    # any fresh balance preflight. A matching completed replay
    # therefore never depends on today's balance or confirmation.
    try:
        existing = store.get_transfer(
            request_id
        )

    except KeyError:
        existing = None

    if existing is None:
        required_confirmation = (
            demo_user_transfer_confirmation_text(
                source_account_id=source,
                destination_account_id=(
                    destination
                ),
                currency=symbol,
                amount=amount_text,
            )
        )

        if (
            confirmation
            != required_confirmation
        ):
            raise DemoTreasuryConfirmationError(
                "Invalid Demo transfer confirmation text"
            )

        preview = store.preview_transfer(
            source_account_id=source,
            destination_account_id=(
                destination
            ),
            currency=symbol,
            amount=amount_text,
        )

        if not preview[
            "can_transfer"
        ]:
            blockers = preview[
                "operation_blockers"
            ]

            message = (
                blockers[
                    0
                ][
                    "message"
                ]
                if blockers
                else (
                    "Demo transfer is blocked"
                )
            )

            raise DemoTreasuryTransferBlocked(
                message
            )

    try:
        result = store.simulate_transfer(
            request_id=request_id,
            source_account_id=source,
            destination_account_id=(
                destination
            ),
            currency=symbol,
            amount=amount_text,
            username=username,
            donation=donation,
            occurred_at=occurred_at,
        )

    except ValueError as exc:
        if (
            "Insufficient Demo Wallet"
            in str(exc)
        ):
            raise DemoTreasuryTransferBlocked(
                str(exc)
            ) from exc

        raise

    transfer = result[
        "transfer"
    ]

    response = result[
        "response"
    ]

    replay = not bool(
        result[
            "created"
        ]
    )

    payload = {
        "phase":
            "USER_ACCOUNT_TRANSFER",
        "source":
            "demo",
        "simulation":
            True,
        "status":
            transfer[
                "status"
            ],
        "user_transfers_enabled":
            True,
        "execution_implemented":
            True,
        "gate_read_performed":
            False,
        "gate_write_required":
            False,
        "gate_write_performed":
            False,
        "idempotent_replay":
            replay,
        "request_id":
            transfer[
                "request_id"
            ],
        "source_account_id":
            transfer[
                "source_account_id"
            ],
        "destination_account_id":
            transfer[
                "destination_account_id"
            ],
        "currency":
            transfer[
                "currency"
            ],
        "amount":
            transfer[
                "amount"
            ],
        "transfer_path":
            DEMO_TRANSFER_PATH,
        "fresh_available_before":
            response.get(
                "source_available_before"
            ),
        "gate_payload":
            None,
        "operation_lock":
            None,
        "audit":
            transfer,
        "ownership_changed":
            False,
    }

    if replay:
        payload[
            "message"
        ] = (
            "Existing Demo transfer request returned. "
            "No second simulated transfer was performed."
        )

    return payload
