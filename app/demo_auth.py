from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .security import DashboardUser


DEMO_TOKEN_PREFIX = "gdbdemo_"
DEMO_USERNAME = "demo"

# These are intentionally synthetic Wallet-account identities.
# They do not correspond to production Gate account IDs.
DEMO_ACCOUNT_IDS = (
    "demo-wallet-1",
    "demo-wallet-2",
)

# Demo requests are method-aware and explicitly bounded.
# Only surfaces with an accepted isolated adapter are added here.
DEMO_AUTH_REQUEST_ALLOWLIST = frozenset(
    {
        ("GET", "/api/auth/me"),
        ("POST", "/api/auth/logout"),
        ("GET", "/api/me/balance"),
        ("GET", "/api/deposit/currencies"),
        ("GET", "/api/me/deposits"),
    }
)

_DEMO_WALLET_GET_PATH_PATTERNS = (
    re.compile(
        r"^/api/me/deposit/"
        r"[A-Za-z0-9._-]+"
        r"(?:/networks)?$"
    ),
    re.compile(
        r"^/api/me/deposits/"
        r"[0-9]+$"
    ),
)


def demo_request_is_allowed(
    method: str,
    path: str,
) -> bool:
    normalized_method = str(
        method or ""
    ).strip().upper()

    normalized_path = str(
        path or ""
    ).strip()

    if (
        normalized_method,
        normalized_path,
    ) in DEMO_AUTH_REQUEST_ALLOWLIST:
        return True

    if normalized_method != "GET":
        return False

    return any(
        pattern.fullmatch(
            normalized_path
        )
        is not None
        for pattern
        in _DEMO_WALLET_GET_PATH_PATTERNS
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalized_now(
    value: datetime | None,
) -> datetime:
    result = value or _utc_now()

    if result.tzinfo is None:
        raise ValueError(
            "Demo session timestamps must be timezone-aware"
        )

    return result.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(
        timezone.utc
    ).isoformat()


def _token_hash(token: str) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


class DemoSessionStore:
    """
    Dedicated demo-session storage.

    This store intentionally does not import or use the application's
    production SQLAlchemy engine, SessionLocal, auth-state tables, Gate
    credentials, or Gate transports.

    The caller explicitly supplies the SQLite path. This makes the
    production/demo storage boundary testable and keeps Demo state out
    of gate_bots.db.
    """

    def __init__(
        self,
        database_path: Path,
    ) -> None:
        self.database_path = Path(
            database_path
        )

    def _connect(
        self,
    ) -> sqlite3.Connection:
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        connection = sqlite3.connect(
            self.database_path,
            timeout=5.0,
        )

        connection.row_factory = (
            sqlite3.Row
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS demo_sessions (
                token_hash TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                account_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                revoked_at TEXT
            )
            """
        )

        connection.commit()

        return connection

    def create_session(
        self,
        *,
        account_ids: tuple[str, ...],
        ttl_seconds: int,
        username: str = DEMO_USERNAME,
        role: str = "account_operator",
        now: datetime | None = None,
    ) -> tuple[str, dict[str, Any]]:
        if ttl_seconds < 1:
            raise ValueError(
                "Demo session TTL must be positive"
            )

        if role not in {
            "account_operator",
            "super_admin",
        }:
            raise ValueError(
                "Unsupported Demo dashboard role"
            )

        normalized_accounts = tuple(
            dict.fromkeys(
                item.strip().lower()
                for item in account_ids
                if item.strip()
            )
        )

        if not normalized_accounts:
            raise ValueError(
                "Demo session requires at least one Demo Wallet account"
            )

        timestamp = _normalized_now(
            now
        )

        expires_at = (
            timestamp
            + timedelta(
                seconds=ttl_seconds
            )
        )

        token = (
            DEMO_TOKEN_PREFIX
            + secrets.token_urlsafe(32)
        )

        digest = _token_hash(
            token
        )

        with self._connect() as db:
            db.execute(
                """
                INSERT INTO demo_sessions (
                    token_hash,
                    username,
                    role,
                    account_ids_json,
                    created_at,
                    expires_at,
                    last_seen_at,
                    revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    digest,
                    username.strip().lower(),
                    role,
                    json.dumps(
                        list(
                            normalized_accounts
                        ),
                        separators=(",", ":"),
                    ),
                    _iso(timestamp),
                    _iso(expires_at),
                    _iso(timestamp),
                ),
            )

        return (
            token,
            {
                "username":
                    username.strip().lower(),
                "role":
                    role,
                "account_ids":
                    list(
                        normalized_accounts
                    ),
                "created_at":
                    _iso(timestamp),
                "expires_at":
                    _iso(expires_at),
                "last_seen_at":
                    _iso(timestamp),
                "execution_mode":
                    "demo",
            },
        )

    def resolve_session(
        self,
        token: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        if not token.startswith(
            DEMO_TOKEN_PREFIX
        ):
            return None

        timestamp = _normalized_now(
            now
        )

        digest = _token_hash(
            token
        )

        if not self.database_path.exists():
            return None

        with self._connect() as db:
            row = db.execute(
                """
                SELECT
                    username,
                    role,
                    account_ids_json,
                    created_at,
                    expires_at,
                    last_seen_at,
                    revoked_at
                FROM demo_sessions
                WHERE token_hash = ?
                """,
                (digest,),
            ).fetchone()

            if row is None:
                return None

            if row["revoked_at"]:
                return None

            try:
                expires_at = (
                    datetime.fromisoformat(
                        row["expires_at"]
                    )
                )

                account_ids_raw = (
                    json.loads(
                        row[
                            "account_ids_json"
                        ]
                    )
                )
            except (
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ):
                return None

            if (
                expires_at.tzinfo is None
                or expires_at
                <= timestamp
            ):
                return None

            if (
                not isinstance(
                    account_ids_raw,
                    list,
                )
                or not all(
                    isinstance(
                        item,
                        str,
                    )
                    and item.strip()
                    for item
                    in account_ids_raw
                )
            ):
                return None

            role = str(
                row["role"]
            )

            if role not in {
                "account_operator",
                "super_admin",
            }:
                return None

            account_ids = tuple(
                item.strip().lower()
                for item
                in account_ids_raw
            )

            db.execute(
                """
                UPDATE demo_sessions
                SET last_seen_at = ?
                WHERE token_hash = ?
                  AND revoked_at IS NULL
                """,
                (
                    _iso(timestamp),
                    digest,
                ),
            )

            user = DashboardUser(
                username=str(
                    row["username"]
                ).strip().lower(),
                role=role,  # type: ignore[arg-type]
                account_ids=account_ids,
                enabled=True,
                password_hash="",
                auth_source="demo",
                execution_mode="demo",
            )

            return {
                "user":
                    user,
                "session": {
                    "username":
                        user.username,
                    "role":
                        user.role,
                    "account_ids":
                        list(
                            user.account_ids
                        ),
                    "created_at":
                        row[
                            "created_at"
                        ],
                    "expires_at":
                        row[
                            "expires_at"
                        ],
                    "last_seen_at":
                        _iso(timestamp),
                    "execution_mode":
                        "demo",
                },
            }

    def revoke_session(
        self,
        token: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        if not token.startswith(
            DEMO_TOKEN_PREFIX
        ):
            return False

        if not self.database_path.exists():
            return False

        timestamp = _normalized_now(
            now
        )

        digest = _token_hash(
            token
        )

        with self._connect() as db:
            cursor = db.execute(
                """
                UPDATE demo_sessions
                SET revoked_at = ?
                WHERE token_hash = ?
                  AND revoked_at IS NULL
                """,
                (
                    _iso(timestamp),
                    digest,
                ),
            )

            return (
                cursor.rowcount == 1
            )
