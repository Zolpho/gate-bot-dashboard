from pathlib import Path
from types import SimpleNamespace

from app.api import auth as auth_api


def _accounts():
    return [
        SimpleNamespace(
            id="arnold",
            name="Arnold",
        ),
        SimpleNamespace(
            id="eqtydao",
            name="EQTY DAO",
        ),
        SimpleNamespace(
            id="reserves",
            name="Reserves",
        ),
        SimpleNamespace(
            id="zolnode",
            name="zolnode",
        ),
    ]


def _user():
    return SimpleNamespace(
        is_super_admin=True,
        can_manage=lambda account_id: True,
        safe_dict=lambda: {
            "username": "test-admin",
            "role": "super_admin",
        },
    )


def test_auth_capabilities_exposes_safe_account_live_boolean(
    monkeypatch,
):
    accounts = _accounts()

    monkeypatch.setattr(
        auth_api,
        "enabled_gate_accounts",
        lambda: accounts,
    )

    monkeypatch.setattr(
        auth_api,
        "enabled_bot_control_accounts",
        lambda: accounts,
    )

    allowed = {
        "arnold",
        "eqtydao",
        "zolnode",
    }

    settings = SimpleNamespace(
        bot_control_live_armed=True,
        bot_control_live_account_allowed=(
            lambda account_id:
                account_id in allowed
        ),
    )

    monkeypatch.setattr(
        auth_api,
        "get_settings",
        lambda: settings,
    )

    result = auth_api.capabilities(
        _user()
    )

    by_id = {
        item["account_id"]: item
        for item in result["accounts"]
    }

    assert (
        by_id["arnold"]["bot_control_live"]
        is True
    )

    assert (
        by_id["eqtydao"]["bot_control_live"]
        is True
    )

    assert (
        by_id["reserves"]["bot_control"]
        is True
    )

    assert (
        by_id["reserves"]["bot_control_live"]
        is False
    )

    assert (
        by_id["zolnode"]["bot_control_live"]
        is True
    )

    for item in result["accounts"]:
        assert (
            "bot_control_live_accounts"
            not in item
        )


def test_account_live_boolean_fails_closed_when_arm_off(
    monkeypatch,
):
    accounts = _accounts()

    monkeypatch.setattr(
        auth_api,
        "enabled_gate_accounts",
        lambda: accounts,
    )

    monkeypatch.setattr(
        auth_api,
        "enabled_bot_control_accounts",
        lambda: accounts,
    )

    settings = SimpleNamespace(
        bot_control_live_armed=False,
        bot_control_live_account_allowed=(
            lambda account_id: True
        ),
    )

    monkeypatch.setattr(
        auth_api,
        "get_settings",
        lambda: settings,
    )

    result = auth_api.capabilities(
        _user()
    )

    assert all(
        item["bot_control_live"] is False
        for item in result["accounts"]
    )


def test_create_ui_uses_account_specific_live_policy():
    app = Path(
        "frontend/app.js"
    ).read_text(encoding="utf-8")

    assert (
        "function botControlAccountLiveEnabled("
        in app
    )

    assert (
        "?.bot_control_live"
        in app
    )

    assert (
        "function "
        "botCreationSubmissionAvailableForAccount("
        in app
    )

    assert (
        "'LIVE creation not enabled '"
        in app
    )

    assert (
        "+ 'for this account'"
        in app
    )

    assert (
        "renderBotControlCreateState();"
        in app
    )

    assert (
        "state.botControlCapabilities = await adminApi("
        in app
    )

    assert (
        "'/api/auth/capabilities'"
        in app
    )


def test_review_remains_available_but_final_mutation_is_gated():
    app = Path(
        "frontend/app.js"
    ).read_text(encoding="utf-8")

    assert (
        "$('#openSpotGridConfirmation').disabled = ("
        in app
    )

    assert (
        "!botCreationSubmissionAvailableForAccount("
        in app
    )

    submit_start = app.index(
        "async function submitSpotGridCreate()"
    )

    create_post = app.index(
        "'/api/bot-control/spot-grid/create'",
        submit_start,
    )

    account_gate = app.index(
        "botCreationSubmissionAvailableForAccount(",
        submit_start,
    )

    assert account_gate < create_post


def test_app_js_cache_buster_updated():
    html = Path(
        "frontend/index.html"
    ).read_text(encoding="utf-8")

    assert (
        './app.js?v=20260822-bot-live-account-v1'
        in html
    )


def test_stop_ui_uses_account_specific_live_policy():
    app = Path(
        "frontend/app.js"
    ).read_text(encoding="utf-8")

    assert (
        "function "
        "botStopSubmissionAvailableForAccount("
        in app
    )

    assert (
        "'LIVE Bot Stop is not enabled for this '"
        in app
    )

    assert (
        "'LIVE Bot Stop is not enabled '"
        in app
    )

    assert (
        "botStopSubmissionAvailableForAccount("
        in app
    )


def test_stop_button_and_confirmation_are_account_gated():
    app = Path(
        "frontend/app.js"
    ).read_text(encoding="utf-8")

    controls_start = app.index(
        "function updateBotAdminControls(bot)"
    )

    controls_end = app.index(
        "\nasync function ",
        controls_start,
    )

    controls = app[
        controls_start:controls_end
    ]

    assert (
        "botStopSubmissionAvailableForAccount("
        in controls
    )

    confirmation_start = app.index(
        "function updateBotStopConfirmButton()"
    )

    confirmation_end = app.index(
        "\nasync function submitBotStop()",
        confirmation_start,
    )

    confirmation = app[
        confirmation_start:confirmation_end
    ]

    assert (
        "botStopSubmissionAvailableForAccount("
        in confirmation
    )


def test_stop_submit_refreshes_account_policy_before_post():
    app = Path(
        "frontend/app.js"
    ).read_text(encoding="utf-8")

    submit_start = app.index(
        "async function submitBotStop()"
    )

    stop_post = app.index(
        "/stop`",
        submit_start,
    )

    capability_refresh = app.index(
        "'/api/auth/capabilities'",
        submit_start,
    )

    account_gate = app.index(
        "botStopSubmissionAvailableForAccount(",
        submit_start,
    )

    assert account_gate < capability_refresh
    assert capability_refresh < stop_post


def test_create_and_stop_share_same_account_live_capability():
    app = Path(
        "frontend/app.js"
    ).read_text(encoding="utf-8")

    assert (
        "function botControlAccountLiveEnabled("
        in app
    )

    create_helper = app[
        app.index(
            "function "
            "botCreationSubmissionAvailableForAccount("
        ):
        app.index(
            "function "
            "botStopSubmissionAvailableForAccount("
        )
    ]

    stop_helper_start = app.index(
        "function "
        "botStopSubmissionAvailableForAccount("
    )

    stop_helper_end = app.index(
        "function renderBotControlCreateState(",
        stop_helper_start,
    )

    stop_helper = app[
        stop_helper_start:stop_helper_end
    ]

    assert (
        "botControlAccountLiveEnabled("
        in create_helper
    )

    assert (
        "botControlAccountLiveEnabled("
        in stop_helper
    )
