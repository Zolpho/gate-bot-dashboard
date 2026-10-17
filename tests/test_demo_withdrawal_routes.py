from __future__ import annotations

import ast
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
from app.demo_wallet import DemoWalletStore
from app.main import app


SAFE_ROUTE_FUNCTIONS = {
    "treasury_withdrawal_recipients",
    "create_treasury_withdrawal_recipient",
    "treasury_withdrawal_recipient_detail",
    "rename_treasury_withdrawal_recipient",
    "archive_treasury_withdrawal_recipient",
    "restore_treasury_withdrawal_recipient",
    "create_treasury_withdrawal_recipient_destination",
    "treasury_withdrawal_destinations",
    "treasury_withdrawal_destination_detail",
    "treasury_withdrawal_capabilities",
    "treasury_withdrawal_preflight",
    "simulate_treasury_withdrawal_request",
    "treasury_withdrawal_requests",
    "treasury_withdrawal_request_detail",
    "treasury_withdrawal_locks",
    "reserve_treasury_withdrawal_request",
    "confirm_treasury_withdrawal_request",
    "prepare_treasury_withdrawal_jit",
    "execute_treasury_withdrawal_jit",
    "execute_treasury_external_withdrawal",
}


BLOCKED_ROUTE_FUNCTIONS = {
    "create_treasury_withdrawal_destination",
    "approve_treasury_withdrawal_destination",
    "revoke_treasury_withdrawal_destination",
    "reconcile_treasury_withdrawal_jit",
    "reconcile_treasury_external_withdrawal",
    "settle_treasury_withdrawal_request",
    "abandon_treasury_withdrawal_request",
    "hold_treasury_withdrawal_funds_on_main",
    "cancel_treasury_withdrawal_request",
}


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

    return {
        "Authorization":
            (
                "Bearer "
                + response.json()[
                    "access_token"
                ]
            )
    }


def _single_account_headers(
    settings: Settings,
) -> dict[str, str]:
    token, _session = DemoSessionStore(
        settings.dashboard_demo_database_path
    ).create_session(
        account_ids=(
            "demo-wallet-1",
        ),
        ttl_seconds=900,
    )

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
            "production withdrawal path reached: "
            + name
        )

    return fail


