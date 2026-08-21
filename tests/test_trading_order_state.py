import pytest

from app.trading_order_state import (
    derive_trading_order_state,
)


def request(
    status="confirmed_open",
):
    return {
        "status": status,
    }


@pytest.mark.parametrize(
    "cancel_status",
    [
        "cancelled",
        "confirmed_cancelled",
        "already_cancelled",
    ],
)
def test_cancelled_overrides_open(
    cancel_status,
):
    state = derive_trading_order_state(
        request=request(),
        cancellation={
            "status": cancel_status,
        },
    )

    assert (
        state["execution_status"]
        == "confirmed_open"
    )

    assert (
        state["cancellation_status"]
        == cancel_status
    )

    assert (
        state["effective_status"]
        == "confirmed_cancelled"
    )

    assert (
        state["source"]
        == "cancellation"
    )


def test_finished_cancel_precheck_overrides_open():
    state = derive_trading_order_state(
        request=request(),
        cancellation={
            "status": "confirmed_finished",
        },
    )

    assert (
        state["effective_status"]
        == "confirmed_closed"
    )

    assert (
        state["source"]
        == "cancellation"
    )


@pytest.mark.parametrize(
    "cancel_status",
    [
        "cancelling",
        "uncertain",
        "attention",
        "lookup_error",
    ],
)
def test_uncertain_cancel_overrides_open(
    cancel_status,
):
    state = derive_trading_order_state(
        request=request(),
        cancellation={
            "status": cancel_status,
        },
    )

    assert (
        state["effective_status"]
        == "uncertain"
    )

    assert (
        state["source"]
        == "cancellation"
    )


def test_no_cancellation_preserves_execution_state():
    state = derive_trading_order_state(
        request=request(),
        cancellation=None,
    )

    assert state == {
        "execution_status": (
            "confirmed_open"
        ),
        "cancellation_status": None,
        "effective_status": (
            "confirmed_open"
        ),
        "source": "execution",
    }


def test_definitive_cancel_rejection_does_not_fake_cancel():
    state = derive_trading_order_state(
        request=request(),
        cancellation={
            "status": "rejected",
        },
    )

    assert (
        state["effective_status"]
        == "confirmed_open"
    )

    assert (
        state["source"]
        == "execution"
    )
