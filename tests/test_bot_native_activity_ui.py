from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess

from app.bot_native_activity import (
    normalize_native_activity,
)


ROOT = Path(__file__).resolve().parents[1]

INDEX = (
    ROOT
    / "frontend"
    / "index.html"
)

APP = (
    ROOT
    / "frontend"
    / "app.js"
)

VIEW = (
    ROOT
    / "frontend"
    / "bot-native-activity.js"
)

STYLES = (
    ROOT
    / "frontend"
    / "styles.css"
)

AURORA = (
    ROOT
    / "frontend"
    / "aurora-bot-details.css"
)


class _StructureParser(
    HTMLParser
):
    def __init__(self) -> None:
        super().__init__()
        self.sequence: list[
            tuple[
                str,
                str,
                str,
            ]
        ] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[
            tuple[
                str,
                str | None,
            ]
        ],
    ) -> None:
        values = dict(
            attrs
        )

        self.sequence.append(
            (
                tag,
                values.get(
                    "id",
                    "",
                )
                or "",
                values.get(
                    "class",
                    "",
                )
                or "",
            )
        )


def _normalized_activity() -> dict:
    strategy_id = "5453981"

    open_payload = {
        "code": 200,
        "data": {
            "ask": [
                {
                    "id": 1,
                    "order_id": 1938066916,
                    "strategy_id": 5453981,
                    "positive_order_id": 1938066617,
                    "me_order_id": 1001,
                    "side": "sell",
                    "price": "0.001869",
                    "qty": "2121",
                    "match_price": "0.000000",
                    "match_qty": "0",
                    "match_amount": "0",
                    "fee": "0",
                    "profit": "0",
                    "status": "open",
                    "order_index": 3,
                    "order_type": "",
                    "create_time": 1791678911,
                    "gt_fee": "0",
                    "point_fee": "0",
                    "market": "EQTY_USDT",
                    "vip": -1,
                    "vip_fee_discount": "1",
                }
            ],
            "bid": [
                {
                    "id": 2,
                    "order_id": 1937998121,
                    "strategy_id": 5453981,
                    "positive_order_id": 0,
                    "me_order_id": 1002,
                    "side": "buy",
                    "price": "0.001831",
                    "qty": "2165",
                    "match_price": "0.000000",
                    "match_qty": "0",
                    "match_amount": "0",
                    "fee": "0",
                    "profit": "0",
                    "status": "open",
                    "order_index": 1,
                    "order_type": "",
                    "create_time": 1791666711,
                    "gt_fee": "0",
                    "point_fee": "0",
                    "market": "EQTY_USDT",
                    "vip": -1,
                    "vip_fee_discount": "1",
                }
            ],
            "total_qty": "0",
            "total_match_qty": "0",
        },
    }

    trade_payload = {
        "code": 200,
        "page": 1,
        "pagesize": 30,
        "pagecount": 2,
        "totalcount": 34,
        "data": [
            {
                "id": 3,
                "order_id": 1938066617,
                "strategy_id": 5453981,
                "positive_order_id": 0,
                "me_order_id": 1003,
                "side": "buy",
                "price": "0.00185",
                "qty": "2121",
                "match_price": "0.00185",
                "match_qty": "2121",
                "match_amount": "3.92385",
                "fee": "2.07858",
                "profit": "0",
                "status": "finished",
                "finish_as": "filled",
                "order_index": 2,
                "order_type": "",
                "create_time": 1791678906,
                "finish_time": 1791678911,
                "gt_fee": "0",
                "point_fee": "0",
                "market": "EQTY_USDT",
                "vip": -1,
                "vip_fee_discount": "1",
            },
            {
                "id": 4,
                "order_id": 1937810978,
                "strategy_id": 5453981,
                "positive_order_id": 1937734062,
                "me_order_id": 1004,
                "side": "sell",
                "price": "0.001869",
                "qty": "2121",
                "match_price": "0.001869",
                "match_qty": "2121",
                "match_amount": "3.964149",
                "fee": "0.00388486602",
                "profit": "0.03641413398",
                "status": "finished",
                "finish_as": "filled",
                "order_index": 3,
                "order_type": "",
                "create_time": 1791642908,
                "finish_time": 1791678906,
                "gt_fee": "0",
                "point_fee": "0",
                "market": "EQTY_USDT",
                "vip": -1,
                "vip_fee_discount": "1",
            },
        ],
    }

    return normalize_native_activity(
        strategy_id=strategy_id,
        open_orders_payload=open_payload,
        trades_payload=trade_payload,
    )


