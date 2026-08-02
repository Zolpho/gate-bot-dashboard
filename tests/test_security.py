from __future__ import annotations

from app.security import DashboardUser, hash_password, require_account_access, verify_password


def test_password_hash_round_trip() -> None:
    encoded = hash_password("a-long-test-password")
    assert verify_password("a-long-test-password", encoded)
    assert not verify_password("wrong-password", encoded)


def test_account_operator_scope() -> None:
    user = DashboardUser(
        username="zolnode",
        role="account_operator",
        account_ids=("zolnode",),
        password_hash="unused",
    )
    assert require_account_access(user, "zolnode") == "zolnode"
