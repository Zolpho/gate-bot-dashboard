from __future__ import annotations

from app.bot_control_attention import (
    attention_reasons,
    attention_severity,
    recommended_action,
)


def test_uncertain_needs_attention():
    reasons = attention_reasons(
        status="uncertain",
        lock_state="held",
        reconciliation_outcome=(
            "inconclusive"
        ),
    )

    assert (
        "request_status:uncertain"
        in reasons
    )

    assert (
        "operation_lock:held"
        in reasons
    )


def test_simulated_without_lock_is_clean():
    assert attention_reasons(
        status="simulated",
        lock_state=None,
        reconciliation_outcome=(
            "not_applicable"
        ),
    ) == []


def test_held_lock_is_high_severity():
    assert attention_severity(
        status="succeeded",
        lock_state="held",
        reconciliation_outcome=None,
    ) == "high"


def test_probable_create_is_high():
    assert attention_severity(
        status="uncertain",
        lock_state="held",
        reconciliation_outcome=(
            "probable_created"
        ),
    ) == "high"


def test_uncertain_without_reconciliation():
    text = recommended_action(
        action="spot_grid_create",
        status="uncertain",
        lock_state="held",
        reconciliation_outcome=None,
        has_reconciliation=False,
        latest_resolution_type=None,
        latest_resolution_decision=None,
    )

    assert "reconciliation" in text.lower()
    assert "do not retry" in text.lower()


def test_stop_in_progress_stays_locked():
    text = recommended_action(
        action="bot_stop",
        status="uncertain",
        lock_state="held",
        reconciliation_outcome=(
            "stop_in_progress"
        ),
        has_reconciliation=True,
        latest_resolution_type=None,
        latest_resolution_decision=None,
    )

    assert "keep the lock held" in text.lower()
