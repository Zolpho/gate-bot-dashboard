from app.trading_open_orders import (
    merge_open_spot_orders,
)


def gate_order(
    *,
    order_id="123",
    text="t-eq-test",
    status="open",
):
    return {
        "id": order_id,
        "text": text,
        "status": status,
        "currency_pair": "EQTY_USDT",
        "side": "buy",
        "amount": "2100",
        "price": "0.0015",
    }


def request(
    *,
    request_id="req-1",
    gate_order_id="123",
    gate_text="t-eq-test",
    status="confirmed_open",
):
    return {
        "request_id": request_id,
        "account_id": "arnold",
        "pair": "EQTY_USDT",
        "status": status,
        "gate_order_id": gate_order_id,
        "gate_text": gate_text,
    }


def test_managed_open_order_matches_gate_id():
    rows = merge_open_spot_orders(
        account_id="arnold",
        pair="EQTY_USDT",
        gate_orders=[
            gate_order(),
        ],
        local_requests=[
            request(),
        ],
        cancellations_by_request_id={},
    )

    assert len(rows) == 1

    row = rows[0]

    assert row["managed"] is True
    assert (
        row["match_method"]
        == "gate_order_id"
    )
    assert (
        row["identity_conflict"]
        is False
    )
    assert (
        row["state_conflict"]
        is False
    )
    assert (
        row["request"]["request_id"]
        == "req-1"
    )
    assert (
        row["order_state"]
        ["effective_status"]
        == "confirmed_open"
    )


def test_unmanaged_gate_order_is_visible():
    rows = merge_open_spot_orders(
        account_id="arnold",
        pair="EQTY_USDT",
        gate_orders=[
            gate_order(),
        ],
        local_requests=[],
        cancellations_by_request_id={},
    )

    row = rows[0]

    assert row["managed"] is False
    assert (
        row["match_method"]
        == "none"
    )
    assert row["request"] is None
    assert row["cancellation"] is None

    assert row["order_state"] == {
        "execution_status": None,
        "cancellation_status": None,
        "effective_status": "open",
        "source": "gate",
    }


def test_gate_text_can_recover_audit_match():
    rows = merge_open_spot_orders(
        account_id="arnold",
        pair="EQTY_USDT",
        gate_orders=[
            gate_order(
                order_id="555",
                text="t-eq-recovery",
            ),
        ],
        local_requests=[
            request(
                gate_order_id="",
                gate_text="t-eq-recovery",
                status="uncertain",
            ),
        ],
        cancellations_by_request_id={},
    )

    row = rows[0]

    assert row["managed"] is True
    assert (
        row["match_method"]
        == "gate_text"
    )
    assert (
        row["request"]["request_id"]
        == "req-1"
    )


def test_cross_identity_conflict_fails_closed():
    rows = merge_open_spot_orders(
        account_id="arnold",
        pair="EQTY_USDT",
        gate_orders=[
            gate_order(
                order_id="123",
                text="t-eq-other",
            ),
        ],
        local_requests=[
            request(
                request_id="req-id",
                gate_order_id="123",
                gate_text="t-eq-one",
            ),
            request(
                request_id="req-text",
                gate_order_id="999",
                gate_text="t-eq-other",
            ),
        ],
        cancellations_by_request_id={},
    )

    row = rows[0]

    assert row["managed"] is False
    assert (
        row["match_method"]
        == "conflict"
    )
    assert (
        row["identity_conflict"]
        is True
    )
    assert row["request"] is None


def test_terminal_local_state_vs_gate_open_is_flagged():
    local = request(
        status="confirmed_open",
    )

    rows = merge_open_spot_orders(
        account_id="arnold",
        pair="EQTY_USDT",
        gate_orders=[
            gate_order(),
        ],
        local_requests=[
            local,
        ],
        cancellations_by_request_id={
            "req-1": {
                "status": (
                    "confirmed_cancelled"
                ),
            },
        },
    )

    row = rows[0]

    assert row["managed"] is True
    assert (
        row["order_state"]
        ["effective_status"]
        == "confirmed_cancelled"
    )
    assert (
        row["state_conflict"]
        is True
    )


def test_other_account_request_cannot_manage_order():
    foreign = request()
    foreign["account_id"] = "eqtydao"

    rows = merge_open_spot_orders(
        account_id="arnold",
        pair="EQTY_USDT",
        gate_orders=[
            gate_order(),
        ],
        local_requests=[
            foreign,
        ],
        cancellations_by_request_id={},
    )

    assert (
        rows[0]["managed"]
        is False
    )


def test_other_pair_request_cannot_manage_order():
    foreign = request()
    foreign["pair"] = "BTC_USDT"

    rows = merge_open_spot_orders(
        account_id="arnold",
        pair="EQTY_USDT",
        gate_orders=[
            gate_order(),
        ],
        local_requests=[
            foreign,
        ],
        cancellations_by_request_id={},
    )

    assert (
        rows[0]["managed"]
        is False
    )
