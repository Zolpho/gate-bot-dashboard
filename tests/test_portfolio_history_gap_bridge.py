from __future__ import annotations

import ast
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


METRICS_PATH = Path(
    "app/metrics.py"
)


PortfolioHistoryValues = tuple[
    Decimal | None,
    Decimal | None,
    Decimal | None,
    Decimal | None,
]


def _load_history_aggregator():
    """
    Execute the real helper function directly from app/metrics.py
    without importing the whole application module.

    The production module imports SQLAlchemy, but these semantic
    unit tests exercise a pure in-memory helper and should not
    depend on the host having the application dependency stack.
    """

    source = METRICS_PATH.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source,
        filename=str(
            METRICS_PATH
        ),
    )

    helper = next(
        (
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "_aggregate_portfolio_history_minutes"
            )
        ),
        None,
    )

    if helper is None:
        raise AssertionError(
            "History aggregation helper missing "
            "from app/metrics.py"
        )

    namespace = {
        "Any": Any,
        "Decimal": Decimal,
        "datetime": datetime,
        "timedelta": timedelta,
        "defaultdict": defaultdict,
        "bisect_left": bisect_left,
        "PortfolioHistoryValues": (
            PortfolioHistoryValues
        ),
        "PORTFOLIO_HISTORY_BRIDGE_WINDOW": (
            timedelta(
                minutes=3
            )
        ),
    }

    module = ast.Module(
        body=[
            helper,
        ],
        type_ignores=[],
    )

    ast.fix_missing_locations(
        module
    )

    exec(
        compile(
            module,
            filename=str(
                METRICS_PATH
            ),
            mode="exec",
        ),
        namespace,
    )

    return namespace[
        "_aggregate_portfolio_history_minutes"
    ]


_aggregate_portfolio_history_minutes = (
    _load_history_aggregator()
)


def _minute(
    offset: int,
) -> datetime:
    return (
        datetime(
            2026,
            10,
            2,
            12,
            0,
            tzinfo=timezone.utc,
        )
        + timedelta(
            minutes=offset
        )
    )


def _values(
    invest: str,
    current: str,
    pnl: str,
):
    value = Decimal(
        pnl
    )

    return (
        Decimal(
            invest
        ),
        Decimal(
            current
        ),
        value,
        value,
    )


def _by_minute(
    rows,
):
    return {
        row["captured_at"]: row
        for row in rows
    }


def test_short_interior_gap_uses_previous_known_bot_value():
    m0 = _minute(0)
    m1 = _minute(1)
    m2 = _minute(2)

    latest = {
        (m0, 1): _values(
            "100",
            "110",
            "10",
        ),
        (m1, 1): _values(
            "100",
            "111",
            "11",
        ),
        (m2, 1): _values(
            "100",
            "112",
            "12",
        ),
        (m0, 2): _values(
            "200",
            "220",
            "20",
        ),
        # bot 2 is absent only at m1
        (m2, 2): _values(
            "200",
            "222",
            "22",
        ),
    }

    rows = (
        _aggregate_portfolio_history_minutes(
            latest,
            {
                m0,
                m1,
                m2,
            },
        )
    )

    middle = _by_minute(
        rows
    )[
        m1.isoformat()
    ]

    assert (
        middle["current_value"]
        == 331.0
    )

    assert middle["pnl"] == 31.0
    assert middle["bot_count"] == 2

    assert (
        middle[
            "observed_bot_count"
        ]
        == 1
    )

    assert (
        middle[
            "carried_forward_bot_count"
        ]
        == 1
    )


def test_bot_is_not_carried_past_end_of_observed_lifecycle():
    m0 = _minute(0)
    m1 = _minute(1)
    m2 = _minute(2)

    latest = {
        (m0, 1): _values(
            "100",
            "110",
            "10",
        ),
        (m1, 1): _values(
            "100",
            "111",
            "11",
        ),
        (m2, 1): _values(
            "100",
            "112",
            "12",
        ),
        (m0, 2): _values(
            "200",
            "220",
            "20",
        ),
        # No later observation for bot 2.
    }

    rows = (
        _aggregate_portfolio_history_minutes(
            latest,
            {
                m0,
                m1,
                m2,
            },
        )
    )

    minute_one = _by_minute(
        rows
    )[
        m1.isoformat()
    ]

    assert (
        minute_one[
            "current_value"
        ]
        == 111.0
    )

    assert (
        minute_one[
            "bot_count"
        ]
        == 1
    )

    assert (
        minute_one[
            "carried_forward_bot_count"
        ]
        == 0
    )


def test_bot_is_not_backfilled_before_first_observation():
    m0 = _minute(0)
    m1 = _minute(1)
    m2 = _minute(2)

    latest = {
        (m0, 1): _values(
            "100",
            "110",
            "10",
        ),
        (m1, 1): _values(
            "100",
            "111",
            "11",
        ),
        (m2, 1): _values(
            "100",
            "112",
            "12",
        ),
        # A new bot begins at m2.
        (m2, 2): _values(
            "400",
            "401",
            "1",
        ),
    }

    rows = (
        _aggregate_portfolio_history_minutes(
            latest,
            {
                m0,
                m1,
                m2,
            },
        )
    )

    by_minute = _by_minute(
        rows
    )

    assert (
        by_minute[
            m1.isoformat()
        ][
            "bot_count"
        ]
        == 1
    )

    assert (
        by_minute[
            m2.isoformat()
        ][
            "bot_count"
        ]
        == 2
    )

    assert (
        by_minute[
            m2.isoformat()
        ][
            "carried_forward_bot_count"
        ]
        == 0
    )


def test_long_gap_is_not_bridged():
    m0 = _minute(0)
    m1 = _minute(1)
    m2 = _minute(2)
    m4 = _minute(4)

    latest = {
        (m0, 1): _values(
            "100",
            "110",
            "10",
        ),
        (m1, 1): _values(
            "100",
            "111",
            "11",
        ),
        (m2, 1): _values(
            "100",
            "112",
            "12",
        ),
        (m4, 1): _values(
            "100",
            "114",
            "14",
        ),
        (m0, 2): _values(
            "200",
            "220",
            "20",
        ),
        # Four-minute observation gap exceeds
        # the three-minute bridge window.
        (m4, 2): _values(
            "200",
            "224",
            "24",
        ),
    }

    rows = (
        _aggregate_portfolio_history_minutes(
            latest,
            {
                m0,
                m1,
                m2,
                m4,
            },
        )
    )

    by_minute = _by_minute(
        rows
    )

    assert (
        by_minute[
            m1.isoformat()
        ][
            "bot_count"
        ]
        == 1
    )

    assert (
        by_minute[
            m2.isoformat()
        ][
            "bot_count"
        ]
        == 1
    )

    assert (
        by_minute[
            m1.isoformat()
        ][
            "carried_forward_bot_count"
        ]
        == 0
    )


def test_helper_is_loaded_from_real_metrics_source():
    source = METRICS_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        "def _aggregate_portfolio_history_minutes("
        in source
    )

    assert (
        _aggregate_portfolio_history_minutes.__code__.co_filename
        == str(
            METRICS_PATH
        )
    )
