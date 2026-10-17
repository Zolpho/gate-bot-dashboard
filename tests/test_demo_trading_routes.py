from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

import app.api.trading as trading_api
from app.config import (
    Settings,
    get_settings as config_get_settings,
)
from app.demo_auth import (
    DemoSessionStore,
    demo_request_is_allowed,
)
from app.demo_wallet import DemoWalletStore
from app.main import app


SAFE_ROUTE_FUNCTIONS = {
    "trading_catalog",
    "trading_snapshot",
    "preview_limit_order",
    "trading_execution_capabilities",
    "execute_trading_limit_order",
    "get_trading_limit_order_request",
    "cancel_trading_limit_order",
    "amend_trading_limit_order",
    "trading_recent_orders",
    "trading_open_orders",
    "trading_trades",
    "trading_candles",
}


BLOCKED_RECONCILE_FUNCTIONS = {
    "reconcile_trading_limit_order_request",
    "reconcile_trading_limit_order_cancellation",
    "reconcile_trading_limit_order_amendment",
}


def _is_demo_guard(
    node: ast.expr,
) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) == 3
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "user"
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "is_demo"
        and isinstance(node.args[2], ast.Constant)
        and node.args[2].value is False
        and not node.keywords
    )


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
        self.original_direct_get_settings = None

    def __enter__(
        self,
    ) -> TestClient:
        app.dependency_overrides[
            config_get_settings
        ] = lambda: self.settings

        # Two admitted read routes did not historically depend on
        # Settings. Their Demo branch resolves the isolated Demo DB
        # through the imported get_settings function directly.
        self.original_direct_get_settings = (
            trading_api.get_settings
        )

        trading_api.get_settings = (
            lambda: self.settings
        )

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
            config_get_settings,
            None,
        )

        if (
            self.original_direct_get_settings
            is not None
        ):
            trading_api.get_settings = (
                self.original_direct_get_settings
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
            "Bearer "
            + response.json()[
                "access_token"
            ]
    }


