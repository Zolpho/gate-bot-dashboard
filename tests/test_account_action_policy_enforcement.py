from __future__ import annotations

import ast
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.account_action_policy import (
    AccountActionPolicyDenied,
    require_account_action_allowed,
    update_account_action_policy,
)
from app.api import treasury as treasury_api
from app.config import Settings
from app.db import init_db, session_scope
from app.models import GateAccount
from app.security import DashboardUser


@pytest.fixture(
    scope="module",
    autouse=True,
)
def initialize_policy_test_database() -> None:
    # Match normal application startup against the
    # shared temporary test database from conftest.py.
    init_db()


ROOT = Path(__file__).resolve().parents[1]

TREASURY = ROOT / "app/api/treasury.py"

TRANSFER_EXECUTION = (
    ROOT
    / "app/treasury_transfer_execution.py"
)


def unique(prefix: str) -> str:
    return (
        f"{prefix}-"
        f"{uuid.uuid4().hex[:12]}"
    )


def create_account(
    account_id: str,
) -> None:
    with session_scope() as db:
        db.add(
            GateAccount(
                id=account_id,
                name=account_id,
                account_type="subaccount",
                enabled=True,
                configured=True,
            )
        )


def test_require_account_action_allowed_fails_closed() -> None:
    account_id = unique(
        "policy-missing"
    )

    create_account(
        account_id
    )

    with pytest.raises(
        AccountActionPolicyDenied
    ) as raised:
        require_account_action_allowed(
            account_id,
            "transfers",
        )

    error = raised.value

    assert error.account_id == account_id

    assert (
        error.capability
        == "transfers"
    )

    detail = error.safe_dict(
        operation="test_transfer"
    )

    assert (
        detail["reason"]
        == (
            "transfers_disabled_"
            "by_account_policy"
        )
    )

    assert (
        detail["operation"]
        == "test_transfer"
    )


def test_require_account_action_allowed_obeys_policy() -> None:
    account_id = unique(
        "policy-enabled"
    )

    create_account(
        account_id
    )

    update_account_action_policy(
        account_id,
        username="rootadmin",
        transfers_enabled=True,
        reason=(
            "Enable transfer execution "
            "for enforcement test."
        ),
    )

    require_account_action_allowed(
        account_id,
        "transfers",
    )

    update_account_action_policy(
        account_id,
        username="rootadmin",
        transfers_enabled=False,
        reason=(
            "Disable transfer execution "
            "for enforcement test."
        ),
    )

    with pytest.raises(
        AccountActionPolicyDenied
    ):
        require_account_action_allowed(
            account_id,
            "transfers",
        )


def function_node(
    tree: ast.Module,
    name: str,
) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in tree.body:
        if (
            isinstance(
                node,
                ast.FunctionDef | ast.AsyncFunctionDef,
            )
            and node.name == name
        ):
            return node

    raise AssertionError(
        f"Function not found: {name}"
    )


def call_lines(
    node: ast.AST,
    name: str,
) -> list[int]:
    result = []

    for child in ast.walk(node):
        if not isinstance(
            child,
            ast.Call,
        ):
            continue

        func = child.func

        if (
            isinstance(
                func,
                ast.Name,
            )
            and func.id == name
        ):
            result.append(
                child.lineno
            )

        elif (
            isinstance(
                func,
                ast.Attribute,
            )
            and func.attr == name
        ):
            result.append(
                child.lineno
            )

    return sorted(result)


def test_direct_transfer_policy_is_after_replay_before_rate_limit() -> None:
    tree = ast.parse(
        TREASURY.read_text(),
        filename=str(TREASURY),
    )

    cases = (
        (
            "execute_treasury_user_transfer",
            "existing_user_transfer_result",
            "execute_user_account_transfer",
        ),
        (
            "execute_treasury_transfer",
            "existing_live_transfer_result",
            "execute_reserved_live_transfer",
        ),
    )

    for (
        function_name,
        replay_name,
        executor_name,
    ) in cases:
        function = function_node(
            tree,
            function_name,
        )

        replay = call_lines(
            function,
            replay_name,
        )

        policy = call_lines(
            function,
            "_require_account_action_policy",
        )

        rate_limit = call_lines(
            function,
            "_enforce_treasury_rate_limit",
        )

        executor = call_lines(
            function,
            executor_name,
        )

        assert len(replay) == 1
        assert len(policy) == 1
        assert len(rate_limit) == 1
        assert len(executor) == 1

        assert (
            replay[0]
            < policy[0]
            < rate_limit[0]
            < executor[0]
        )