def _forbid_live_withdrawal_paths(
    monkeypatch,
) -> None:
    names = (
        "require_account_access",
        "_treasury_withdrawal_recipient_for_user",
        "_withdrawal_request_or_http",
        "_treasury_account_or_http",
        "get_gate_account",
        "ownership_amount",
        "build_withdrawal_capabilities",
        "build_withdrawal_preflight",
        "list_recipients",
        "create_recipient",
        "get_recipient",
        "rename_recipient",
        "archive_recipient",
        "restore_recipient",
        "create_candidate_destination_from_recipient",
        "list_destinations",
        "get_destination",
        "record_withdrawal_simulation",
        "find_matching_withdrawal_request",
        "list_withdrawal_requests",
        "get_withdrawal_request",
        "list_withdrawal_request_events",
        "list_withdrawal_reconciliations",
        "list_withdrawal_locks",
        "get_withdrawal_lock_for_request",
        "acquire_withdrawal_lock",
        "release_withdrawal_lock",
        "transition_withdrawal_request",
        "build_withdrawal_jit_plan",
        "execute_reserved_live_transfer",
        "submit_withdrawal_once",
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


def _usdt(
    store: DemoWalletStore,
):
    state = store.get_balance_state(
        "demo-wallet-1"
    )

    return next(
        item
        for item
        in state["assets"]
        if item["currency"]
        == "USDT"
    )


def test_demo_withdrawal_allowlist_is_exactly_method_bounded():
    allowed = (
        ("GET", "/api/treasury/withdrawals/recipients"),
        ("POST", "/api/treasury/withdrawals/recipients"),
        (
            "GET",
            "/api/treasury/withdrawals/recipients/demo-recipient-growth",
        ),
        (
            "PATCH",
            "/api/treasury/withdrawals/recipients/demo-recipient-growth",
        ),
        (
            "POST",
            "/api/treasury/withdrawals/recipients/demo-recipient-growth/archive",
        ),
        (
            "POST",
            "/api/treasury/withdrawals/recipients/demo-recipient-growth/restore",
        ),
        (
            "POST",
            "/api/treasury/withdrawals/recipients/demo-recipient-growth/destinations",
        ),
        ("GET", "/api/treasury/withdrawals/destinations"),
        (
            "GET",
            (
                "/api/treasury/withdrawals/destinations/"
                "demo-destination-growth-usdt-eth"
            ),
        ),
        (
            "GET",
            "/api/treasury/withdrawals/capabilities/USDT",
        ),
        (
            "GET",
            "/api/treasury/withdrawals/preflight/USDT",
        ),
        (
            "POST",
            "/api/treasury/withdrawals/requests/simulate",
        ),
        ("GET", "/api/treasury/withdrawals/requests"),
        (
            "GET",
            "/api/treasury/withdrawals/requests/demo-route-request-001",
        ),
        (
            "POST",
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-request-001/reserve"
            ),
        ),
        (
            "POST",
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-request-001/confirm"
            ),
        ),
        (
            "POST",
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-request-001/jit/prepare"
            ),
        ),
        (
            "POST",
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-request-001/jit/execute"
            ),
        ),
        (
            "POST",
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-request-001/execute"
            ),
        ),
        ("GET", "/api/treasury/withdrawals/locks"),
    )

    for method, route in allowed:
        assert demo_request_is_allowed(
            method,
            route,
        )

    blocked = (
        ("POST", "/api/treasury/withdrawals/destinations"),
        (
            "POST",
            (
                "/api/treasury/withdrawals/destinations/"
                "demo-destination-growth-usdt-eth/approve"
            ),
        ),
        (
            "POST",
            (
                "/api/treasury/withdrawals/destinations/"
                "demo-destination-growth-usdt-eth/revoke"
            ),
        ),
        (
            "POST",
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-request-001/jit/reconcile"
            ),
        ),
        (
            "POST",
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-request-001/reconcile"
            ),
        ),
        (
            "POST",
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-request-001/settle"
            ),
        ),
        (
            "POST",
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-request-001/abandon"
            ),
        ),
        (
            "POST",
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-request-001/hold-on-main"
            ),
        ),
        (
            "POST",
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-request-001/cancel"
            ),
        ),
    )

    for method, route in blocked:
        assert (
            demo_request_is_allowed(
                method,
                route,
            )
            is False
        )

    assert (
        demo_request_is_allowed(
            "DELETE",
            "/api/treasury/withdrawals/recipients/demo-recipient-growth",
        )
        is False
    )


def test_all_twenty_demo_routes_branch_first_and_blocked_routes_do_not():
    source = Path(
        treasury_api.__file__
    ).read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    functions = {
        node.name:
            node
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    }

    assert SAFE_ROUTE_FUNCTIONS <= set(
        functions
    )

    assert BLOCKED_ROUTE_FUNCTIONS <= set(
        functions
    )

    for name in SAFE_ROUTE_FUNCTIONS:
        node = functions[
            name
        ]

        args = {
            arg.arg
            for arg in (
                list(
                    node.args.posonlyargs
                )
                + list(
                    node.args.args
                )
                + list(
                    node.args.kwonlyargs
                )
            )
        }

        assert (
            "request_settings"
            in args
        ), name

        assert node.body

        first = node.body[
            0
        ]

        assert isinstance(
            first,
            ast.If,
        ), name

        assert (
            "user.is_demo"
            in ast.unparse(
                first.test
            )
        ), name

    for name in BLOCKED_ROUTE_FUNCTIONS:
        node = functions[
            name
        ]

        if not node.body:
            continue

        first = node.body[
            0
        ]

        assert not (
            isinstance(
                first,
                ast.If,
            )
            and "user.is_demo"
            in ast.unparse(
                first.test
            )
        ), name


