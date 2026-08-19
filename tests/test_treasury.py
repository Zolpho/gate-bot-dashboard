from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from app.accounts import GateAccountConfig
from app.main import app
from app.treasury import (
    TreasuryConfigError,
    _validate_treasury_accounts,
)


def account(
    account_id: str,
    *,
    api_key: str,
    uid: str,
    account_type: str = "main",
) -> GateAccountConfig:
    return GateAccountConfig(
        id=account_id,
        name=account_id,
        api_key=api_key,
        api_secret=f"{api_key}-secret",
        enabled=True,
        account_type=account_type,
        gate_uid=uid,
    )


def auth(
    username: str,
    password: str,
) -> dict[str, str]:
    token = base64.b64encode(
        f"{username}:{password}".encode()
    ).decode()

    return {
        "Authorization": f"Basic {token}"
    }


def valid_inputs():
    monitor = account(
        "zolnode",
        api_key="monitor-key",
        uid="13079163",
    )

    control = account(
        "zolnode",
        api_key="control-key",
        uid="13079163",
    )

    treasury = account(
        "zolnode",
        api_key="treasury-key",
        uid="13079163",
    )

    return treasury, monitor, control


def test_valid_separate_main_treasury_credential() -> None:
    treasury, monitor, control = valid_inputs()

    result = _validate_treasury_accounts(
        [treasury],
        [monitor],
        [control],
        main_account_id="zolnode",
    )

    assert result is treasury


def test_treasury_rejects_wrong_account_id() -> None:
    _, monitor, control = valid_inputs()

    treasury = account(
        "arnold",
        api_key="treasury-key",
        uid="58601346",
    )

    with pytest.raises(
        TreasuryConfigError,
        match="must belong to configured main account",
    ):
        _validate_treasury_accounts(
            [treasury],
            [monitor],
            [control],
            main_account_id="zolnode",
        )


def test_treasury_rejects_subaccount_type() -> None:
    treasury, monitor, control = valid_inputs()

    treasury = account(
        "zolnode",
        api_key="treasury-key",
        uid="13079163",
        account_type="subaccount",
    )

    with pytest.raises(
        TreasuryConfigError,
        match="account_type='main'",
    ):
        _validate_treasury_accounts(
            [treasury],
            [monitor],
            [control],
            main_account_id="zolnode",
        )


def test_treasury_rejects_uid_mismatch() -> None:
    treasury, monitor, control = valid_inputs()

    treasury = account(
        "zolnode",
        api_key="treasury-key",
        uid="99999999",
    )

    with pytest.raises(
        TreasuryConfigError,
        match="Gate UID mismatch",
    ):
        _validate_treasury_accounts(
            [treasury],
            [monitor],
            [control],
            main_account_id="zolnode",
        )


def test_treasury_rejects_monitor_key_reuse() -> None:
    _, monitor, control = valid_inputs()

    treasury = account(
        "zolnode",
        api_key="monitor-key",
        uid="13079163",
    )

    with pytest.raises(
        TreasuryConfigError,
        match="reuses a Monitor API key",
    ):
        _validate_treasury_accounts(
            [treasury],
            [monitor],
            [control],
            main_account_id="zolnode",
        )


def test_treasury_rejects_bot_control_key_reuse() -> None:
    _, monitor, control = valid_inputs()

    treasury = account(
        "zolnode",
        api_key="control-key",
        uid="13079163",
    )

    with pytest.raises(
        TreasuryConfigError,
        match="reuses a Bot Control API key",
    ):
        _validate_treasury_accounts(
            [treasury],
            [monitor],
            [control],
            main_account_id="zolnode",
        )


def test_treasury_rejects_multiple_enabled_credentials() -> None:
    treasury, monitor, control = valid_inputs()

    second = account(
        "treasury2",
        api_key="treasury-key-2",
        uid="13079163",
    )

    with pytest.raises(
        TreasuryConfigError,
        match="exactly one enabled",
    ):
        _validate_treasury_accounts(
            [treasury, second],
            [monitor],
            [control],
            main_account_id="zolnode",
        )


def test_treasury_status_is_safe_when_unconfigured() -> None:
    headers = auth(
        "zolnode",
        "zolnode-test-password",
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/treasury/status",
            headers=headers,
        )

        assert response.status_code == 200

        payload = response.json()

        assert payload["phase"] == "T2B_TRANSFER_CONTROL"
        assert payload["configured"] is False
        assert payload["main_account"] == "zolnode"
        assert payload["transfers_enabled"] is False
        assert payload["withdrawals_enabled"] is False
        assert payload["config_error"] == ""


def test_treasury_t2c3b_allows_only_expected_mutation_routes() -> None:
    write_routes = []

    for route in app.routes:
        path = getattr(route, "path", "")

        if not path.startswith(
            "/api/treasury"
        ):
            continue

        methods = set(
            getattr(route, "methods", set())
            or set()
        )

        mutation_methods = methods.intersection(
            {
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
            }
        )

        if mutation_methods:
            write_routes.append(
                (
                    path,
                    mutation_methods,
                )
            )

    actual = {
        (
            path,
            frozenset(methods),
        )
        for path, methods in write_routes
    }

    transfer_mutations = {
        (
            "/api/treasury/transfers/simulate",
            frozenset({"POST"}),
        ),
        (
            "/api/treasury/transfers/execute",
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/transfers/"
                "{request_id}/reconcile"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/transfers/"
                "{request_id}/lock/release"
            ),
            frozenset({"POST"}),
        ),
    }

    local_withdrawal_mutations = {
        (
            (
                "/api/treasury/withdrawals/"
                "destinations"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/withdrawals/"
                "destinations/"
                "{destination_id}/approve"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/withdrawals/"
                "destinations/"
                "{destination_id}/revoke"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/withdrawals/"
                "requests/simulate"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/withdrawals/"
                "requests/{request_id}/reserve"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/withdrawals/"
                "requests/{request_id}/confirm"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/withdrawals/"
                "requests/{request_id}/jit/prepare"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/withdrawals/"
                "requests/{request_id}/jit/execute"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/withdrawals/"
                "requests/{request_id}/jit/reconcile"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/withdrawals/"
                "requests/{request_id}/execute"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/withdrawals/"
                "requests/{request_id}/reconcile"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/withdrawals/"
                "requests/{request_id}/settle"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/withdrawals/"
                "requests/{request_id}/abandon"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/withdrawals/"
                "requests/{request_id}/hold-on-main"
            ),
            frozenset({"POST"}),
        ),
        (
            (
                "/api/treasury/withdrawals/"
                "requests/{request_id}/cancel"
            ),
            frozenset({"POST"}),
        ),
    }

    assert actual == (
        transfer_mutations
        | local_withdrawal_mutations
    )

    withdrawal_paths = {
        path
        for path, _methods in write_routes
        if "/withdrawals/" in path
    }

    assert withdrawal_paths == {
        path
        for path, _methods
        in local_withdrawal_mutations
    }

    assert all(
        path != "/api/treasury/withdrawals"
        for path, _methods in write_routes
    )

    assert all(
        "/withdrawals/execute" not in path
        and "/withdrawals/submit" not in path
        and "/withdrawals/reconcile" not in path
        for path, _methods in write_routes
    )

    assert all(
        "/withdrawals/preflight" not in path
        and "/withdrawals/capabilities" not in path
        for path, _methods in write_routes
    )
