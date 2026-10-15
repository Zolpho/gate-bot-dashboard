from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

from app.demo_auth import (
    DEMO_TOKEN_PREFIX,
    DemoSessionStore,
)
from app.security import DashboardUser


BASE_TIME = datetime(
    2026,
    10,
    15,
    19,
    0,
    tzinfo=timezone.utc,
)


def test_live_dashboard_user_contract_is_unchanged():
    user = DashboardUser(
        username="operator",
        role="account_operator",
        account_ids=("wallet-a",),
    )

    assert user.execution_mode == "live"
    assert user.is_demo is False

    assert user.safe_dict() == {
        "username": "operator",
        "role": "account_operator",
        "account_ids": ["wallet-a"],
        "enabled": True,
        "auth_source": "file",
    }


def test_demo_user_advertises_demo_execution_mode():
    user = DashboardUser(
        username="demo",
        role="account_operator",
        account_ids=(
            "demo-wallet-1",
            "demo-wallet-2",
        ),
        auth_source="demo",
        execution_mode="demo",
    )

    assert user.is_demo is True

    assert user.safe_dict() == {
        "username": "demo",
        "role": "account_operator",
        "account_ids": [
            "demo-wallet-1",
            "demo-wallet-2",
        ],
        "enabled": True,
        "auth_source": "demo",
        "execution_mode": "demo",
    }


def test_demo_session_store_isolated_create_and_resolve(
    tmp_path,
):
    path = (
        tmp_path
        / "demo"
        / "demo.db"
    )

    store = DemoSessionStore(
        path
    )

    token, created = (
        store.create_session(
            account_ids=(
                "demo-wallet-1",
                "demo-wallet-2",
            ),
            ttl_seconds=3600,
            now=BASE_TIME,
        )
    )

    assert token.startswith(
        DEMO_TOKEN_PREFIX
    )

    assert created[
        "execution_mode"
    ] == "demo"

    assert path.exists()

    resolved = (
        store.resolve_session(
            token,
            now=(
                BASE_TIME
                + timedelta(
                    minutes=10
                )
            ),
        )
    )

    assert resolved is not None

    user = resolved["user"]

    assert user.is_demo is True
    assert user.auth_source == "demo"
    assert user.role == "account_operator"
    assert user.account_ids == (
        "demo-wallet-1",
        "demo-wallet-2",
    )

    assert resolved[
        "session"
    ][
        "execution_mode"
    ] == "demo"


def test_demo_store_never_persists_raw_bearer_token(
    tmp_path,
):
    path = tmp_path / "demo.db"

    store = DemoSessionStore(
        path
    )

    token, _ = store.create_session(
        account_ids=(
            "demo-wallet-1",
        ),
        ttl_seconds=3600,
        now=BASE_TIME,
    )

    digest = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    with sqlite3.connect(path) as db:
        row = db.execute(
            """
            SELECT token_hash
            FROM demo_sessions
            """
        ).fetchone()

    assert row is not None
    assert row[0] == digest
    assert row[0] != token

    raw = path.read_bytes()

    assert (
        token.encode("utf-8")
        not in raw
    )


def test_demo_session_expiry_fails_closed(
    tmp_path,
):
    path = tmp_path / "demo.db"

    store = DemoSessionStore(
        path
    )

    token, _ = store.create_session(
        account_ids=(
            "demo-wallet-1",
        ),
        ttl_seconds=60,
        now=BASE_TIME,
    )

    assert (
        store.resolve_session(
            token,
            now=(
                BASE_TIME
                + timedelta(
                    seconds=59
                )
            ),
        )
        is not None
    )

    assert (
        store.resolve_session(
            token,
            now=(
                BASE_TIME
                + timedelta(
                    seconds=60
                )
            ),
        )
        is None
    )


def test_demo_session_revocation_fails_closed(
    tmp_path,
):
    path = tmp_path / "demo.db"

    store = DemoSessionStore(
        path
    )

    token, _ = store.create_session(
        account_ids=(
            "demo-wallet-1",
        ),
        ttl_seconds=3600,
        now=BASE_TIME,
    )

    assert store.revoke_session(
        token,
        now=(
            BASE_TIME
            + timedelta(
                minutes=5
            )
        ),
    ) is True

    assert (
        store.resolve_session(
            token,
            now=(
                BASE_TIME
                + timedelta(
                    minutes=6
                )
            ),
        )
        is None
    )


def test_non_demo_token_never_creates_store(
    tmp_path,
):
    path = tmp_path / "demo.db"

    store = DemoSessionStore(
        path
    )

    assert (
        store.resolve_session(
            "ordinary-live-token",
            now=BASE_TIME,
        )
        is None
    )

    assert path.exists() is False
