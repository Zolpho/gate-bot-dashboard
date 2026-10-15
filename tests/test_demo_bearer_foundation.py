from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.auth as auth_api
import app.auth_login as auth_login
from app.config import (
    Settings,
    get_settings,
)
from app.demo_auth import (
    DEMO_ACCOUNT_IDS,
    DEMO_TOKEN_PREFIX,
    DemoSessionStore,
)
from app.main import app


def _settings(
    tmp_path: Path,
    *,
    enabled: bool,
) -> Settings:
    return Settings(
        _env_file=None,
        dashboard_demo_login_enabled=enabled,
        dashboard_demo_database_path=(
            tmp_path
            / "isolated-demo"
            / "demo.db"
        ),
        dashboard_demo_session_ttl_seconds=900,
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

        # Deliberately avoid TestClient as a context manager.
        # The focused route tests do not require application
        # startup/lifespan behavior.
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


def test_demo_login_is_disabled_by_default(
    tmp_path,
):
    settings = _settings(
        tmp_path,
        enabled=False,
    )

    with _Client(settings) as client:
        response = client.post(
            "/api/auth/login/demo"
        )

    assert response.status_code == 404
    assert (
        settings
        .dashboard_demo_database_path
        .exists()
        is False
    )


def test_enabled_demo_login_uses_isolated_session_store(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path,
        enabled=True,
    )

    def forbidden_live_login(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "production password login "
            "must not serve Demo"
        )

    monkeypatch.setattr(
        auth_api,
        "begin_password_login",
        forbidden_live_login,
    )

    with _Client(settings) as client:
        response = client.post(
            "/api/auth/login/demo"
        )

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "authenticated"
    assert payload["token_type"] == "bearer"
    assert payload["access_token"].startswith(
        DEMO_TOKEN_PREFIX
    )

    assert payload["user"] == {
        "username": "demo",
        "role": "account_operator",
        "account_ids": list(
            DEMO_ACCOUNT_IDS
        ),
        "enabled": True,
        "auth_source": "demo",
        "execution_mode": "demo",
    }

    assert payload["session"][
        "auth_method"
    ] == "demo"

    assert payload["session"][
        "execution_mode"
    ] == "demo"

    assert payload["mfa_required"] is False
    assert (
        payload["gate_write_performed"]
        is False
    )

    assert (
        settings
        .dashboard_demo_database_path
        .exists()
    )


def test_demo_bearer_resolves_me_without_live_auth_state(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path,
        enabled=True,
    )

    def forbidden_live_resolver(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "production Bearer resolver "
            "must not receive Demo token"
        )

    monkeypatch.setattr(
        auth_login,
        "resolve_bearer_session",
        forbidden_live_resolver,
    )

    with _Client(settings) as client:
        login = client.post(
            "/api/auth/login/demo"
        )

        assert login.status_code == 200

        token = login.json()[
            "access_token"
        ]

        response = client.get(
            "/api/auth/me",
            headers={
                "Authorization":
                    f"Bearer {token}",
            },
        )

    assert response.status_code == 200

    assert response.json() == {
        "user": {
            "username": "demo",
            "role": "account_operator",
            "account_ids": list(
                DEMO_ACCOUNT_IDS
            ),
            "enabled": True,
            "auth_source": "demo",
            "execution_mode": "demo",
        }
    }


def test_demo_token_fails_closed_outside_exact_auth_allowlist(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path,
        enabled=True,
    )

    def forbidden_session_listing(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "production session repository "
            "must not be reached by Demo"
        )

    monkeypatch.setattr(
        auth_api,
        "list_active_auth_sessions",
        forbidden_session_listing,
    )

    with _Client(settings) as client:
        login = client.post(
            "/api/auth/login/demo"
        )

        token = login.json()[
            "access_token"
        ]

        response = client.get(
            "/api/auth/sessions",
            headers={
                "Authorization":
                    f"Bearer {token}",
            },
        )

    assert response.status_code == 403

    assert response.json() == {
        "detail": (
            "Demo session is not authorized "
            "for this endpoint"
        )
    }


def test_disabling_demo_invalidates_existing_demo_token(
    tmp_path,
):
    enabled = _settings(
        tmp_path,
        enabled=True,
    )

    with _Client(enabled) as client:
        login = client.post(
            "/api/auth/login/demo"
        )

    token = login.json()[
        "access_token"
    ]

    disabled = Settings(
        _env_file=None,
        dashboard_demo_login_enabled=False,
        dashboard_demo_database_path=(
            enabled
            .dashboard_demo_database_path
        ),
        dashboard_demo_session_ttl_seconds=900,
    )

    with _Client(disabled) as client:
        response = client.get(
            "/api/auth/me",
            headers={
                "Authorization":
                    f"Bearer {token}",
            },
        )

    assert response.status_code == 401


def test_demo_logout_never_calls_production_session_revocation(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path,
        enabled=True,
    )

    def forbidden_live_revoke(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "production auth-session revocation "
            "must not receive Demo token"
        )

    monkeypatch.setattr(
        auth_api,
        "revoke_auth_session",
        forbidden_live_revoke,
    )

    with _Client(settings) as client:
        login = client.post(
            "/api/auth/login/demo"
        )

        token = login.json()[
            "access_token"
        ]

        logout = client.post(
            "/api/auth/logout",
            headers={
                "Authorization":
                    f"Bearer {token}",
            },
        )

        assert logout.status_code == 200
        assert logout.json()[
            "status"
        ] == "revoked"

        after = client.get(
            "/api/auth/me",
            headers={
                "Authorization":
                    f"Bearer {token}",
            },
        )

    assert after.status_code == 401


def test_demo_token_namespace_cannot_fall_through_when_store_missing(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path,
        enabled=True,
    )

    assert (
        settings
        .dashboard_demo_database_path
        .exists()
        is False
    )

    def forbidden_live_resolver(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "Demo token namespace must never "
            "fall through to live Bearer auth"
        )

    monkeypatch.setattr(
        auth_login,
        "resolve_bearer_session",
        forbidden_live_resolver,
    )

    missing_token = (
        DEMO_TOKEN_PREFIX
        + "does-not-exist"
    )

    with _Client(settings) as client:
        response = client.get(
            "/api/auth/me",
            headers={
                "Authorization":
                    f"Bearer {missing_token}",
            },
        )

    assert response.status_code == 401


def test_direct_demo_store_account_ids_remain_synthetic(
    tmp_path,
):
    path = tmp_path / "demo.db"

    token, _ = (
        DemoSessionStore(
            path
        ).create_session(
            account_ids=(
                DEMO_ACCOUNT_IDS
            ),
            ttl_seconds=900,
        )
    )

    resolved = (
        DemoSessionStore(
            path
        ).resolve_session(
            token
        )
    )

    assert resolved is not None
    assert resolved[
        "user"
    ].account_ids == (
        DEMO_ACCOUNT_IDS
    )

    assert all(
        item.startswith(
            "demo-wallet-"
        )
        for item
        in resolved[
            "user"
        ].account_ids
    )
