from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app.api.treasury as treasury_api
from app.config import (
    Settings,
    get_settings,
)
from app.demo_auth import (
    DemoSessionStore,
    demo_request_is_allowed,
)
from app.demo_wallet import (
    DemoWalletStore,
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


def _headers(
    token: str,
) -> dict[str, str]:
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


def _asset(
    payload,
    currency: str,
):
    return next(
        item
        for item
        in payload[
            "assets"
        ]
        if item[
            "currency"
        ]
        == currency
    )


def _forbid_live_user_transfer_paths(
    monkeypatch,
) -> None:
    names = (
        "_registered_user_transfer_accounts",
        "_user_transfer_gate_account_or_http",
        "_gate_spot_available_balances",
        "build_user_gate_transfer",
        "find_matching_transfer_request",
        "_require_account_action_policy",
        "_enforce_treasury_rate_limit",
        "_treasury_account_or_http",
        "execute_user_account_transfer",
        "GateClient",
    )

    for name in names:
        monkeypatch.setattr(
            treasury_api,
            name,
            _forbidden(
                name
            ),
        )


def test_demo_treasury_allowlist_is_method_aware_and_bounded():
    allowed = (
        (
            "GET",
            "/api/treasury/ownership/balances",
        ),
        (
            "GET",
            "/api/treasury/ownership/ledger",
        ),
        (
            "GET",
            "/api/treasury/transfers/requests",
        ),
        (
            "GET",
            (
                "/api/treasury/transfers/requests/"
                "demo-seed-transfer-001"
            ),
        ),
        (
            "GET",
            "/api/treasury/user-transfers/participants",
        ),
        (
            "POST",
            "/api/treasury/user-transfers/preview",
        ),
        (
            "POST",
            "/api/treasury/user-transfers/execute",
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
            "/api/treasury/ownership/balances",
        ),
        (
            "POST",
            "/api/treasury/transfers/requests",
        ),
        (
            "GET",
            "/api/treasury/user-transfers/preview",
        ),
        (
            "POST",
            (
                "/api/treasury/user-transfers/"
                "demo-seed-transfer-001/reconcile"
            ),
        ),
        (
            "POST",
            (
                "/api/treasury/user-transfers/"
                "demo-seed-transfer-001/"
                "donation-attribution"
            ),
        ),
        (
            "POST",
            "/api/treasury/transfers/simulate",
        ),
        (
            "POST",
            "/api/treasury/transfers/execute",
        ),
        (
            "GET",
            "/api/treasury/transfers/locks",
        ),
        (
            "GET",
            "/api/treasury/status",
        ),
        (
            "GET",
            "/api/treasury/withdrawals/recipients",
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


def test_demo_ownership_routes_never_reach_live_treasury_repositories(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    monkeypatch.setattr(
        treasury_api,
        "ownership_balances",
        _forbidden(
            "production ownership_balances"
        ),
    )

    monkeypatch.setattr(
        treasury_api,
        "list_ownership_entries",
        _forbidden(
            "production list_ownership_entries"
        ),
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        balances = client.get(
            "/api/treasury/ownership/balances",
            headers=headers,
        )

        ledger = client.get(
            "/api/treasury/ownership/ledger",
            params={
                "limit":
                    2,
            },
            headers=headers,
        )

    assert balances.status_code == 200
    assert ledger.status_code == 200

    balance_payload = (
        balances.json()
    )

    ledger_payload = (
        ledger.json()
    )

    assert balance_payload[
        "source"
    ] == "demo"

    assert balance_payload[
        "gate_read_performed"
    ] is False

    assert balance_payload[
        "gate_write_performed"
    ] is False

    assert len(
        balance_payload[
            "items"
        ]
    ) == 3

    assert ledger_payload[
        "source"
    ] == "demo"

    assert len(
        ledger_payload[
            "items"
        ]
    ) == 2


def test_demo_transfer_request_routes_never_reach_live_audit_repository(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    for name in (
        "list_transfer_requests",
        "get_transfer_request",
        "list_transfer_reconciliations",
        "get_transfer_lock_for_request",
        "list_lock_resolutions",
    ):
        monkeypatch.setattr(
            treasury_api,
            name,
            _forbidden(
                name
            ),
        )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        listing = client.get(
            "/api/treasury/transfers/requests",
            headers=headers,
        )

        detail = client.get(
            (
                "/api/treasury/transfers/requests/"
                "demo-seed-transfer-001"
            ),
            headers=headers,
        )

    assert listing.status_code == 200
    assert detail.status_code == 200

    list_payload = listing.json()

    assert list_payload[
        "source"
    ] == "demo"

    assert len(
        list_payload[
            "items"
        ]
    ) == 2

    detail_payload = detail.json()

    assert detail_payload[
        "source"
    ] == "demo"

    assert detail_payload[
        "item"
    ][
        "request_id"
    ] == "demo-seed-transfer-001"

    assert detail_payload[
        "reconciliations"
    ] == []

    assert detail_payload[
        "operation_lock"
    ] is None

    assert detail_payload[
        "lock_resolutions"
    ] == []


def test_demo_transfer_participants_never_read_registered_users_or_gate(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    for name in (
        "_registered_user_transfer_accounts",
        "get_gate_account",
        "_gate_spot_available_balances",
        "GateClient",
    ):
        monkeypatch.setattr(
            treasury_api,
            name,
            _forbidden(
                name
            ),
        )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        response = client.get(
            (
                "/api/treasury/"
                "user-transfers/participants"
            ),
            headers=headers,
        )

    assert response.status_code == 200

    payload = response.json()

    assert payload[
        "source"
    ] == "demo"

    assert payload[
        "simulation"
    ] is True

    assert payload[
        "gate_read_performed"
    ] is False

    assert payload[
        "gate_write_performed"
    ] is False

    assert [
        item[
            "account_id"
        ]
        for item
        in payload[
            "items"
        ]
    ] == [
        "demo-wallet-1",
        "demo-wallet-2",
    ]


def test_demo_transfer_preview_never_reads_gate_or_live_helpers(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_user_transfer_paths(
        monkeypatch
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        response = client.post(
            (
                "/api/treasury/"
                "user-transfers/preview"
            ),
            json={
                "source_account_id":
                    "demo-wallet-1",
                "destination_account_id":
                    "demo-wallet-2",
                "currency":
                    "USDT",
                "amount":
                    "100",
                "donation":
                    False,
            },
            headers=headers,
        )

    assert response.status_code == 200

    payload = response.json()

    assert payload[
        "source"
    ] == "demo"

    assert payload[
        "status"
    ] == "ready"

    assert payload[
        "can_execute"
    ] is True

    assert payload[
        "gate_read_performed"
    ] is False

    assert payload[
        "gate_write_required"
    ] is False

    assert payload[
        "gate_write_performed"
    ] is False

    assert payload[
        "preview"
    ][
        "source_available_before"
    ] == "12500"

    assert payload[
        "preview"
    ][
        "source_available_after"
    ] == "12400"


def test_demo_transfer_execute_mutates_only_demo_store(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_user_transfer_paths(
        monkeypatch
    )

    store = DemoWalletStore(
        settings
        .dashboard_demo_database_path
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        preview = client.post(
            (
                "/api/treasury/"
                "user-transfers/preview"
            ),
            json={
                "source_account_id":
                    "demo-wallet-1",
                "destination_account_id":
                    "demo-wallet-2",
                "currency":
                    "USDT",
                "amount":
                    "100",
                "donation":
                    False,
            },
            headers=headers,
        )

        assert preview.status_code == 200

        ownership_before = (
            store.ownership_balances()
        )

        execute = client.post(
            (
                "/api/treasury/"
                "user-transfers/execute"
            ),
            json={
                "request_id":
                    "demo-route-transfer-001",
                "source_account_id":
                    "demo-wallet-1",
                "destination_account_id":
                    "demo-wallet-2",
                "currency":
                    "USDT",
                "amount":
                    "100",
                "donation":
                    False,
                "confirmation":
                    preview.json()[
                        "required_confirmation"
                    ],
            },
            headers=headers,
        )

    assert execute.status_code == 200

    payload = execute.json()

    assert payload[
        "source"
    ] == "demo"

    assert payload[
        "status"
    ] == "success"

    assert payload[
        "simulation"
    ] is True

    assert payload[
        "gate_read_performed"
    ] is False

    assert payload[
        "gate_write_required"
    ] is False

    assert payload[
        "gate_write_performed"
    ] is False

    growth = store.get_balance_state(
        "demo-wallet-1"
    )

    treasury = store.get_balance_state(
        "demo-wallet-2"
    )

    assert _asset(
        growth,
        "USDT",
    )[
        "available"
    ] == "12400"

    assert _asset(
        treasury,
        "USDT",
    )[
        "available"
    ] == "42100"

    assert (
        store.ownership_balances()
        == ownership_before
    )


def test_demo_transfer_execute_replay_is_idempotent_before_live_paths(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_user_transfer_paths(
        monkeypatch
    )

    store = DemoWalletStore(
        settings
        .dashboard_demo_database_path
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        preview = client.post(
            (
                "/api/treasury/"
                "user-transfers/preview"
            ),
            json={
                "source_account_id":
                    "demo-wallet-1",
                "destination_account_id":
                    "demo-wallet-2",
                "currency":
                    "ETH",
                "amount":
                    "0.1",
            },
            headers=headers,
        )

        assert preview.status_code == 200

        body = {
            "request_id":
                "demo-route-transfer-002",
            "source_account_id":
                "demo-wallet-1",
            "destination_account_id":
                "demo-wallet-2",
            "currency":
                "ETH",
            "amount":
                "0.1",
            "donation":
                False,
            "confirmation":
                preview.json()[
                    "required_confirmation"
                ],
        }

        first = client.post(
            (
                "/api/treasury/"
                "user-transfers/execute"
            ),
            json=body,
            headers=headers,
        )

        assert first.status_code == 200

        after_first = (
            store.get_balance_state(
                "demo-wallet-1"
            )
        )

        body[
            "confirmation"
        ] = (
            "STALE CONFIRMATION AFTER SUCCESS"
        )

        replay = client.post(
            (
                "/api/treasury/"
                "user-transfers/execute"
            ),
            json=body,
            headers=headers,
        )

    assert replay.status_code == 200

    assert replay.json()[
        "idempotent_replay"
    ] is True

    assert (
        store.get_balance_state(
            "demo-wallet-1"
        )
        == after_first
    )

    matching = [
        item
        for item
        in store.list_transfers()
        if item[
            "request_id"
        ]
        == "demo-route-transfer-002"
    ]

    assert len(
        matching
    ) == 1


def test_demo_transfer_bad_confirmation_and_blocked_amount_do_not_mutate(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_user_transfer_paths(
        monkeypatch
    )

    store = DemoWalletStore(
        settings
        .dashboard_demo_database_path
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        before = store.get_balance_state(
            "demo-wallet-1"
        )

        bad_confirmation = client.post(
            (
                "/api/treasury/"
                "user-transfers/execute"
            ),
            json={
                "request_id":
                    "demo-route-transfer-003",
                "source_account_id":
                    "demo-wallet-1",
                "destination_account_id":
                    "demo-wallet-2",
                "currency":
                    "USDT",
                "amount":
                    "1",
                "donation":
                    False,
                "confirmation":
                    "WRONG",
            },
            headers=headers,
        )

        blocked_preview = client.post(
            (
                "/api/treasury/"
                "user-transfers/preview"
            ),
            json={
                "source_account_id":
                    "demo-wallet-1",
                "destination_account_id":
                    "demo-wallet-2",
                "currency":
                    "USDT",
                "amount":
                    "999999",
            },
            headers=headers,
        )

        assert blocked_preview.status_code == 200

        blocked_execute = client.post(
            (
                "/api/treasury/"
                "user-transfers/execute"
            ),
            json={
                "request_id":
                    "demo-route-transfer-004",
                "source_account_id":
                    "demo-wallet-1",
                "destination_account_id":
                    "demo-wallet-2",
                "currency":
                    "USDT",
                "amount":
                    "999999",
                "donation":
                    False,
                "confirmation":
                    blocked_preview.json()[
                        "required_confirmation"
                    ],
            },
            headers=headers,
        )

    assert bad_confirmation.status_code == 400

    assert bad_confirmation.json()[
        "detail"
    ][
        "gate_write_performed"
    ] is False

    assert blocked_execute.status_code == 409

    assert blocked_execute.json()[
        "detail"
    ][
        "gate_write_performed"
    ] is False

    assert (
        store.get_balance_state(
            "demo-wallet-1"
        )
        == before
    )

    request_ids = {
        item[
            "request_id"
        ]
        for item
        in store.list_transfers()
    }

    assert (
        "demo-route-transfer-003"
        not in request_ids
    )

    assert (
        "demo-route-transfer-004"
        not in request_ids
    )


def test_demo_transfer_source_scope_fails_before_adapter(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    monkeypatch.setattr(
        treasury_api,
        "demo_user_transfer_preview_payload",
        _forbidden(
            "Demo adapter after unauthorized source"
        ),
    )

    token, _ = DemoSessionStore(
        settings
        .dashboard_demo_database_path
    ).create_session(
        account_ids=(
            "demo-wallet-1",
        ),
        ttl_seconds=900,
    )

    with _Client(settings) as client:
        response = client.post(
            (
                "/api/treasury/"
                "user-transfers/preview"
            ),
            json={
                "source_account_id":
                    "demo-wallet-2",
                "destination_account_id":
                    "demo-wallet-1",
                "currency":
                    "USDT",
                "amount":
                    "1",
            },
            headers=_headers(
                token
            ),
        )

    assert response.status_code == 403

    assert response.json() == {
        "detail": (
            "You are not allowed to transfer funds "
            "from this Demo Wallet account"
        )
    }