def _render_with_node(
    activity: dict,
) -> dict:
    runner = r"""
const fs = require('fs');
const vm = require('vm');

global.window = {};

vm.runInThisContext(
  fs.readFileSync(
    'frontend/bot-native-activity.js',
    'utf8',
  ),
  {
    filename:
      'frontend/bot-native-activity.js',
  },
);

const payload = JSON.parse(
  fs.readFileSync(
    0,
    'utf8',
  ),
);

const result =
  window.BotNativeActivityView.render(
    payload.activity,
    payload.context,
  );

process.stdout.write(
  JSON.stringify(result)
);
"""

    result = subprocess.run(
        [
            "node",
            "-e",
            runner,
        ],
        cwd=ROOT,
        input=json.dumps(
            {
                "activity": activity,
                "context": {
                    "baseAsset": "EQTY",
                    "quoteAsset": "USDT",
                },
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )

    return json.loads(
        result.stdout
    )


def test_bot_detail_places_activity_after_cumulative_return() -> None:
    parser = _StructureParser()

    parser.feed(
        INDEX.read_text(
            encoding="utf-8"
        )
    )

    identifiers = [
        item[1]
        for item in parser.sequence
        if item[1]
    ]

    cumulative = identifiers.index(
        "cumulativeReturnPanel"
    )

    activity = identifiers.index(
        "botNativeActivityPanel"
    )

    definition = identifiers.index(
        "botDefinitionList"
    )

    assert (
        cumulative
        < activity
        < definition
    )


def test_bot_detail_activity_has_expected_tables_and_counters() -> None:
    parser = _StructureParser()

    parser.feed(
        INDEX.read_text(
            encoding="utf-8"
        )
    )

    identifiers = {
        item[1]
        for item in parser.sequence
        if item[1]
    }

    assert {
        "botNativeActivityPanel",
        "botNativeActivityStatus",
        "botNativeOpenCount",
        "botNativeSellCount",
        "botNativeBuyCount",
        "botNativeTradeCount",
        "botNativeProfitCount",
        "botNativeOpenOrders",
        "botNativeTrades",
    }.issubset(
        identifiers
    )


def test_native_activity_view_renders_normalized_gate_contract() -> None:
    rendered = _render_with_node(
        _normalized_activity()
    )

    assert rendered[
        "strategyId"
    ] == "5453981"

    assert rendered[
        "counters"
    ] == {
        "openCount": 2,
        "sellCount": 1,
        "buyCount": 1,
        "tradeCount": 34,
        "profitCount": 1,
        "returnedTradeCount": 2,
    }

    assert (
        "0.001869 USDT"
        in rendered[
            "openRowsHtml"
        ]
    )

    assert (
        "2121 EQTY"
        in rendered[
            "openRowsHtml"
        ]
    )

    assert (
        "1938066617"
        in rendered[
            "openRowsHtml"
        ]
    )

    assert (
        "1938066916"
        in rendered[
            "openRowsHtml"
        ]
    )

    assert (
        "0.03641413398 USDT"
        in rendered[
            "tradeRowsHtml"
        ]
    )

    assert (
        "3.964149 USDT"
        in rendered[
            "tradeRowsHtml"
        ]
    )

    assert (
        "2.07858 EQTY"
        in rendered[
            "tradeRowsHtml"
        ]
    )

    assert (
        "0.00388486602 USDT"
        in rendered[
            "tradeRowsHtml"
        ]
    )

    assert (
        "34 Gate trades · 2 shown"
        == rendered[
            "tradeStatus"
        ]
    )


def test_view_layer_contains_no_transport() -> None:
    source = VIEW.read_text(
        encoding="utf-8"
    )

    forbidden = (
        "fetch(",
        "XMLHttpRequest",
        "adminApi(",
        "api(",
        "/spot/",
        "/bot/",
        "/api/",
    )

    for marker in forbidden:
        assert marker not in source


def test_app_integration_does_not_add_native_activity_api_call() -> None:
    source = APP.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "function renderBotNativeActivity()"
    )

    end = source.index(
        "function renderBotDialog(detail)"
    )

    presentation = source[
        start:end
    ]

    assert "api(" not in presentation
    assert "adminApi(" not in presentation
    assert "fetch(" not in presentation

    assert (
        "state.currentBotNativeActivity"
        in presentation
    )

    assert (
        "window.BotNativeActivityView"
        in presentation
    )


def test_spot_and_infinity_are_the_only_initial_activity_types() -> None:
    source = APP.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "function botNativeActivityEligible("
    )

    end = source.index(
        "function renderBotNativeActivity()"
    )

    block = source[
        start:end
    ]

    assert "'spot_grid'" in block
    assert "'infinite_grid'" in block

    assert "'futures_grid'" not in block
    assert "'margin_grid'" not in block


