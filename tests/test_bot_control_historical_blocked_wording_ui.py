from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

JS = (
    ROOT / "frontend" / "app.js"
).read_text()


FUNCTION_PATTERN = re.compile(
    r"^(?:async\s+)?function\s+"
    r"([A-Za-z0-9_$]+)\s*\(",
    re.M,
)


def function(name):
    matches = list(
        FUNCTION_PATTERN.finditer(JS)
    )

    found = []

    for index, match in enumerate(matches):
        if match.group(1) != name:
            continue

        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(JS)
        )

        found.append(
            JS[match.start():end]
        )

    assert len(found) == 1

    return found[0]


def test_historical_lock_conflict_detection_is_narrow():
    block = function(
        "renderBotControlRequestDetail"
    )

    assert "historicalLockConflict" in block
    assert "requestStatus === 'blocked'" in block
    assert "=== 'bot_stop'" in block
    assert (
        "'already locked by another bot control operation'"
        in block
    )


def test_original_outcome_is_historical():
    block = function(
        "renderBotControlRequestDetail"
    )

    assert (
        "Original outcome: This Stop request was"
        in block
    )

    assert (
        "blocked because another Bot Control"
        in block
    )

    assert (
        "The Stop operation did not reach Gate."
        in block
    )


def test_persisted_blocked_status_still_drives_status_badge():
    block = function(
        "renderBotControlRequestDetail"
    )

    assert (
        "reconciliationLabel(detail.status)"
        in block
    )

    assert not re.search(
        r"\bdetail\.status\s*=(?!=)",
        block,
    )


def test_current_state_explains_old_lock_is_gone():
    block = function(
        "renderBotControlRequestDetail"
    )

    assert "&& !lock" in block

    assert (
        "Current state: The conflicting lock is no"
        in block
    )

    assert "longer active." in block


def test_observed_running_requires_new_stop_request():
    block = function(
        "renderBotControlRequestDetail"
    )

    assert "currentlyObservedRunning" in block

    assert (
        "Gate currently reports the strategy"
        in block
    )

    assert (
        "This historical Stop"
        in block
    )

    assert (
        "request will not be retried"
        in block
    )

    assert "Create a new Stop" in block


def test_no_reconciliation_gets_read_only_guidance():
    block = function(
        "renderBotControlRequestDetail"
    )

    assert (
        "Reconcile with Gate before deciding"
        in block
    )

    assert (
        "whether a new Stop request is needed."
        in block
    )


def test_generic_error_rejected_and_monitor_paths_remain():
    block = function(
        "renderBotControlRequestDetail"
    )

    assert ": detail.error" in block
    assert "detail.status === 'rejected'" in block

    assert (
        "Read-only reconciliation uses the Monitor"
        in block
    )


def test_request_detail_renderer_remains_read_only():
    block = function(
        "renderBotControlRequestDetail"
    )

    for expression in (
        r"\bmethod\s*:\s*['\"]POST['\"]",
        r"\bmethod\s*:\s*['\"]PATCH['\"]",
        r"\bmethod\s*:\s*['\"]DELETE['\"]",
    ):
        assert not re.search(
            expression,
            block,
            re.I,
        )


def test_reconciliation_history_is_action_aware():
    block = function(
        "renderBotControlReconciliationHistory"
    )

    assert "action = ''" in block
    assert "historicalStopStillRunning" in block
    assert "=== 'bot_stop'" in block
    assert "outcome === 'observed_running'" in block


def test_history_refines_observed_running_stop_summary():
    block = function(
        "renderBotControlReconciliationHistory"
    )

    assert (
        "This historical Stop request"
        in block
    )

    assert (
        "will not be retried automatically."
        in block
    )

    assert (
        "Create a new Stop request only if you"
        in block
    )

    assert (
        "still want to stop the strategy."
        in block
    )


def test_other_history_rows_keep_persisted_summary_fallback():
    block = function(
        "renderBotControlReconciliationHistory"
    )

    assert "row.summary || '—'" in block
    assert "escapeHtml(summary)" in block

    assert (
        block.index("row.summary || '—'")
        < block.index("escapeHtml(summary)")
    )


def test_request_detail_passes_action_to_history():
    block = function(
        "renderBotControlRequestDetail"
    )

    assert re.search(
        r"renderBotControlReconciliationHistory\(\s*"
        r"detail\.reconciliations\s*"
        r"\|\|\s*\[\],\s*"
        r"detail\.action\s*"
        r"\|\|\s*'',\s*"
        r"\);",
        block,
        re.S,
    )


def test_no_active_lock_display_is_preserved():
    block = function(
        "renderBotControlRequestDetail"
    )

    assert "'No active lock'" in block
