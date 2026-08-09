from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

TEST_DB = Path("/tmp/gate_bot_dashboard_test.db")
TEST_USERS = Path("/tmp/gate_bot_dashboard_users.json")
for suffix in ("", "-shm", "-wal"):
    try:
        Path(str(TEST_DB) + suffix).unlink()
    except FileNotFoundError:
        pass


def password_hash(password: str) -> str:
    salt = b"0123456789abcdef"
    iterations = 100_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    enc = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
    return f"pbkdf2_sha256${iterations}${enc(salt)}${enc(digest)}"


TEST_USERS.write_text(
    json.dumps(
        {
            "users": [
                {
                    "username": "zolnode",
                    "password_hash": password_hash("zolnode-test-password"),
                    "account_ids": ["zolnode"],
                    "role": "account_operator",
                    "enabled": True,
                },
                {
                    "username": "arnold",
                    "password_hash": password_hash("arnold-test-password"),
                    "account_ids": ["arnold"],
                    "role": "account_operator",
                    "enabled": True,
                },
                {
                    "username": "rootadmin",
                    "password_hash": password_hash("rootadmin-test-password"),
                    "account_ids": [],
                    "role": "super_admin",
                    "enabled": True,
                },
            ]
        }
    ),
    encoding="utf-8",
)

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["DEMO_MODE"] = "true"
os.environ["POLL_SECONDS"] = "3600"
os.environ["APP_ENV"] = "test"
os.environ["GATE_TREASURY_FILE"] = (
    "/tmp/gate_treasury_test_missing.json"
)
os.environ["TREASURY_MAIN_ACCOUNT"] = "zolnode"
os.environ["DASHBOARD_USERS_FILE"] = str(TEST_USERS)
os.environ["DASHBOARD_USERS_BACKUP_DIR"] = "/tmp/gate_bot_dashboard_user_backups"
os.environ["DASHBOARD_USERS_BACKUP_KEEP"] = "5"
os.environ["DASHBOARD_USERNAME"] = ""
os.environ["DASHBOARD_PASSWORD"] = ""
os.environ["CORS_ORIGINS"] = "https://zolpho.github.io"