def test_direct_transfer_policy_uses_source_wallet_account() -> None:
    tree = ast.parse(
        TREASURY.read_text(),
        filename=str(TREASURY),
    )

    expected = {
        "execute_treasury_user_transfer":
            "source",
        "execute_treasury_transfer":
            "source_account_id",
    }

    for (
        function_name,
        expected_account_name,
    ) in expected.items():
        function = function_node(
            tree,
            function_name,
        )

        matches = []

        for child in ast.walk(
            function
        ):
            if not isinstance(
                child,
                ast.Call,
            ):
                continue

            if not (
                isinstance(
                    child.func,
                    ast.Name,
                )
                and child.func.id
                == "_require_account_action_policy"
            ):
                continue

            matches.append(
                {
                    keyword.arg:
                        keyword.value
                    for keyword
                    in child.keywords
                    if keyword.arg
                }
            )

        assert len(matches) == 1

        values = matches[0]

        account = values[
            "account_id"
        ]

        capability = values[
            "capability"
        ]

        assert isinstance(
            account,
            ast.Name,
        )

        assert (
            account.id
            == expected_account_name
        )

        assert isinstance(
            capability,
            ast.Constant,
        )

        assert (
            capability.value
            == "transfers"
        )


def test_only_direct_transfer_execute_routes_consume_policy() -> None:
    tree = ast.parse(
        TREASURY.read_text(),
        filename=str(TREASURY),
    )

    consumers = set()

    for node in tree.body:
        if not isinstance(
            node,
            ast.FunctionDef | ast.AsyncFunctionDef,
        ):
            continue

        for child in ast.walk(
            node
        ):
            if not isinstance(
                child,
                ast.Call,
            ):
                continue

            if (
                isinstance(
                    child.func,
                    ast.Name,
                )
                and child.func.id
                == "_require_account_action_policy"
            ):
                consumers.add(
                    node.name
                )

    assert consumers == {
        "execute_treasury_user_transfer",
        "execute_treasury_transfer",
    }


def test_shared_transfer_executor_remains_policy_agnostic() -> None:
    tree = ast.parse(
        TRANSFER_EXECUTION.read_text(),
        filename=str(
            TRANSFER_EXECUTION
        ),
    )

    imported_modules = []

    for node in ast.walk(tree):
        if isinstance(
            node,
            ast.ImportFrom,
        ):
            imported_modules.append(
                node.module or ""
            )

        elif isinstance(
            node,
            ast.Import,
        ):
            imported_modules.extend(
                alias.name
                for alias in node.names
            )

    assert not any(
        module.endswith(
            "account_action_policy"
        )
        for module
        in imported_modules
    )

    source = (
        TRANSFER_EXECUTION
        .read_text()
    )

    assert (
        "require_account_action_allowed"
        not in source
    )

    assert (
        "account_action_allowed"
        not in source
    )


def attribute_lines(
    node: ast.AST,
    name: str,
) -> list[int]:
    return sorted(
        child.lineno
        for child in ast.walk(node)
        if (
            isinstance(
                child,
                ast.Attribute,
            )
            and child.attr == name
        )
    )


def test_global_gates_precede_account_policy() -> None:
    tree = ast.parse(
        TREASURY.read_text(),
        filename=str(TREASURY),
    )

    user = function_node(
        tree,
        "execute_treasury_user_transfer",
    )

    user_replay = call_lines(
        user,
        "existing_user_transfer_result",
    )

    user_global_arm = attribute_lines(
        user,
        "treasury_user_transfers_enabled",
    )

    user_policy = call_lines(
        user,
        "_require_account_action_policy",
    )

    user_rate_limit = call_lines(
        user,
        "_enforce_treasury_rate_limit",
    )

    user_executor = call_lines(
        user,
        "execute_user_account_transfer",
    )

    assert len(user_replay) == 1
    assert len(user_global_arm) == 1
    assert len(user_policy) == 1
    assert len(user_rate_limit) == 1
    assert len(user_executor) == 1

    assert (
        user_replay[0]
        < user_global_arm[0]
        < user_policy[0]
        < user_rate_limit[0]
        < user_executor[0]
    )

    direct = function_node(
        tree,
        "execute_treasury_transfer",
    )

    direct_replay = call_lines(
        direct,
        "existing_live_transfer_result",
    )

    direct_global_arm = attribute_lines(
        direct,
        "treasury_transfers_live_armed",
    )

    direct_allowlist = attribute_lines(
        direct,
        "treasury_transfers_live_account_allowed",
    )

    direct_policy = call_lines(
        direct,
        "_require_account_action_policy",
    )

    direct_rate_limit = call_lines(
        direct,
        "_enforce_treasury_rate_limit",
    )

    direct_executor = call_lines(
        direct,
        "execute_reserved_live_transfer",
    )

    assert len(direct_replay) == 1
    assert len(direct_global_arm) == 1
    assert len(direct_allowlist) == 1
    assert len(direct_policy) == 1
    assert len(direct_rate_limit) == 1
    assert len(direct_executor) == 1

    assert (
        direct_replay[0]
        < direct_global_arm[0]
        < direct_allowlist[0]
        < direct_policy[0]
        < direct_rate_limit[0]
        < direct_executor[0]
    )