def test_demo_withdrawal_read_routes_never_reach_live_helpers(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_withdrawal_paths(
        monkeypatch
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        responses = (
            client.get(
                "/api/treasury/withdrawals/recipients",
                headers=headers,
            ),
            client.get(
                (
                    "/api/treasury/withdrawals/recipients/"
                    "demo-recipient-growth"
                ),
                headers=headers,
            ),
            client.get(
                "/api/treasury/withdrawals/destinations",
                headers=headers,
            ),
            client.get(
                (
                    "/api/treasury/withdrawals/destinations/"
                    "demo-destination-growth-usdt-eth"
                ),
                headers=headers,
            ),
            client.get(
                "/api/treasury/withdrawals/capabilities/USDT",
                params={
                    "owner_account_id":
                        "demo-wallet-1",
                },
                headers=headers,
            ),
            client.get(
                "/api/treasury/withdrawals/preflight/USDT",
                params={
                    "owner_account_id":
                        "demo-wallet-1",
                    "destination_id":
                        "demo-destination-growth-usdt-eth",
                    "amount":
                        "50",
                },
                headers=headers,
            ),
            client.get(
                "/api/treasury/withdrawals/requests",
                headers=headers,
            ),
            client.get(
                "/api/treasury/withdrawals/locks",
                headers=headers,
            ),
        )

    for response in responses:
        assert (
            response.status_code
            == 200
        ), response.text

        payload = response.json()

        assert (
            payload["source"]
            == "demo"
        )

        assert (
            payload[
                "gate_write_performed"
            ]
            is False
        )


def test_demo_recipient_mutations_never_reach_live_repositories(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_withdrawal_paths(
        monkeypatch
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        created = client.post(
            "/api/treasury/withdrawals/recipients",
            json={
                "owner_account_id":
                    "demo-wallet-1",
                "address":
                    "DEMO-ROUTE-BTC-RECIPIENT",
                "label":
                    "Route recipient",
            },
            headers=headers,
        )

        assert created.status_code == 200

        recipient_id = (
            created.json()[
                "recipient"
            ][
                "recipient_id"
            ]
        )

        renamed = client.patch(
            (
                "/api/treasury/withdrawals/recipients/"
                + recipient_id
            ),
            json={
                "label":
                    "Renamed route recipient",
            },
            headers=headers,
        )

        archived = client.post(
            (
                "/api/treasury/withdrawals/recipients/"
                + recipient_id
                + "/archive"
            ),
            json={
                "reason":
                    "Demo route archive",
            },
            headers=headers,
        )

        restored = client.post(
            (
                "/api/treasury/withdrawals/recipients/"
                + recipient_id
                + "/restore"
            ),
            json={
                "reason":
                    "Demo route restore",
            },
            headers=headers,
        )

        destination = client.post(
            (
                "/api/treasury/withdrawals/recipients/"
                + recipient_id
                + "/destinations"
            ),
            json={
                "currency":
                    "BTC",
                "chain":
                    "BTC",
                "memo":
                    "",
            },
            headers=headers,
        )

    assert renamed.status_code == 200
    assert archived.status_code == 200
    assert restored.status_code == 200
    assert destination.status_code == 200

    assert (
        renamed.json()[
            "recipient"
        ][
            "label"
        ]
        == "Renamed route recipient"
    )

    assert (
        destination.json()[
            "destination"
        ][
            "verification_method"
        ]
        == "demo_auto_approved"
    )


def test_demo_http_lifecycle_settles_and_replay_does_not_debit_twice(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_withdrawal_paths(
        monkeypatch
    )

    store = DemoWalletStore(
        settings.dashboard_demo_database_path
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        before = _usdt(
            store
        )

        simulated = client.post(
            "/api/treasury/withdrawals/requests/simulate",
            json={
                "request_id":
                    "demo-route-life-001",
                "owner_account_id":
                    "demo-wallet-1",
                "destination_id":
                    "demo-destination-growth-usdt-eth",
                "currency":
                    "USDT",
                "amount":
                    "50",
            },
            headers=headers,
        )

        assert simulated.status_code == 200

        reserve = client.post(
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-life-001/reserve"
            ),
            json={
                "confirmation":
                    simulated.json()[
                        "required_confirmation"
                    ],
            },
            headers=headers,
        )

        assert reserve.status_code == 200

        confirm = client.post(
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-life-001/confirm"
            ),
            json={
                "confirmation":
                    reserve.json()[
                        "detail"
                    ][
                        "required_confirmation"
                    ],
            },
            headers=headers,
        )

        assert confirm.status_code == 200

        prepare = client.post(
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-life-001/jit/prepare"
            ),
            json={
                "confirmation":
                    confirm.json()[
                        "detail"
                    ][
                        "required_confirmation"
                    ],
            },
            headers=headers,
        )

        assert prepare.status_code == 200

        jit_ready = client.post(
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-life-001/jit/execute"
            ),
            json={
                "confirmation":
                    prepare.json()[
                        "detail"
                    ][
                        "required_confirmation"
                    ],
            },
            headers=headers,
        )

        assert jit_ready.status_code == 200

        settled = client.post(
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-life-001/execute"
            ),
            json={
                "confirmation":
                    jit_ready.json()[
                        "detail"
                    ][
                        "required_confirmation"
                    ],
            },
            headers=headers,
        )

        assert settled.status_code == 200

        after_first = _usdt(
            store
        )

        replay = client.post(
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-life-001/execute"
            ),
            json={
                "confirmation":
                    "STALE CONFIRMATION",
            },
            headers=headers,
        )

        assert replay.status_code == 200

        after_replay = _usdt(
            store
        )

        detail = client.get(
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-life-001"
            ),
            headers=headers,
        )

    assert before[
        "available"
    ] == "12500"

    assert after_first[
        "available"
    ] == "12450"

    assert (
        after_replay
        == after_first
    )

    assert (
        settled.json()[
            "status"
        ]
        == "withdrawal_settled"
    )

    assert (
        settled.json()[
            "gate_write_performed"
        ]
        is False
    )

    assert (
        replay.json()[
            "idempotent_replay"
        ]
        is True
    )

    assert detail.status_code == 200

    assert (
        detail.json()[
            "workflow"
        ][
            "terminal"
        ]
        is True
    )


