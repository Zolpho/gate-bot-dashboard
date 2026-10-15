from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

import app.api.deposit as deposit_api
import app.api.deposit_history as deposit_history_api
import app.api.me as me_api
from app.config import (
    Settings,
    get_settings,
)
from app.demo_auth import (
    demo_request_is_allowed,
)
from app.main import app


def _settings(
    tmp_path: Path,
) -> Settings:
    return Settings(
        _env_file=None,
        dashboard_demo_login_enabled=True,
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


def _login(
    client: TestClient,
) -> dict[str, str]:
    response = client.post(
        "/api/auth/login/demo"
    )

    assert response.status_code == 200

    token = response.json()[
        "access_token"
    ]

    return {
        "Authorization":
            f"Bearer {token}"
    }


def _forbidden(
    name: str,
):
    def fail(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            f"production path reached: {name}"
        )

    return fail


def test_demo_request_allowlist_is_method_aware_and_read_only():
    allowed = (
        (
            "GET",
            "/api/auth/me",
        ),
        (
            "POST",
            "/api/auth/logout",
        ),
        (
            "GET",
            "/api/me/balance",
        ),
        (
            "GET",
            "/api/deposit/currencies",
        ),
        (
            "GET",
            "/api/me/deposit/USDT/networks",
        ),
        (
            "GET",
            "/api/me/deposit/USDT",
        ),
        (
            "GET",
            "/api/me/deposits",
        ),
        (
            "GET",
            "/api/me/deposits/900001",
        ),
    )

    for method, path in allowed:
        assert demo_request_is_allowed(
            method,
            path,
        )

    blocked = (
        (
            "POST",
            "/api/me/deposits/sync",
        ),
        (
            "POST",
            "/api/me/balance",
        ),
        (
            "GET",
            "/api/auth/sessions",
        ),
        (
            "GET",
            "/api/trading/catalog",
        ),
        (
            "POST",
            "/api/treasury/transfer",
        ),
    )

    for method, path in blocked:
        assert (
            demo_request_is_allowed(
                method,
                path,
            )
            is False
        )


def test_demo_balance_never_enters_production_db_or_gate(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    monkeypatch.setattr(
        me_api,
        "session_scope",
        _forbidden(
            "balance session_scope"
        ),
    )

    async def forbidden_live_balance(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "live balance transport reached"
        )

    monkeypatch.setattr(
        me_api,
        "_fetch_live_balance",
        forbidden_live_balance,
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        response = client.get(
            "/api/me/balance",
            params={
                "account_id":
                    "demo-wallet-1",
            },
            headers=headers,
        )

    assert response.status_code == 200

    payload = response.json()

    assert payload[
        "account_id"
    ] == "demo-wallet-1"

    assert payload[
        "source"
    ] == "demo"

    assert payload[
        "display_name"
    ] == "Demo Growth Wallet"

    assert payload[
        "cache"
    ] == {
        "hit": False,
        "ttl_seconds": 0,
    }

    assert payload[
        "authorized_user"
    ][
        "execution_mode"
    ] == "demo"


def test_demo_currency_catalog_never_calls_public_gate_transport(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    monkeypatch.setattr(
        deposit_api,
        "GateClient",
        _forbidden(
            "deposit catalog GateClient"
        ),
    )

    monkeypatch.setattr(
        deposit_api,
        "session_scope",
        _forbidden(
            "deposit session_scope"
        ),
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        response = client.get(
            "/api/deposit/currencies",
            headers=headers,
        )

    assert response.status_code == 200

    payload = response.json()

    assert payload[
        "source"
    ] == "demo"

    assert [
        item[
            "currency"
        ]
        for item
        in payload[
            "currencies"
        ]
    ] == [
        "USDT",
        "EQTY",
        "BTC",
        "ETH",
    ]


def test_demo_network_and_address_reads_never_touch_production_paths(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    monkeypatch.setattr(
        deposit_api,
        "session_scope",
        _forbidden(
            "deposit session_scope"
        ),
    )

    monkeypatch.setattr(
        deposit_api,
        "get_gate_account",
        _forbidden(
            "get_gate_account"
        ),
    )

    monkeypatch.setattr(
        deposit_api,
        "GateClient",
        _forbidden(
            "GateClient"
        ),
    )

    monkeypatch.setattr(
        deposit_api,
        "persist_deposit_address",
        _forbidden(
            "persist_deposit_address"
        ),
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        networks = client.get(
            "/api/me/deposit/USDT/networks",
            params={
                "account_id":
                    "demo-wallet-1",
            },
            headers=headers,
        )

        address = client.get(
            "/api/me/deposit/USDT",
            params={
                "account_id":
                    "demo-wallet-1",
                "chain":
                    "ETH",
            },
            headers=headers,
        )

    assert networks.status_code == 200

    assert [
        item[
            "chain"
        ]
        for item
        in networks.json()[
            "networks"
        ]
    ] == [
        "ETH",
        "TRX",
    ]

    assert address.status_code == 200

    payload = address.json()

    assert payload[
        "source"
    ] == "demo"

    assert payload[
        "network"
    ][
        "address"
    ].startswith(
        "DEMO-ONLY-"
    )

    assert payload[
        "authorized_user"
    ][
        "execution_mode"
    ] == "demo"


def test_demo_deposit_history_and_detail_never_read_production_models(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    monkeypatch.setattr(
        deposit_history_api,
        "session_scope",
        _forbidden(
            "deposit history session_scope"
        ),
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        listing = client.get(
            "/api/me/deposits",
            params={
                "account_id":
                    "demo-wallet-1",
            },
            headers=headers,
        )

        detail = client.get(
            "/api/me/deposits/900001",
            params={
                "account_id":
                    "demo-wallet-1",
            },
            headers=headers,
        )

    assert listing.status_code == 200

    list_payload = listing.json()

    assert list_payload[
        "total"
    ] == 3

    assert list_payload[
        "sync"
    ][
        "status"
    ] == "demo"

    assert all(
        item[
            "account_id"
        ]
        == "demo-wallet-1"
        for item
        in list_payload[
            "items"
        ]
    )

    assert detail.status_code == 200

    detail_payload = detail.json()

    assert detail_payload[
        "deposit"
    ][
        "id"
    ] == 900001

    assert detail_payload[
        "deposit"
    ][
        "raw"
    ][
        "demo"
    ] is True

    # Authentication and Wallet state must share the exact
    # request-configured isolated Demo SQLite database.
    demo_db = (
        settings
        .dashboard_demo_database_path
    )

    assert demo_db.exists()

    with sqlite3.connect(
        demo_db
    ) as db:
        tables = {
            row[0]
            for row
            in db.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }

        session_count = int(
            db.execute(
                """
                SELECT COUNT(*)
                FROM demo_sessions
                """
            ).fetchone()[0]
        )

    assert "demo_sessions" in tables
    assert "demo_wallet_accounts" in tables
    assert "demo_deposits" in tables
    assert session_count == 1


def test_demo_deposit_sync_is_blocked_before_gate_account_resolution(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    monkeypatch.setattr(
        deposit_history_api,
        "get_gate_account",
        _forbidden(
            "sync get_gate_account"
        ),
    )

    monkeypatch.setattr(
        deposit_history_api,
        "DepositHistoryService",
        _forbidden(
            "DepositHistoryService"
        ),
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        response = client.post(
            "/api/me/deposits/sync",
            params={
                "account_id":
                    "demo-wallet-1",
            },
            headers=headers,
        )

    assert response.status_code == 403

    assert response.json() == {
        "detail": (
            "Demo session is not authorized "
            "for this endpoint"
        )
    }