@pytest.mark.asyncio
async def test_direct_treasury_route_policy_denial_never_dispatches(
    monkeypatch,
) -> None:
    source = SimpleNamespace(
        id="policy-direct-source",
        name="Policy direct source",
        account_type="subaccount",
        gate_uid="101",
        enabled=True,
        configured=True,
    )

    user = DashboardUser(
        username="policy-direct-user",
        role="account_operator",
        account_ids=(
            source.id,
        ),
        enabled=True,
    )

    monkeypatch.setattr(
        treasury_api,
        "settings",
        Settings(
            _env_file=None,
            treasury_transfers_live_armed=True,
            treasury_transfers_live_accounts=(
                source.id
            ),
            treasury_rate_limit_enabled=False,
        ),
    )

    monkeypatch.setattr(
        treasury_api,
        "get_gate_account",
        lambda account_id: (
            source
            if account_id == source.id
            else None
        ),
    )

    monkeypatch.setattr(
        treasury_api,
        "build_gate_subaccount_transfer_payload",
        lambda **_kwargs: {
            "sub_account": "101",
            "sub_account_type": "spot",
            "currency": "USDT",
            "amount": "1",
            "direction": "from",
            "client_order_id": (
                "policy-direct-route-test"
            ),
        },
    )

    monkeypatch.setattr(
        treasury_api,
        "find_matching_transfer_request",
        lambda **_kwargs: None,
    )

    monkeypatch.setattr(
        treasury_api,
        "live_transfer_confirmation_text",
        lambda **_kwargs: (
            "CONFIRM POLICY DIRECT TEST"
        ),
    )

    policy_calls = []

    def deny_policy(
        account_id: str,
        capability: str,
    ) -> None:
        policy_calls.append(
            (
                account_id,
                capability,
            )
        )

        raise AccountActionPolicyDenied(
            account_id=account_id,
            capability=capability,
        )

    monkeypatch.setattr(
        treasury_api,
        "require_account_action_allowed",
        deny_policy,
    )

    rate_limit_called = False

    def forbidden_rate_limit(
        **_kwargs,
    ) -> None:
        nonlocal rate_limit_called
        rate_limit_called = True

        raise AssertionError(
            "Policy-denied route reached rate limit"
        )

    monkeypatch.setattr(
        treasury_api,
        "_enforce_treasury_rate_limit",
        forbidden_rate_limit,
    )

    executor_called = False

    async def forbidden_executor(
        **_kwargs,
    ):
        nonlocal executor_called
        executor_called = True

        raise AssertionError(
            "Policy-denied route reached executor"
        )

    monkeypatch.setattr(
        treasury_api,
        "execute_reserved_live_transfer",
        forbidden_executor,
    )

    request = (
        treasury_api
        .TreasuryTransferExecutionRequest(
            request_id=(
                "policy-direct-route-0001"
            ),
            source_account_id=source.id,
            currency="USDT",
            amount=Decimal("1"),
            confirmation=(
                "CONFIRM POLICY DIRECT TEST"
            ),
        )
    )

    with pytest.raises(
        HTTPException
    ) as raised:
        await (
            treasury_api
            .execute_treasury_transfer(
                request,
                user,
            )
        )

    assert raised.value.status_code == 403

    detail = raised.value.detail

    assert detail == {
        "reason": (
            "transfers_disabled_by_account_policy"
        ),
        "message": (
            "The Transfers capability is disabled "
            "for Wallet account policy-direct-source"
        ),
        "account_id": "policy-direct-source",
        "capability": "transfers",
        "operation": "treasury_transfer",
        "gate_write_performed": False,
    }

    assert policy_calls == [
        (
            "policy-direct-source",
            "transfers",
        )
    ]

    assert rate_limit_called is False
    assert executor_called is False


@pytest.mark.parametrize(
    ("capability", "expected"),
    (
        (
            "transfers",
            (
                "The Transfers capability is disabled "
                "for Wallet account review-wallet"
            ),
        ),
        (
            "withdrawals",
            (
                "The Withdrawals capability is disabled "
                "for Wallet account review-wallet"
            ),
        ),
        (
            "trading",
            (
                "The Trading capability is disabled "
                "for Wallet account review-wallet"
            ),
        ),
    ),
)
def test_denial_message_is_generic_and_grammatical(
    capability: str,
    expected: str,
) -> None:
    error = AccountActionPolicyDenied(
        account_id="review-wallet",
        capability=capability,
    )

    assert str(error) == expected

    detail = error.safe_dict(
        operation="review",
    )

    assert detail["message"] == expected

    assert detail["reason"] == (
        f"{capability}"
        "_disabled_by_account_policy"
    )
