from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from app.api import treasury as treasury_api
from app.treasury_withdrawal_settlement import (
    withdrawal_settlement_action_policy,
)


@pytest.mark.parametrize(
    (
        "status",
        "live_armed",
        "settlement_allowed",
        "replay_only",
        "replay_allowed",
    ),
    [
        (
            "withdrawal_done_unsettled",
            False,
            True,
            False,
            False,
        ),
        (
            "withdrawal_done_unsettled",
            True,
            False,
            False,
            False,
        ),
        (
            "withdrawal_settled",
            False,
            False,
            True,
            True,
        ),
        (
            "withdrawal_settled",
            True,
            False,
            True,
            False,
        ),
        (
            "jit_ready",
            False,
            False,
            False,
            False,
        ),
    ],
)
def test_settlement_action_policy_separates_normal_action_from_replay(
    status,
    live_armed,
    settlement_allowed,
    replay_only,
    replay_allowed,
):
    policy = (
        withdrawal_settlement_action_policy(
            status=status,
            withdrawals_live_armed=(
                live_armed
            ),
        )
    )

    assert (
        policy["settlement_allowed"]
        is settlement_allowed
    )

    assert (
        policy["idempotent_replay_only"]
        is replay_only
    )

    assert (
        policy["idempotent_replay_allowed"]
        is replay_allowed
    )


def test_request_detail_uses_settlement_action_policy():
    """
    Structural integration check.

    Keep this semantic/AST-based rather than relying on
    fragile source-string ordering.
    """

    source = textwrap.dedent(
        inspect.getsource(
            treasury_api
            .treasury_withdrawal_request_detail
        )
    )

    tree = ast.parse(source)

    calls = []

    preview_dicts = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func

            if (
                isinstance(fn, ast.Name)
                and fn.id
                == "withdrawal_settlement_action_policy"
            ):
                calls.append(node)

        if isinstance(node, ast.Dict):
            keys = {
                key.value
                for key in node.keys
                if (
                    isinstance(
                        key,
                        ast.Constant,
                    )
                    and isinstance(
                        key.value,
                        str,
                    )
                )
            }

            if (
                "settlement_allowed"
                in keys
                and "required_confirmation"
                in keys
            ):
                preview_dicts.append(
                    keys
                )

    assert len(calls) == 1

    assert len(preview_dicts) == 1

    keys = preview_dicts[0]

    assert (
        "idempotent_replay_only"
        in keys
    )

    assert (
        "idempotent_replay_allowed"
        in keys
    )
