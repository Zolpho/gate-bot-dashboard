from app.trading_recent_orders import (
    build_recent_spot_orders,
)


def request(
    *,
    status="confirmed_open",
):
    return {
        "request_id": "req-1",
        "account_id": "arnold",
        "pair": "EQTY_USDT",
        "status": status,
        "gate_order_id": "123",
        "response": {
            "gate_response": {
                "id": "123",
                "status": "open",
                "finish_as": "open",
                "filled_amount": "0",
                "filled_total": "0",
            },
        },
    }


def test_execution_snapshot_used_without_cancel():
    rows = build_recent_spot_orders(
        requests=[
            request(),
        ],
        cancellations_by_request_id={},
    )

    assert len(rows) == 1

    row = rows[0]

    assert row["managed"] is True

    assert (
        row["history_source"]
        == "dashboard_audit"
    )

    assert (
        row["gate_snapshot_source"]
        == "execution"
    )

    assert (
        row["gate_status"]
        == "open"
    )

    assert (
        row["finish_as"]
        == "open"
    )

    assert (
        row["order_state"]
        ["effective_status"]
        == "confirmed_open"
    )


def test_cancel_snapshot_overrides_execution():
    rows = build_recent_spot_orders(
        requests=[
            request(),
        ],
        cancellations_by_request_id={
            "req-1": {
                "status": (
                    "confirmed_cancelled"
                ),
                "response": {
                    "gate_response": {
                        "id": "123",
                        "status": (
                            "cancelled"
                        ),
                        "finish_as": (
                            "cancelled"
                        ),
                        "filled_amount": "0",
                        "filled_total": "0",
                    },
                },
            },
        },
    )

    row = rows[0]

    assert (
        row["gate_snapshot_source"]
        == "cancellation"
    )

    assert (
        row["gate_status"]
        == "cancelled"
    )

    assert (
        row["finish_as"]
        == "cancelled"
    )

    assert (
        row["order_state"]
        ["execution_status"]
        == "confirmed_open"
    )

    assert (
        row["order_state"]
        ["cancellation_status"]
        == "confirmed_cancelled"
    )

    assert (
        row["order_state"]
        ["effective_status"]
        == "confirmed_cancelled"
    )

    assert (
        row["order_state"]["source"]
        == "cancellation"
    )


def test_cancel_state_survives_without_gate_snapshot():
    rows = build_recent_spot_orders(
        requests=[
            request(),
        ],
        cancellations_by_request_id={
            "req-1": {
                "status": (
                    "confirmed_cancelled"
                ),
                "response": {},
            },
        },
    )

    row = rows[0]

    assert (
        row["gate_snapshot_source"]
        == "execution"
    )

    assert (
        row["gate_status"]
        == "open"
    )

    assert (
        row["order_state"]
        ["effective_status"]
        == "confirmed_cancelled"
    )


def test_request_without_gate_response_remains_visible():
    local = request()
    local["response"] = {}

    rows = build_recent_spot_orders(
        requests=[
            local,
        ],
        cancellations_by_request_id={},
    )

    row = rows[0]

    assert (
        row["gate_order_id"]
        == "123"
    )

    assert (
        row["gate_snapshot"]
        is None
    )

    assert (
        row["gate_snapshot_source"]
        is None
    )

    assert (
        row["gate_status"]
        is None
    )

    assert (
        row["finish_as"]
        is None
    )


def test_non_dict_request_is_ignored():
    rows = build_recent_spot_orders(
        requests=[
            None,
            request(),
        ],
        cancellations_by_request_id={},
    )

    assert len(rows) == 1


def test_empty_cancel_gate_response_falls_back_cleanly():
    rows = build_recent_spot_orders(
        requests=[
            request(),
        ],
        cancellations_by_request_id={
            "req-1": {
                "status": (
                    "confirmed_cancelled"
                ),
                "response": {
                    "gate_response": {},
                },
            },
        },
    )

    row = rows[0]

    #
    # Empty cancellation Gate data is not a useful
    # snapshot, so retain the earlier execution
    # snapshot and label its source correctly.
    #
    assert (
        row["gate_snapshot_source"]
        == "execution"
    )

    assert (
        row["gate_status"]
        == "open"
    )

    assert (
        row["finish_as"]
        == "open"
    )

    #
    # The later local cancellation lifecycle still
    # determines the authoritative effective state.
    #
    assert (
        row["order_state"]
        ["effective_status"]
        == "confirmed_cancelled"
    )

    assert (
        row["order_state"]["source"]
        == "cancellation"
    )
