from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(
    __file__
).resolve().parents[1]

WRITE_METHODS = {
    "post",
    "put",
    "patch",
    "delete",
}

RISK_MODULES = {
    "app/api/bot_control.py":
        7,
    "app/api/trading.py":
        7,
    "app/api/treasury.py":
        27,
}

RECOVERY_COMPATIBILITY = {
    "set_current_user_passkey_enabled":
        "require_user",
    "revoke_current_user_passkey":
        "require_user",
    "enroll_totp":
        "require_user",
    "confirm_totp":
        "require_user",
    "administrator_reset_mfa":
        "require_super_admin",
    "change_password":
        "require_user",
}


def _tree(
    relative: str,
) -> ast.Module:
    path = ROOT / relative

    return ast.parse(
        path.read_text(
            encoding="utf-8"
        ),
        filename=str(path),
    )


def _names(
    node: ast.AST,
) -> set[str]:
    return {
        item.id
        for item in ast.walk(
            node
        )
        if isinstance(
            item,
            ast.Name,
        )
    }


def _function(
    tree: ast.Module,
    name: str,
):
    return next(
        node
        for node in tree.body
        if (
            isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and node.name == name
        )
    )


def _is_write_route(
    node: ast.AST,
) -> bool:
    if not isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        ),
    ):
        return False

    for decorator in (
        node.decorator_list
    ):
        if not isinstance(
            decorator,
            ast.Call,
        ):
            continue

        func = decorator.func

        if (
            isinstance(
                func,
                ast.Attribute,
            )
            and func.attr
            in WRITE_METHODS
        ):
            return True

    return False


def test_generic_require_user_keeps_basic_compatibility() -> None:
    tree = _tree(
        "app/security.py"
    )

    node = _function(
        tree,
        "require_user",
    )

    names = _names(
        node
    )

    assert (
        "authenticate_credentials"
        in names
    )

    assert (
        "_require_basic_ip_access"
        in names
    )

    assert (
        "_resolve_bearer_user"
        in names
    )


def test_explicit_bearer_dependency_uses_session_resolver() -> None:
    tree = _tree(
        "app/security.py"
    )

    bearer = _function(
        tree,
        "require_bearer_user",
    )

    bearer_names = _names(
        bearer
    )

    assert (
        "_resolve_bearer_user"
        in bearer_names
    )

    assert (
        "_bearer_authentication_error"
        in bearer_names
    )

    resolver = _function(
        tree,
        "_resolve_bearer_user",
    )

    resolver_names = _names(
        resolver
    )

    assert (
        "resolve_bearer_session"
        in resolver_names
    )


def test_risk_on_write_routes_are_explicitly_bearer_only() -> None:
    for (
        relative,
        expected_count,
    ) in RISK_MODULES.items():
        tree = _tree(
            relative
        )

        routes = [
            node
            for node in tree.body
            if _is_write_route(
                node
            )
        ]

        assert (
            len(routes)
            == expected_count
        )

        for node in routes:
            names = _names(
                node
            )

            assert (
                "require_bearer_user"
                in names
                or
                "require_bearer_super_admin"
                in names
            )

            assert not (
                "require_user"
                in names
            )

            assert not (
                "require_super_admin"
                in names
            )


def test_account_policy_mutation_requires_bearer_superadmin() -> None:
    tree = _tree(
        "app/api/auth.py"
    )

    node = _function(
        tree,
        "change_account_action_policy",
    )

    names = _names(
        node
    )

    assert (
        "require_bearer_super_admin"
        in names
    )

    assert (
        "require_super_admin"
        not in names
    )


def test_auth_recovery_contract_remains_on_generic_authentication() -> None:
    tree = _tree(
        "app/api/auth.py"
    )

    for (
        function_name,
        expected_dependency,
    ) in RECOVERY_COMPATIBILITY.items():
        node = _function(
            tree,
            function_name,
        )

        names = _names(
            node
        )

        assert (
            expected_dependency
            in names
        )

        assert (
            "require_bearer_user"
            not in names
        )

        assert (
            "require_bearer_super_admin"
            not in names
        )
