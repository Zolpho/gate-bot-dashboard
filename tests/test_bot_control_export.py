from __future__ import annotations

import json

from app.bot_control_export import (
    build_bot_control_csv,
    build_bot_control_json,
    csv_safe_cell,
    empty_export,
    redact_sensitive,
)


def test_sensitive_values_are_redacted():
    value = {
        "market": "EQTY_USDT",
        "api_key": "abc",
        "nested": {
            "secret": "xyz",
            "strategy_id": "123",
        },
    }

    result = redact_sensitive(
        value
    )

    assert (
        result["api_key"]
        == "[REDACTED]"
    )

    assert (
        result["nested"]["secret"]
        == "[REDACTED]"
    )

    assert (
        result["nested"][
            "strategy_id"
        ]
        == "123"
    )


def test_csv_formula_injection_is_neutralized():
    assert (
        csv_safe_cell(
            "=2+2"
        )
        == "'=2+2"
    )

    assert (
        csv_safe_cell(
            "+SUM(A1:A2)"
        )
        == "'+SUM(A1:A2)"
    )

    assert (
        csv_safe_cell(
            "normal"
        )
        == "normal"
    )


def test_empty_json_export_is_valid():
    document = empty_export()

    payload = json.loads(
        build_bot_control_json(
            document
        )
    )

    assert payload["count"] == 0
    assert payload["items"] == []


def test_csv_contains_expected_columns():
    document = {
        "generated_at": (
            "2026-08-08T12:00:00+00:00"
        ),
        "count": 1,
        "items": [{
            "request_id": "test-request",
            "account_id": "zolnode",
            "username": "zolnode",
            "action": "spot_grid_create",
            "status": "simulated",
            "strategy_id": None,
            "gate_status_code": None,
            "gate_label": None,
            "error": "",
            "created_at": (
                "2026-08-08T12:00:00"
            ),
            "completed_at": (
                "2026-08-08T12:00:01"
            ),
            "request": {
                "gate_payload": {
                    "market": "EQTY_USDT",
                    "create_params": {
                        "money": "100",
                        "grid_num": 10,
                    },
                },
            },
            "response": {
                "simulation": True,
                "write_performed": False,
            },
            "operation_lock": None,
            "reconciliations": [],
            "lock_resolutions": [],
        }],
    }

    csv_text = (
        build_bot_control_csv(
            document
        )
    )

    assert "request_id" in csv_text
    assert "EQTY_USDT" in csv_text
    assert "spot_grid_create" in csv_text
    assert "test-request" in csv_text
