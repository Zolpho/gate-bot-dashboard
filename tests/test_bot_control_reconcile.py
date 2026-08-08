from __future__ import annotations

from app.bot_control_reconcile import (
    classify_stop_status,
    match_spot_grid_candidates,
)


def make_record() -> dict:
    return {
        "created_at": (
            "2026-08-08T10:00:00+00:00"
        ),
        "request": {
            "gate_payload": {
                "strategy_type": "spot_grid",
                "market": "EQTY_USDT",
                "create_params": {
                    "money": "100",
                },
            },
        },
    }


def test_create_candidate_matches_money_and_time():
    items = [{
        "strategy_id": "123",
        "strategy_type": "spot_grid",
        "strategy_name": "Spot Grid",
        "market": "EQTY_USDT",
        "status": "running",
        "invest_amount": "100.000000",
        "created_at": (
            "2026-08-08T10:01:00+00:00"
        ),
    }]

    matches = match_spot_grid_candidates(
        make_record(),
        items,
    )

    assert len(matches) == 1
    assert matches[0]["strategy_id"] == "123"
    assert matches[0]["time_match"] is True


def test_create_candidate_rejects_wrong_money():
    items = [{
        "strategy_id": "123",
        "strategy_type": "spot_grid",
        "market": "EQTY_USDT",
        "invest_amount": "200",
        "created_at": (
            "2026-08-08T10:01:00+00:00"
        ),
    }]

    matches = match_spot_grid_candidates(
        make_record(),
        items,
    )

    assert matches == []


def test_create_candidate_rejects_old_strategy():
    items = [{
        "strategy_id": "123",
        "strategy_type": "spot_grid",
        "market": "EQTY_USDT",
        "invest_amount": "100",
        "created_at": (
            "2026-08-08T09:30:00+00:00"
        ),
    }]

    matches = match_spot_grid_candidates(
        make_record(),
        items,
    )

    assert matches == []


def test_stop_status_stopped_is_definitive():
    outcome, confidence, _ = (
        classify_stop_status(
            "stopped"
        )
    )

    assert outcome == "confirmed_stopped"
    assert confidence == "definitive"


def test_stop_status_stopping_is_in_progress():
    outcome, confidence, _ = (
        classify_stop_status(
            "stopping"
        )
    )

    assert outcome == "stop_in_progress"
    assert confidence == "high"


def test_stop_status_running_does_not_allow_retry():
    outcome, confidence, _ = (
        classify_stop_status(
            "running"
        )
    )

    assert outcome == "observed_running"
    assert confidence == "high"
