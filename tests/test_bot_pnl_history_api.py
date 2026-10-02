from datetime import (
    datetime,
    timedelta,
    timezone,
)
from decimal import Decimal

from fastapi.testclient import TestClient

from app.api.bots import (
    _downsample_total_profit_rows,
)
from app.main import app


def _rows(
    count: int,
) -> list[
    tuple[
        datetime,
        Decimal,
    ]
]:
    start = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    rows = []

    for index in range(
        count
    ):
        value = Decimal(
            str(
                (
                    (index % 37)
                    - 18
                )
                * 1.25
            )
        )

        rows.append(
            (
                start
                + timedelta(
                    minutes=index,
                ),
                value,
            )
        )

    return rows


def test_downsample_returns_small_series_unchanged():
    rows = _rows(
        120
    )

    assert (
        _downsample_total_profit_rows(
            rows,
            1600,
        )
        == rows
    )


def test_downsample_bounds_large_series_and_preserves_ends():
    rows = _rows(
        10000
    )

    sampled = (
        _downsample_total_profit_rows(
            rows,
            1600,
        )
    )

    assert len(sampled) <= 1600
    assert sampled[0] == rows[0]
    assert sampled[-1] == rows[-1]

    timestamps = [
        row[0]
        for row in sampled
    ]

    assert timestamps == sorted(
        timestamps
    )


def test_downsample_preserves_global_peak_and_trough():
    rows = _rows(
        10000
    )

    rows[3210] = (
        rows[3210][0],
        Decimal("-999"),
    )

    rows[7654] = (
        rows[7654][0],
        Decimal("999"),
    )

    sampled = (
        _downsample_total_profit_rows(
            rows,
            1600,
        )
    )

    values = {
        row[1]
        for row in sampled
    }

    assert Decimal("-999") in values
    assert Decimal("999") in values


def test_public_pnl_history_endpoint_is_lightweight_and_bounded():
    with TestClient(
        app
    ) as client:
        bots = client.get(
            "/api/bots"
        )

        assert (
            bots.status_code
            == 200
        )

        bot_id = (
            bots.json()[
                "items"
            ][0]["id"]
        )

        response = client.get(
            f"/api/bots/{bot_id}/pnl-history"
            "?hours=8760"
            "&max_points=200"
        )

        assert (
            response.status_code
            == 200
        )

        payload = (
            response.json()
        )

        assert (
            payload[
                "max_points"
            ]
            == 200
        )

        assert (
            payload[
                "plotted_points"
            ]
            <= 200
        )

        assert (
            payload[
                "source_points"
            ]
            >= payload[
                "plotted_points"
            ]
        )

        for item in payload[
            "items"
        ]:
            assert set(
                item
            ) == {
                "captured_at",
                "total_profit",
            }


def test_pnl_history_rejects_excessive_point_request():
    with TestClient(
        app
    ) as client:
        bots = client.get(
            "/api/bots"
        )

        bot_id = (
            bots.json()[
                "items"
            ][0]["id"]
        )

        response = client.get(
            f"/api/bots/{bot_id}/pnl-history"
            "?max_points=5001"
        )

        assert (
            response.status_code
            == 422
        )


def test_bot_detail_can_skip_expensive_analytics():
    with TestClient(
        app
    ) as client:
        bots = client.get(
            "/api/bots"
        )

        assert (
            bots.status_code
            == 200
        )

        bot_id = (
            bots.json()[
                "items"
            ][0]["id"]
        )

        normal = client.get(
            f"/api/bots/{bot_id}"
        )

        assert (
            normal.status_code
            == 200
        )

        assert (
            normal.json()[
                "analytics"
            ]
            is not None
        )

        fast = client.get(
            f"/api/bots/{bot_id}"
            "?include_analytics=false"
        )

        assert (
            fast.status_code
            == 200
        )

        assert (
            fast.json()[
                "analytics"
            ]
            is None
        )

        assert (
            fast.json()[
                "bot"
            ]["id"]
            == bot_id
        )