def _single_account_headers(
    settings: Settings,
    account_id: str,
) -> dict[str, str]:
    token, _session = DemoSessionStore(
        settings.dashboard_demo_database_path
    ).create_session(
        account_ids=(
            account_id,
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
            "production Trading path reached: "
            + name
        )

    return fail


def _forbid_live_trading_paths(
    monkeypatch,
) -> None:
    names = (
        "GateClient",
        "load_gate_accounts",
        "get_gate_account",
        "get_trading_account",
        "_monitor_account_or_http",
        "_explicit_trading_account",
        "_trading_request_for_user",
        "execute_limit_order",
        "cancel_limit_order",
        "amend_limit_order_price",
        "get_order_request",
        "list_order_requests",
        "list_order_requests_for_market",
        "find_order_requests_by_gate_identity",
        "get_order_cancellation",
        "get_active_order_amendment",
        "list_order_amendments",
        "list_order_amendments_for_requests",
        "get_trading_lock_for_request",
        "list_order_reconciliations",
    )

    for name in names:
        monkeypatch.setattr(
            trading_api,
            name,
            _forbidden(
                name
            ),
        )


def _execute_body(
    request_id: str,
    *,
    account_id: str = "demo-wallet-1",
    price: str = "0.0042",
):
    return {
        "request_id":
            request_id,
        "account_id":
            account_id,
        "pair":
            "EQTY_USDT",
        "side":
            "buy",
        "price":
            price,
        "amount":
            "100000",
        "time_in_force":
            "gtc",
        "confirmation":
            "SIMULATE DEMO LIMIT ORDER",
    }


def _usdt(
    settings: Settings,
    account_id: str = "demo-wallet-1",
):
    state = DemoWalletStore(
        settings.dashboard_demo_database_path
    ).get_balance_state(
        account_id
    )

    return next(
        item
        for item in state["assets"]
        if item["currency"]
        == "USDT"
    )


def test_demo_trading_allowlist_is_exactly_method_bounded():
    allowed = (
        ("GET", "/api/trading/catalog"),
        ("GET", "/api/trading/snapshot"),
        (
            "GET",
            "/api/trading/execution-capabilities",
        ),
        (
            "POST",
            "/api/trading/limit-orders/preview",
        ),
        (
            "POST",
            "/api/trading/limit-orders/execute",
        ),
        (
            "GET",
            (
                "/api/trading/limit-orders/requests/"
                "demo-route-order-001"
            ),
        ),
        (
            "POST",
            (
                "/api/trading/limit-orders/requests/"
                "demo-route-order-001/cancel"
            ),
        ),
        (
            "POST",
            (
                "/api/trading/limit-orders/requests/"
                "demo-route-order-001/amend"
            ),
        ),
        ("GET", "/api/trading/orders/open"),
        ("GET", "/api/trading/orders/recent"),
        ("GET", "/api/trading/trades"),
        ("GET", "/api/trading/candles"),
    )

    for method, route in allowed:
        assert demo_request_is_allowed(
            method,
            route,
        )

    blocked = (
        (
            "POST",
            (
                "/api/trading/limit-orders/requests/"
                "demo-route-order-001/reconcile"
            ),
        ),
        (
            "POST",
            (
                "/api/trading/limit-orders/requests/"
                "demo-route-order-001/cancel/reconcile"
            ),
        ),
        (
            "POST",
            (
                "/api/trading/limit-orders/requests/"
                "demo-route-order-001/amendments/"
                "demo-amend-001/reconcile"
            ),
        ),
        ("POST", "/api/trading/catalog"),
        ("DELETE", "/api/trading/orders/open"),
        (
            "GET",
            (
                "/api/trading/limit-orders/requests/"
                "short"
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


def test_all_twelve_demo_routes_branch_first_and_reconciliation_does_not():
    source = Path(
        trading_api.__file__
    ).read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    functions = {
        node.name: node
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    }

    assert (
        SAFE_ROUTE_FUNCTIONS
        <= set(functions)
    )

    assert (
        BLOCKED_RECONCILE_FUNCTIONS
        <= set(functions)
    )

    def executable_body(node):
        body = list(
            node.body
        )

        if (
            body
            and isinstance(
                body[0],
                ast.Expr,
            )
            and isinstance(
                body[0].value,
                ast.Constant,
            )
            and isinstance(
                body[0].value.value,
                str,
            )
        ):
            body = body[1:]

        return body

    for name in SAFE_ROUTE_FUNCTIONS:
        body = executable_body(
            functions[name]
        )

        assert body, name

        first = body[0]

        assert isinstance(
            first,
            ast.If,
        ), name

        assert _is_demo_guard(
            first.test
        ), name

        assert (
            "_demo_trading_result"
            in ast.unparse(
                first
            )
        ), name

    for name in BLOCKED_RECONCILE_FUNCTIONS:
        body = executable_body(
            functions[name]
        )

        assert body, name

        first = body[0]

        assert not (
            isinstance(
                first,
                ast.If,
            )
            and _is_demo_guard(
                first.test
            )
        ), name


def test_demo_market_read_routes_never_reach_gate_or_production_helpers(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_trading_paths(
        monkeypatch
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        responses = (
            client.get(
                "/api/trading/catalog",
                headers=headers,
            ),
            client.get(
                "/api/trading/snapshot",
                params={
                    "account_id":
                        "demo-wallet-1",
                    "pair":
                        "EQTY_USDT",
                    "depth":
                        20,
                    "book_interval":
                        "0",
                },
                headers=headers,
            ),
            client.get(
                "/api/trading/candles",
                params={
                    "account_id":
                        "demo-wallet-1",
                    "pair":
                        "EQTY_USDT",
                    "interval":
                        "1h",
                    "limit":
                        50,
                },
                headers=headers,
            ),
            client.get(
                "/api/trading/trades",
                params={
                    "account_id":
                        "demo-wallet-1",
                    "pair":
                        "EQTY_USDT",
                    "limit":
                        10,
                },
                headers=headers,
            ),
            client.get(
                "/api/trading/execution-capabilities",
                headers=headers,
            ),
            client.get(
                "/api/trading/orders/open",
                params={
                    "account_id":
                        "demo-wallet-1",
                    "limit":
                        50,
                },
                headers=headers,
            ),
            client.get(
                "/api/trading/orders/recent",
                params={
                    "account_id":
                        "demo-wallet-1",
                    "limit":
                        50,
                },
                headers=headers,
            ),
        )

    for response in responses:
        assert (
            response.status_code
            == 200
        )

        payload = response.json()

        assert (
            payload["source"]
            == "demo"
        )

        assert (
            payload[
                "gate_read_performed"
            ]
            is False
        )

        assert (
            payload[
                "gate_write_performed"
            ]
            is False
        )


def test_demo_preview_and_execute_never_reach_live_execution(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_trading_paths(
        monkeypatch
    )

    request_id = (
        "demo-route-execute-001"
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        preview = client.post(
            "/api/trading/limit-orders/preview",
            json={
                "account_id":
                    "demo-wallet-1",
                "pair":
                    "EQTY_USDT",
                "side":
                    "buy",
                "price":
                    "0.0042",
                "amount":
                    "100000",
                "time_in_force":
                    "gtc",
            },
            headers=headers,
        )

        execute = client.post(
            "/api/trading/limit-orders/execute",
            json=_execute_body(
                request_id
            ),
            headers=headers,
        )

    assert preview.status_code == 200

    preview_payload = (
        preview.json()
    )

    assert (
        preview_payload["source"]
        == "demo"
    )

    assert (
        preview_payload[
            "can_execute"
        ]
        is True
    )

    assert (
        preview_payload[
            "gate_write_required"
        ]
        is False
    )

    assert execute.status_code == 200

    payload = execute.json()

    assert payload["source"] == "demo"

    assert (
        payload[
            "gate_write_performed"
        ]
        is False
    )

    assert (
        payload[
            "balance_reservation_performed"
        ]
        is True
    )

    balance = _usdt(
        settings
    )

    assert (
        balance["available"]
        == "12080"
    )

    assert (
        balance["locked"]
        == "670"
    )


def test_demo_detail_open_and_recent_read_only_isolated_audit(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_trading_paths(
        monkeypatch
    )

    request_id = (
        "demo-route-readmodel-001"
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        created = client.post(
            "/api/trading/limit-orders/execute",
            json=_execute_body(
                request_id
            ),
            headers=headers,
        )

        assert (
            created.status_code
            == 200
        )

        detail = client.get(
            (
                "/api/trading/limit-orders/requests/"
                + request_id
            ),
            headers=headers,
        )

        opened = client.get(
            "/api/trading/orders/open",
            params={
                "account_id":
                    "demo-wallet-1",
            },
            headers=headers,
        )

        recent = client.get(
            "/api/trading/orders/recent",
            params={
                "account_id":
                    "demo-wallet-1",
            },
            headers=headers,
        )

    assert detail.status_code == 200
    assert opened.status_code == 200
    assert recent.status_code == 200

    detail_payload = (
        detail.json()
    )

    assert (
        detail_payload[
            "request"
        ][
            "request_id"
        ]
        == request_id
    )

    assert (
        detail_payload[
            "reconciliations"
        ]
        == []
    )

    assert (
        detail_payload["lock"]
        is None
    )

    assert opened.json()["count"] == 1
    assert recent.json()["count"] == 1

    for response in (
        detail,
        opened,
        recent,
    ):
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


def test_demo_price_amend_isolated_and_never_calls_live_amend(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_trading_paths(
        monkeypatch
    )

    request_id = (
        "demo-route-amend-001"
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        created = client.post(
            "/api/trading/limit-orders/execute",
            json=_execute_body(
                request_id
            ),
            headers=headers,
        )

        assert created.status_code == 200

        amended = client.post(
            (
                "/api/trading/limit-orders/requests/"
                + request_id
                + "/amend"
            ),
            json={
                "amend_request_id":
                    "demo-route-amend-token-001",
                "requested_price":
                    "0.005",
                "confirmation":
                    (
                        "AMEND DEMO LIMIT ORDER "
                        + request_id
                        + " PRICE 0.005"
                    ),
            },
            headers=headers,
        )

    assert amended.status_code == 200

    payload = amended.json()

    assert payload["source"] == "demo"

    assert (
        payload[
            "gate_write_performed"
        ]
        is False
    )

    assert (
        payload[
            "amendment"
        ][
            "reservation_delta"
        ]
        == "80"
    )

    balance = _usdt(
        settings
    )

    assert (
        balance["available"]
        == "12000"
    )

    assert (
        balance["locked"]
        == "750"
    )


def test_demo_cancel_isolated_and_releases_reservation_once(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_trading_paths(
        monkeypatch
    )

    request_id = (
        "demo-route-cancel-001"
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        created = client.post(
            "/api/trading/limit-orders/execute",
            json=_execute_body(
                request_id
            ),
            headers=headers,
        )

        assert created.status_code == 200

        cancel_url = (
            "/api/trading/limit-orders/requests/"
            + request_id
            + "/cancel"
        )

        body = {
            "cancel_request_id":
                "demo-route-cancel-token-001",
            "confirmation":
                (
                    "CANCEL DEMO LIMIT ORDER "
                    + request_id
                ),
        }

        first = client.post(
            cancel_url,
            json=body,
            headers=headers,
        )

        replay = client.post(
            cancel_url,
            json={
                **body,
                "confirmation":
                    "STALE CONFIRMATION",
            },
            headers=headers,
        )

    assert first.status_code == 200
    assert replay.status_code == 200

    first_payload = first.json()
    replay_payload = replay.json()

    assert (
        first_payload[
            "balance_release_performed"
        ]
        is True
    )

    assert (
        replay_payload[
            "idempotent_replay"
        ]
        is True
    )

    assert (
        replay_payload[
            "balance_release_performed"
        ]
        is False
    )

    balance = _usdt(
        settings
    )

    assert (
        balance["available"]
        == "12500"
    )

    assert (
        balance["locked"]
        == "250"
    )


def test_all_three_demo_reconciliation_paths_are_rejected_before_handlers(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    for name in (
        "reconcile_spot_order_request",
        "reconcile_limit_order_cancellation",
        "reconcile_limit_order_amendment",
    ):
        monkeypatch.setattr(
            trading_api,
            name,
            _forbidden(
                name
            ),
        )

    request_id = (
        "demo-route-reconcile-001"
    )

    with _Client(settings) as client:
        headers = _login(
            client
        )

        responses = (
            client.post(
                (
                    "/api/trading/limit-orders/requests/"
                    + request_id
                    + "/reconcile"
                ),
                headers=headers,
            ),
            client.post(
                (
                    "/api/trading/limit-orders/requests/"
                    + request_id
                    + "/cancel/reconcile"
                ),
                headers=headers,
            ),
            client.post(
                (
                    "/api/trading/limit-orders/requests/"
                    + request_id
                    + "/amendments/"
                    + "demo-amend-reconcile-001"
                    + "/reconcile"
                ),
                headers=headers,
            ),
        )

    for response in responses:
        assert (
            response.status_code
            == 403
        )

        assert response.json() == {
            "detail": (
                "Demo session is not authorized "
                "for this endpoint"
            )
        }


def test_demo_trading_account_scope_fails_closed(
    tmp_path,
    monkeypatch,
):
    settings = _settings(
        tmp_path
    )

    _forbid_live_trading_paths(
        monkeypatch
    )

    with _Client(settings) as client:
        full_headers = _login(
            client
        )

        created = client.post(
            "/api/trading/limit-orders/execute",
            json=_execute_body(
                "demo-route-treasury-001",
                account_id=
                    "demo-wallet-2",
                price=
                    "0.0041",
            ),
            headers=full_headers,
        )

        assert created.status_code == 200

        growth_headers = (
            _single_account_headers(
                settings,
                "demo-wallet-1",
            )
        )

        preview = client.post(
            "/api/trading/limit-orders/preview",
            json={
                "account_id":
                    "demo-wallet-2",
                "pair":
                    "EQTY_USDT",
                "side":
                    "buy",
                "price":
                    "0.0041",
                "amount":
                    "100000",
                "time_in_force":
                    "gtc",
            },
            headers=growth_headers,
        )

        detail = client.get(
            (
                "/api/trading/limit-orders/requests/"
                "demo-route-treasury-001"
            ),
            headers=growth_headers,
        )

    assert preview.status_code == 403

    assert (
        preview.json()[
            "detail"
        ][
            "gate_write_performed"
        ]
        is False
    )

    # Inaccessible request IDs remain non-enumerable.
    assert detail.status_code == 404


def test_demo_route_module_has_no_demo_branch_on_reconciliation_functions():
    source = Path(
        trading_api.__file__
    ).read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    functions = {
        node.name: node
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    }

    for name in BLOCKED_RECONCILE_FUNCTIONS:
        node = functions[name]

        rendered = ast.unparse(
            node
        )

        assert (
            "_demo_trading_result"
            not in rendered
        ), name

        assert (
            "DemoTradingApi"
            not in rendered
        ), name
