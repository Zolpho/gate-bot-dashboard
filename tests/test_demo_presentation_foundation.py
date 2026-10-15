from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import (
    Settings,
    get_settings,
)
from app.main import app


ROOT = Path(__file__).resolve().parents[1]

APP_JS = (
    ROOT
    / "frontend"
    / "app.js"
).read_text(
    encoding="utf-8"
)

INDEX_HTML = (
    ROOT
    / "frontend"
    / "index.html"
).read_text(
    encoding="utf-8"
)


class _Client:
    def __init__(
        self,
        settings: Settings,
    ) -> None:
        self.settings = settings
        self.client: TestClient | None = None

    def __enter__(
        self,
    ) -> TestClient:
        app.dependency_overrides[
            get_settings
        ] = lambda: self.settings

        self.client = TestClient(
            app
        )

        return self.client

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ) -> None:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )

        if self.client is not None:
            self.client.close()


def test_demo_status_default_off_and_read_only(
    tmp_path,
):
    demo_db = (
        tmp_path
        / "demo"
        / "demo.db"
    )

    settings = Settings(
        _env_file=None,
        dashboard_demo_login_enabled=False,
        dashboard_demo_database_path=demo_db,
    )

    with _Client(settings) as client:
        response = client.get(
            "/api/auth/demo-status"
        )

    assert response.status_code == 200

    assert response.json() == {
        "enabled": False,
        "execution_mode": "demo",
        "gate_write_performed": False,
    }

    assert demo_db.exists() is False


def test_demo_status_reflects_explicit_enablement_without_session_write(
    tmp_path,
):
    demo_db = (
        tmp_path
        / "demo"
        / "demo.db"
    )

    settings = Settings(
        _env_file=None,
        dashboard_demo_login_enabled=True,
        dashboard_demo_database_path=demo_db,
    )

    with _Client(settings) as client:
        response = client.get(
            "/api/auth/demo-status"
        )

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert (
        response.json()[
            "gate_write_performed"
        ]
        is False
    )

    # Availability lookup alone must not create Demo persistence.
    assert demo_db.exists() is False


def test_frontend_has_hidden_demo_login_discovery_flow():
    assert 'id="demoLoginButton"' in INDEX_HTML
    assert ">Demo login</button>" in INDEX_HTML

    assert (
        "/api/auth/demo-status"
        in APP_JS
    )

    assert (
        "/api/auth/login/demo"
        in APP_JS
    )

    assert (
        "demoAvailable: false"
        in APP_JS
    )


def test_frontend_preserves_demo_execution_mode():
    assert (
        "value.execution_mode || 'live'"
        in APP_JS
    )

    assert (
        "execution_mode: executionMode"
        in APP_JS
    )

    assert (
        "function isDemoSession()"
        in APP_JS
    )


def test_demo_navigation_is_contained_to_overview_and_bots():
    switch_start = APP_JS.index(
        "function switchTab("
    )

    titles_start = APP_JS.index(
        "  const titles = {",
        switch_start,
    )

    guard = APP_JS[
        switch_start:
        titles_start
    ]

    assert (
        "isDemoSession()"
        in guard
    )

    assert "'overview'" in guard
    assert "'bots'" in guard

    assert (
        "tab = 'overview';"
        in guard
    )

    presentation_start = (
        APP_JS.index(
            "function renderDemoPresentation()"
        )
    )

    availability_start = (
        APP_JS.index(
            "async function loadDemoAvailability()",
            presentation_start,
        )
    )

    presentation = APP_JS[
        presentation_start:
        availability_start
    ]

    for tab in (
        "overview",
        "bots",
    ):
        assert f"'{tab}'" in presentation

    assert (
        "syncButton"
        in presentation
    )

    assert (
        "globalAccountSelector"
        in presentation
    )

    assert (
        "accountPermissionsButton"
        in presentation
    )


def test_demo_identity_never_manages_real_wallet_accounts():
    start = APP_JS.index(
        "function canManageAccount("
    )

    end = APP_JS.index(
        "function canManageRule(",
        start,
    )

    function = APP_JS[
        start:end
    ]

    assert (
        "user.execution_mode === 'demo'"
        in function
    )

    assert (
        "return false;"
        in function
    )


def test_demo_restore_skips_private_bot_control_initialization():
    start = APP_JS.index(
        "async function restorePersistedAdminSession()"
    )

    end = APP_JS.index(
        "function setAdminError(",
        start,
    )

    function = APP_JS[
        start:end
    ]

    private_call = function.index(
        "await loadBotControlCapabilities();"
    )

    guard = function.rfind(
        "if (!isDemoSession())",
        0,
        private_call,
    )

    assert guard >= 0


def test_demo_native_activity_is_blocked_before_upstream_request():
    start = APP_JS.index(
        "async function loadBotNativeActivity("
    )

    guard = APP_JS.index(
        "if (isDemoSession())",
        start,
    )

    live_request = APP_JS.index(
        "/native-activity",
        start,
    )

    assert guard < live_request

    prefix = APP_JS[
        guard:
        live_request
    ]

    assert (
        "return;"
        in prefix
    )

    assert (
        "Live Gate-native Trades are not enabled in Demo yet."
        in prefix
    )


def test_demo_has_persistent_no_real_funds_indicator():
    marker = (
        "DEMO MODE · simulated actions · no real funds"
    )

    assert APP_JS.count(
        marker
    ) >= 2


def test_demo_shell_has_new_app_cache_marker():
    assert (
        "m424e2=20261015-demo-presentation-shell-v1"
        in INDEX_HTML
    )
