from __future__ import annotations

from pathlib import Path

import app.api.trading as trading_api


def test_order_rows_attach_amendment_history(
    monkeypatch,
):
    histories = {
        "order-1": [
            {
                "amend_request_id": "amend-2",
                "order_request_id": "order-1",
                "status": "uncertain",
                "current_price": "1",
                "requested_price": "2",
                "completed_at": None,
            },
            {
                "amend_request_id": "amend-1",
                "order_request_id": "order-1",
                "status": "confirmed_amended",
                "current_price": "0.9",
                "requested_price": "1",
                "completed_at": "done",
            },
        ],
    }

    captured = {}

    def fake_bulk(request_ids):
        captured["ids"] = set(
            request_ids
        )
        return histories

    monkeypatch.setattr(
        trading_api,
        "list_order_amendments_for_requests",
        fake_bulk,
    )

    original = {
        "managed": True,
        "request": {
            "request_id": "order-1",
        },
    }

    rows = (
        trading_api
        ._order_rows_with_amendment_read_model(
            [original]
        )
    )

    assert captured["ids"] == {
        "order-1",
    }

    assert len(rows) == 1

    row = rows[0]

    assert row is not original
    assert "amendments" not in original

    assert row[
        "amendment_count"
    ] == 2

    assert row[
        "latest_amendment"
    ][
        "amend_request_id"
    ] == "amend-2"

    assert row[
        "active_amendment"
    ][
        "amend_request_id"
    ] == "amend-2"

    assert [
        item["amend_request_id"]
        for item in row["amendments"]
    ] == [
        "amend-2",
        "amend-1",
    ]


def test_unmanaged_row_has_empty_amendment_state(
    monkeypatch,
):
    captured = {}

    def fake_bulk(request_ids):
        captured["ids"] = set(
            request_ids
        )
        return {}

    monkeypatch.setattr(
        trading_api,
        "list_order_amendments_for_requests",
        fake_bulk,
    )

    rows = (
        trading_api
        ._order_rows_with_amendment_read_model(
            [
                {
                    "managed": False,
                    "request": None,
                }
            ]
        )
    )

    assert captured["ids"] == set()

    row = rows[0]

    assert row["amendments"] == []
    assert row["amendment_count"] == 0
    assert row["latest_amendment"] is None
    assert row["active_amendment"] is None


def test_frontend_capabilities_fail_closed_for_amendment():
    text = Path(
        "frontend/trading-limit.js"
    ).read_text()

    required = (
        "result.amendment_implemented !== true",
        "result.amendment_route_available !== true",
        "typeof result.amend_arm_enabled !== 'boolean'",
        "result.amend_reconciliation_implemented !== true",
        "result.amend_reconciliation_route_available !== true",
        "result.amend_reconciliation_gate_get_only !== true",
        "amendment_implemented: false",
        "amendment_route_available: false",
        "amend_arm_enabled: false",
        "amend_reconciliation_implemented: false",
        "amend_reconciliation_route_available: false",
        "amend_reconciliation_gate_get_only: false",
    )

    for item in required:
        assert item in text


def test_frontend_amendment_visibility_coexists_with_guarded_action():
    trading = Path(
        "frontend/trading.js"
    ).read_text()

    limit = Path(
        "frontend/trading-limit.js"
    ).read_text()

    html = Path(
        "frontend/index.html"
    ).read_text()

    assert (
        "function tradingOrderAmendmentReadModel("
        in trading
    )

    assert html.count(
        "<th>Amendment</th>"
    ) == 2

    # B1 amendment mutation remains exactly one
    # isolated browser action.
    assert trading.count(
        "+ '/amend'"
    ) == 1

    assert (
        "async function tradingAmendPersistentOpenOrder("
        in trading
    )

    # The recovery module itself remains free of
    # amendment mutation/reconciliation routes.
    assert "/amend" not in limit

    assert (
        ".amend_arm_enabled"
        in trading
    )

    assert (
        "label: 'Amend disabled'"
        in trading
    )


def test_guarded_notice_describes_capability_gated_actions():
    html = Path(
        "frontend/index.html"
    ).read_text()

    # HTML source is deliberately wrapped across lines;
    # browsers collapse that whitespace when rendered.
    html = " ".join(
        html.split()
    )

    assert (
        "Eligible dashboard-managed open orders"
        in html
    )

    assert (
        "cancellation"
        in html
    )

    assert (
        "price-amend actions"
        in html
    )

    assert (
        "corresponding capability"
        in html
    )

    assert (
        "order passes its safety checks"
        in html
    )

    # The notice must not hard-code a transient
    # runtime arm state. Live capabilities control
    # whether the browser exposes each action.
    assert (
        "remains separately disarmed"
        not in html
    )

    assert (
        "amendment arm is disarmed"
        not in html
    )

    assert (
        "remains unavailable"
        not in html
    )


def test_passive_amendment_capabilities_follow_trading_lifecycle():
    core = Path(
        "frontend/trading.js"
    ).read_text()

    limit = Path(
        "frontend/trading-limit.js"
    ).read_text()

    clear_start = limit.index(
        "function clearTradingLimitOrderPreview("
    )

    clear_end = limit.index(
        "\nfunction resetTradingLimitOrderTicket(",
        clear_start,
    )

    clear_block = limit[
        clear_start:
        clear_end
    ]

    assert (
        "limitOrderExecutionCapabilities = null"
        not in clear_block
    )

    activate_start = core.index(
        "async function activateTradingTab("
    )

    activate_end = core.index(
        "\nfunction resetTradingTab(",
        activate_start,
    )

    activate_block = core[
        activate_start:
        activate_end
    ]

    assert (
        "window.loadTradingExecutionCapabilities"
        in activate_block
    )

    assert (
        "await loadCapabilities();"
        in activate_block
    )

    reset_start = core.index(
        "function resetTradingTab("
    )

    reset_end = core.index(
        "\nfunction bindTradingEvents(",
        reset_start,
    )

    reset_block = core[
        reset_start:
        reset_end
    ]

    assert (
        "limitOrderExecutionCapabilities = null"
        in reset_block
    )

    assert (
        "function tradingRenderPersistentOrders("
        in core
    )

    assert (
        "window.tradingRenderPersistentOrders = ("
        in core
    )

    assert (
        "window.loadTradingExecutionCapabilities = ("
        in limit
    )

    loader_start = limit.index(
        "async function loadTradingExecutionCapabilities("
    )

    loader_end = limit.index(
        "\nfunction renderTradingLimitOrderPreview(",
        loader_start,
    )

    loader_block = limit[
        loader_start:
        loader_end
    ]

    assert (
        "window.tradingRenderPersistentOrders();"
        in loader_block
    )