def test_classic_and_aurora_have_native_activity_styles() -> None:
    classic = STYLES.read_text(
        encoding="utf-8"
    )

    aurora = AURORA.read_text(
        encoding="utf-8"
    )

    assert (
        ".bot-native-activity"
        in classic
    )

    assert (
        "#botDialog .bot-native-activity"
        in aurora
    )

    assert (
        "#botDialog .bot-native-table"
        in aurora
    )


def test_native_activity_renderer_loads_before_app() -> None:
    source = INDEX.read_text(
        encoding="utf-8"
    )

    native = source.index(
        "./bot-native-activity.js?"
    )

    app = source.index(
        "./app.js?"
    )

    assert native < app

    assert (
        "m421c=20261011-native-activity-view-v1"
        in source
    )


def test_activity_labels_distinguish_totals_from_rows_shown() -> None:
    source = INDEX.read_text(
        encoding="utf-8"
    )

    assert "Total trades" in source
    assert "Profit fills shown" in source
    assert "Grid index" in source

    assert "Grid-profit fills" not in source


def test_frontend_loads_native_activity_from_dashboard_api() -> None:
    source = APP.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "async function loadBotNativeActivity("
    )

    end = source.index(
        "function renderBotNativeActivity()",
        start,
    )

    loader = source[
        start:end
    ]

    assert "await api(" in loader

    assert (
        "/native-activity"
        in loader
    )

    assert (
        "?page=1&page_size=30"
        in loader
    )

    assert (
        "botNativeActivityRequestEpoch"
        in loader
    )

    assert (
        "state.currentBot !== botId"
        in loader
    )

    assert (
        "https://www.gate.com/apiw/"
        not in source
    )


def test_open_bot_starts_native_activity_after_initial_render() -> None:
    source = APP.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "async function openBot("
    )

    end = source.index(
        "function botNativeActivityEligible(",
        start,
    )

    block = source[
        start:end
    ]

    assert (
        "state.botNativeActivityRequestEpoch += 1;"
        in block
    )

    assert (
        "const nativeActivityRequestEpoch = ("
        in block
    )

    assert (
        "void loadBotNativeActivity("
        in block
    )

    assert (
        block.index(
            "renderBotDialog("
        )
        < block.index(
            "void loadBotNativeActivity("
        )
    )


def test_frontend_distinguishes_live_trades_from_session_bound_orders() -> None:
    source = APP.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "function renderBotNativeActivity()"
    )

    end = source.index(
        "function renderBotDialog(detail)",
        start,
    )

    block = source[
        start:end
    ]

    assert (
        "gate_web_session_required"
        in block
    )

    assert (
        "Open Orders require "
        in block
    )

    assert (
        "Gate web session required."
        in block
    )

    assert (
        "spot_grid_live_transport_unproven"
        in block
    )

    assert (
        "setCounter("
        in block
    )

    assert (
        "'open',"
        in block
    )

    assert (
        "'trades',"
        in block
    )


def test_spot_grid_live_trades_keep_open_orders_explicitly_unproven() -> None:
    source = APP.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "function renderBotNativeActivity()"
    )

    end = source.index(
        "function renderBotDialog(detail)",
        start,
    )

    block = source[
        start:end
    ]

    assert (
        "spot_grid_open_orders_unproven"
        in block
    )

    assert (
        "Spot Grid Open Orders "
        in block
    )

    assert (
        "not yet proven"
        in block
    )


def test_m422_app_cache_key_is_present() -> None:
    source = INDEX.read_text(
        encoding="utf-8"
    )

    assert (
        "m422=20261011-spot-grid-trades-v1"
        in source
    )