def test_single_account_demo_session_cannot_cross_wallet_scope(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_withdrawal_paths(
        monkeypatch
    )

    with _Client(settings) as client:
        headers = _single_account_headers(
            settings
        )

        recipient = client.get(
            (
                "/api/treasury/withdrawals/recipients/"
                "demo-recipient-treasury"
            ),
            headers=headers,
        )

        destination = client.get(
            (
                "/api/treasury/withdrawals/destinations/"
                "demo-destination-treasury-usdt-trx"
            ),
            headers=headers,
        )

        simulation = client.post(
            "/api/treasury/withdrawals/requests/simulate",
            json={
                "request_id":
                    "demo-route-cross-wallet-001",
                "owner_account_id":
                    "demo-wallet-2",
                "destination_id":
                    "demo-destination-treasury-usdt-trx",
                "currency":
                    "USDT",
                "amount":
                    "100",
            },
            headers=headers,
        )

    assert recipient.status_code == 403
    assert destination.status_code == 403
    assert simulation.status_code == 403


def test_demo_operation_lock_conflict_is_409_without_live_path(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_withdrawal_paths(
        monkeypatch
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        first = client.post(
            "/api/treasury/withdrawals/requests/simulate",
            json={
                "request_id":
                    "demo-route-lock-001",
                "owner_account_id":
                    "demo-wallet-1",
                "destination_id":
                    "demo-destination-growth-usdt-eth",
                "currency":
                    "USDT",
                "amount":
                    "50",
            },
            headers=headers,
        )

        second = client.post(
            "/api/treasury/withdrawals/requests/simulate",
            json={
                "request_id":
                    "demo-route-lock-002",
                "owner_account_id":
                    "demo-wallet-1",
                "destination_id":
                    "demo-destination-growth-usdt-eth",
                "currency":
                    "USDT",
                "amount":
                    "51",
            },
            headers=headers,
        )

        assert first.status_code == 200
        assert second.status_code == 200

        first_reserve = client.post(
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-lock-001/reserve"
            ),
            json={
                "confirmation":
                    first.json()[
                        "required_confirmation"
                    ],
            },
            headers=headers,
        )

        assert first_reserve.status_code == 200

        second_reserve = client.post(
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-lock-002/reserve"
            ),
            json={
                "confirmation":
                    second.json()[
                        "required_confirmation"
                    ],
            },
            headers=headers,
        )

    assert second_reserve.status_code == 409

    assert (
        second_reserve.json()[
            "detail"
        ][
            "gate_write_performed"
        ]
        is False
    )


def test_production_only_withdrawal_route_is_rejected_before_handler(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    monkeypatch.setattr(
        treasury_api,
        "reconcile_withdrawal_service",
        _forbidden(
            "reconcile_withdrawal_service"
        ),
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        response = client.post(
            (
                "/api/treasury/withdrawals/requests/"
                "demo-route-blocked-001/reconcile"
            ),
            headers=headers,
        )

    assert response.status_code == 403
