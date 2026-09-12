from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.metrics import bot_range_state


def bot(
    *,
    status: str = "running",
    strategy_type: str = "spot_grid",
    price_range: str = "0.001500-0.002500",
    current_market_price=Decimal("0.002000"),
):
    return SimpleNamespace(
        status=status,
        strategy_type=strategy_type,
        price_range=price_range,
        current_market_price=current_market_price,
    )


def test_range_state_inside_grid() -> None:
    assert bot_range_state(
        bot()
    ) == "in_range"


def test_range_state_boundaries_are_in_range() -> None:
    assert bot_range_state(
        bot(
            current_market_price=Decimal(
                "0.001500"
            )
        )
    ) == "in_range"

    assert bot_range_state(
        bot(
            current_market_price=Decimal(
                "0.002500"
            )
        )
    ) == "in_range"


def test_range_state_below_grid() -> None:
    assert bot_range_state(
        bot(
            current_market_price=Decimal(
                "0.001499"
            )
        )
    ) == "out_of_range"


def test_range_state_above_grid() -> None:
    assert bot_range_state(
        bot(
            current_market_price=Decimal(
                "0.002501"
            )
        )
    ) == "out_of_range"


def test_range_state_missing_price_is_unknown() -> None:
    assert bot_range_state(
        bot(
            current_market_price=None
        )
    ) == "unknown"


def test_range_state_bad_range_is_unknown() -> None:
    assert bot_range_state(
        bot(
            price_range="not-a-range"
        )
    ) == "unknown"


def test_non_running_bot_is_not_applicable() -> None:
    assert bot_range_state(
        bot(
            status="stopped"
        )
    ) == "not_applicable"


def test_non_spot_grid_is_not_applicable() -> None:
    assert bot_range_state(
        bot(
            strategy_type="futures_grid"
        )
    ) == "not_applicable"
