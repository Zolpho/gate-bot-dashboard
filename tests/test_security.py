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


def test_change_password_updates_only_authenticated_user(tmp_path) -> None:
    import json

    from app.config import Settings
    from app.security import change_dashboard_user_password

    users_path = tmp_path / "dashboard_users.json"
    backup_dir = tmp_path / "backups"
    original_hash = hash_password("old-password-123")
    other_hash = hash_password("other-password-123")
    users_path.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "username": "alice",
                        "password_hash": original_hash,
                        "account_ids": ["alice"],
                        "role": "account_operator",
                        "enabled": True,
                    },
                    {
                        "username": "bob",
                        "password_hash": other_hash,
                        "account_ids": ["bob"],
                        "role": "account_operator",
                        "enabled": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    user = DashboardUser(
        username="alice",
        role="account_operator",
        account_ids=("alice",),
        password_hash=original_hash,
    )
    settings = Settings(
        dashboard_users_file=users_path,
        dashboard_users_backup_dir=backup_dir,
        dashboard_users_backup_keep=5,
    )

    change_dashboard_user_password(
        user,
        "old-password-123",
        "new-password-456",
        settings=settings,
    )

    payload = json.loads(users_path.read_text(encoding="utf-8"))
    alice = next(item for item in payload["users"] if item["username"] == "alice")
    bob = next(item for item in payload["users"] if item["username"] == "bob")
    assert verify_password("new-password-456", alice["password_hash"])
    assert not verify_password("old-password-123", alice["password_hash"])
    assert bob["password_hash"] == other_hash
    assert alice["password_changed_at"]
    assert len(list(backup_dir.glob("dashboard_users.alice.*.json"))) == 1
