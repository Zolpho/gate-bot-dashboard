from decimal import Decimal

import pytest
from sqlalchemy import (
    delete,
    inspect,
)

from app.config import Settings
from app.db import (
    engine,
    init_db,
    session_scope,
)
from app.models import (
    TradingOrderAmendment,
)
from app.trading_order_amend_audit import (
    TradingOrderAmendConflict,
    get_active_order_amendment,
    get_latest_order_amendment,
    get_order_amendment,
    list_order_amendments,
    mark_order_amendment,
    reserve_order_amendment,
)


init_db()


@pytest.fixture(autouse=True)
def clean_amendments():
    def clear():
        with session_scope() as db:
            db.execute(
                delete(
                    TradingOrderAmendment
                )
            )

    clear()
    yield
    clear()


def amend_args(
    **overrides,
):
    values = {
        "amend_request_id":
            "amend-a",
        "order_request_id":
            "request-a",
        "account_id":
            "arnold",
        "username":
            "alice",
        "pair":
            "EQTY_USDT",
        "gate_order_id":
            "123456789",
        "current_price":
            Decimal("0.0015"),
        "requested_price":
            Decimal("0.0016"),
    }

    values.update(
        overrides
    )

    return values


def test_amend_settings_default_fail_closed():
    settings = Settings(
        _env_file=None
    )

    assert (
        settings.trading_order_amends_enabled
        is False
    )

    assert (
        settings
        .trading_order_amend_confirmation_text
        == "AMEND ORDER"
    )

    assert (
        settings.trading_order_amend_exptime_ms
        == 5000
    )


def test_amend_table_is_created():
    assert inspect(
        engine
    ).has_table(
        "trading_order_amendments"
    )


def test_amend_reservation_is_idempotent():
    first, created = (
        reserve_order_amendment(
            **amend_args()
        )
    )

    second, created_again = (
        reserve_order_amendment(
            **amend_args()
        )
    )

    assert created is True
    assert created_again is False

    assert first["id"] == second["id"]

    assert (
        first["amend_request_id"]
        == "amend-a"
    )

    assert first["active"] is True

    assert (
        first["current_price"]
        == "0.0015"
    )

    assert (
        first["requested_price"]
        == "0.0016"
    )


def test_amend_request_id_conflict_rejected():
    reserve_order_amendment(
        **amend_args()
    )

    with pytest.raises(
        TradingOrderAmendConflict,
    ):
        reserve_order_amendment(
            **amend_args(
                order_request_id=(
                    "request-b"
                ),
                gate_order_id=(
                    "987654321"
                ),
                requested_price=(
                    Decimal("0.0017")
                ),
            )
        )


def test_only_one_unresolved_amend_per_order():
    reserve_order_amendment(
        **amend_args()
    )

    with pytest.raises(
        TradingOrderAmendConflict,
    ):
        reserve_order_amendment(
            **amend_args(
                amend_request_id=(
                    "amend-b"
                ),
                requested_price=(
                    Decimal("0.0017")
                ),
            )
        )

    active = (
        get_active_order_amendment(
            "request-a"
        )
    )

    assert active is not None

    assert (
        active["amend_request_id"]
        == "amend-a"
    )


def test_completed_amend_releases_order_for_next_amend():
    reserve_order_amendment(
        **amend_args()
    )

    completed = (
        mark_order_amendment(
            "amend-a",
            status="amended",
            response={
                "id":
                    "123456789",
                "status":
                    "open",
                "price":
                    "0.0016",
            },
            gate_status_code=200,
            write_performed=True,
            completed=True,
        )
    )

    assert completed["active"] is False
    assert completed["completed_at"]

    assert (
        get_active_order_amendment(
            "request-a"
        )
        is None
    )

    second, created = (
        reserve_order_amendment(
            **amend_args(
                amend_request_id=(
                    "amend-b"
                ),
                current_price=(
                    Decimal("0.0016")
                ),
                requested_price=(
                    Decimal("0.0017")
                ),
            )
        )
    )

    assert created is True

    assert (
        second["amend_request_id"]
        == "amend-b"
    )

    assert second["active"] is True


def test_uncertain_amend_keeps_order_locked():
    reserve_order_amendment(
        **amend_args()
    )

    uncertain = (
        mark_order_amendment(
            "amend-a",
            status="uncertain",
            response={
                "phase":
                    "gate_amend",
            },
            error=(
                "Outcome unknown"
            ),
            write_performed=True,
            completed=False,
        )
    )

    assert uncertain["active"] is True
    assert uncertain["completed_at"] is None

    assert (
        get_active_order_amendment(
            "request-a"
        )
        is not None
    )


def test_amend_history_supports_sequential_operations():
    reserve_order_amendment(
        **amend_args()
    )

    mark_order_amendment(
        "amend-a",
        status="amended",
        write_performed=True,
        completed=True,
    )

    reserve_order_amendment(
        **amend_args(
            amend_request_id=(
                "amend-b"
            ),
            current_price=(
                Decimal("0.0016")
            ),
            requested_price=(
                Decimal("0.0017")
            ),
        )
    )

    latest = (
        get_latest_order_amendment(
            "request-a"
        )
    )

    assert latest is not None

    assert (
        latest["amend_request_id"]
        == "amend-b"
    )

    rows = list_order_amendments(
        "request-a"
    )

    assert len(rows) == 2

    assert (
        get_order_amendment(
            "amend-a"
        )
        is not None
    )


@pytest.mark.parametrize(
    (
        "current_price",
        "requested_price",
    ),
    [
        (
            Decimal("0"),
            Decimal("0.0016"),
        ),
        (
            Decimal("0.0015"),
            Decimal("0"),
        ),
        (
            Decimal("0.0015"),
            Decimal("0.0015"),
        ),
    ],
)
def test_amend_prices_fail_closed(
    current_price,
    requested_price,
):
    with pytest.raises(
        ValueError,
    ):
        reserve_order_amendment(
            **amend_args(
                current_price=current_price,
                requested_price=(
                    requested_price
                ),
            )
        )
