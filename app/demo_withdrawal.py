from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .demo_auth import DEMO_ACCOUNT_IDS
from .demo_wallet import (
    DemoWalletStateError,
    DemoWalletStore,
)


DEMO_WITHDRAWAL_SEED_VERSION = "1"

DEMO_WITHDRAWAL_SEED_TIMESTAMP = (
    "2026-10-17T12:00:00+00:00"
)


class DemoWithdrawalRegistryError(
    DemoWalletStateError
):
    """Isolated Demo withdrawal registry validation failed."""


class DemoWithdrawalRegistryConflict(
    DemoWithdrawalRegistryError
):
    """A Demo withdrawal registry identity conflicts."""


_EVM_ADDRESS_RE = re.compile(
    r"^0x[0-9a-fA-F]{40}$",
    re.IGNORECASE,
)


_SEED_POLICIES = (
    {
        "currency": "USDT",
        "chain": "ETH",
        "network_name": "Ethereum",
        "withdraw_enabled": True,
        "requires_memo": False,
        "decimal_places": 6,
        "minimum_withdrawal": "10",
        "maximum_per_withdrawal": "10000",
        "daily_limit": "25000",
        "fixed_fee": "1.04",
        "sort_order": 1,
    },
    {
        "currency": "USDT",
        "chain": "TRX",
        "network_name": "TRON",
        "withdraw_enabled": True,
        "requires_memo": False,
        "decimal_places": 6,
        "minimum_withdrawal": "10",
        "maximum_per_withdrawal": "20000",
        "daily_limit": "50000",
        "fixed_fee": "1",
        "sort_order": 2,
    },
    {
        "currency": "EQTY",
        "chain": "BASE",
        "network_name": "Base",
        "withdraw_enabled": True,
        "requires_memo": False,
        "decimal_places": 18,
        "minimum_withdrawal": "1000",
        "maximum_per_withdrawal": "1000000",
        "daily_limit": "2500000",
        "fixed_fee": "100",
        "sort_order": 1,
    },
    {
        "currency": "BTC",
        "chain": "BTC",
        "network_name": "Bitcoin",
        "withdraw_enabled": True,
        "requires_memo": False,
        "decimal_places": 8,
        "minimum_withdrawal": "0.001",
        "maximum_per_withdrawal": "0.1",
        "daily_limit": "0.25",
        "fixed_fee": "0.0002",
        "sort_order": 1,
    },
    {
        "currency": "ETH",
        "chain": "ETH",
        "network_name": "Ethereum",
        "withdraw_enabled": True,
        "requires_memo": False,
        "decimal_places": 18,
        "minimum_withdrawal": "0.01",
        "maximum_per_withdrawal": "10",
        "daily_limit": "25",
        "fixed_fee": "0.001",
        "sort_order": 1,
    },
)


_SEED_RECIPIENTS = (
    {
        "recipient_id": "demo-recipient-growth",
        "owner_account_id": "demo-wallet-1",
        "address": "DEMO-ONLY-EXTERNAL-GROWTH-001",
        "label": "Demo Growth recipient",
        "created_by": "demo",
    },
    {
        "recipient_id": "demo-recipient-treasury",
        "owner_account_id": "demo-wallet-2",
        "address": "DEMO-ONLY-EXTERNAL-TREASURY-001",
        "label": "Demo Treasury recipient",
        "created_by": "demo",
    },
)


_SEED_DESTINATIONS = (
    {
        "destination_id": "demo-destination-growth-usdt-eth",
        "owner_account_id": "demo-wallet-1",
        "recipient_id": "demo-recipient-growth",
        "currency": "USDT",
        "chain": "ETH",
        "memo": "",
    },
    {
        "destination_id": "demo-destination-growth-eqty-base",
        "owner_account_id": "demo-wallet-1",
        "recipient_id": "demo-recipient-growth",
        "currency": "EQTY",
        "chain": "BASE",
        "memo": "",
    },
    {
        "destination_id": "demo-destination-treasury-usdt-trx",
        "owner_account_id": "demo-wallet-2",
        "recipient_id": "demo-recipient-treasury",
        "currency": "USDT",
        "chain": "TRX",
        "memo": "",
    },
    {
        "destination_id": "demo-destination-treasury-eth",
        "owner_account_id": "demo-wallet-2",
        "recipient_id": "demo-recipient-treasury",
        "currency": "ETH",
        "chain": "ETH",
        "memo": "",
    },
)


def _now(
    value: str | None = None,
) -> str:
    return str(
        value
        or datetime.now(
            timezone.utc
        ).isoformat()
    ).strip()


def _normalize_account_id(
    value: str,
) -> str:
    account_id = str(
        value or ""
    ).strip().lower()

    if account_id not in DEMO_ACCOUNT_IDS:
        raise KeyError(
            "Unknown Demo Wallet account"
        )

    return account_id


def _normalize_account_scope(
    account_ids: set[str] | None,
) -> set[str] | None:
    if account_ids is None:
        return None

    return {
        _normalize_account_id(
            account_id
        )
        for account_id
        in account_ids
    }


def _normalize_currency(
    value: str,
) -> str:
    currency = str(
        value or ""
    ).strip().upper()

    if (
        not currency
        or len(currency) > 20
        or not re.fullmatch(
            r"[A-Z0-9_]+",
            currency,
        )
    ):
        raise ValueError(
            "Invalid Demo withdrawal currency"
        )

    return currency


def _normalize_chain(
    value: str,
) -> str:
    chain = str(
        value or ""
    ).strip().upper()

    if (
        not chain
        or len(chain) > 64
        or not re.fullmatch(
            r"[A-Z0-9._-]+",
            chain,
        )
    ):
        raise ValueError(
            "Invalid Demo withdrawal chain"
        )

    return chain


def _normalize_address(
    value: str,
) -> str:
    address = str(
        value or ""
    ).strip()

    if (
        not address
        or len(address) > 512
    ):
        raise ValueError(
            "Invalid Demo withdrawal recipient address"
        )

    return address


def _address_key(
    value: str,
) -> str:
    address = _normalize_address(
        value
    )

    if _EVM_ADDRESS_RE.fullmatch(
        address
    ):
        return address.lower()

    return address


def _normalize_label(
    value: str,
) -> str:
    label = str(
        value or ""
    ).strip()

    if len(label) > 128:
        raise ValueError(
            "Demo withdrawal recipient label is too long"
        )

    return label


def _normalize_memo(
    value: str,
) -> str:
    memo = str(
        value or ""
    ).strip()

    if len(memo) > 512:
        raise ValueError(
            "Demo withdrawal memo is too long"
        )

    return memo


def _normalize_username(
    value: str,
) -> str:
    username = str(
        value or ""
    ).strip()

    if (
        not username
        or len(username) > 128
    ):
        raise ValueError(
            "Invalid Demo withdrawal username"
        )

    return username


def _stable_id(
    prefix: str,
    *parts: str,
) -> str:
    digest = hashlib.sha256(
        "\x1f".join(
            parts
        ).encode(
            "utf-8"
        )
    ).hexdigest()[:24]

    return (
        prefix
        + digest
    )


def _recipient_id(
    owner_account_id: str,
    address_key: str,
) -> str:
    return _stable_id(
        "demo-recipient-",
        owner_account_id,
        address_key,
    )


def _destination_id(
    *,
    owner_account_id: str,
    currency: str,
    chain: str,
    address: str,
    memo: str,
) -> str:
    return _stable_id(
        "demo-destination-",
        owner_account_id,
        currency,
        chain,
        address,
        memo,
    )


def _json(
    value: Any,
) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        ensure_ascii=False,
        default=str,
    )


def _load_json(
    value: str,
) -> Any:
    try:
        return json.loads(
            value
        )

    except (
        json.JSONDecodeError,
        TypeError,
    ):
        return {}


class DemoWithdrawalStore:
    """
    Withdrawal-only state in the isolated Demo SQLite database.

    This module deliberately has no dependency on Gate transports,
    Treasury services, production SQLAlchemy repositories, account
    credentials, application settings, or HTTP routing.

    DemoWalletStore owns the base synthetic Wallet. This store adds
    only withdrawal-specific tables in the same isolated database.
    """

    def __init__(
        self,
        database_path: Path,
    ) -> None:
        self.database_path = Path(
            database_path
        )

        self.wallet_store = (
            DemoWalletStore(
                self.database_path
            )
        )

    def _connect(
        self,
    ) -> sqlite3.Connection:
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        db = sqlite3.connect(
            self.database_path,
            timeout=5.0,
        )

        db.row_factory = sqlite3.Row

        db.execute(
            "PRAGMA foreign_keys = ON"
        )

        return db

    def _initialize_schema(
        self,
        db: sqlite3.Connection,
    ) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS
                demo_withdrawal_policies (
                    currency TEXT NOT NULL,
                    chain TEXT NOT NULL,
                    network_name TEXT NOT NULL,
                    withdraw_enabled INTEGER NOT NULL,
                    requires_memo INTEGER NOT NULL,
                    decimal_places INTEGER NOT NULL,
                    minimum_withdrawal TEXT NOT NULL,
                    maximum_per_withdrawal TEXT NOT NULL,
                    daily_limit TEXT NOT NULL,
                    fixed_fee TEXT NOT NULL,
                    sort_order INTEGER NOT NULL,
                    PRIMARY KEY (
                        currency,
                        chain
                    ),
                    FOREIGN KEY (
                        currency
                    )
                    REFERENCES demo_wallet_currencies (
                        currency
                    )
                );

            CREATE TABLE IF NOT EXISTS
                demo_withdrawal_recipients (
                    recipient_id TEXT PRIMARY KEY,
                    owner_account_id TEXT NOT NULL,
                    address TEXT NOT NULL,
                    address_key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    archived_by TEXT NOT NULL,
                    archived_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (
                        owner_account_id,
                        address_key
                    ),
                    FOREIGN KEY (
                        owner_account_id
                    )
                    REFERENCES demo_wallet_accounts (
                        account_id
                    )
                );

            CREATE INDEX IF NOT EXISTS
                ix_demo_withdrawal_recipients_owner_status
            ON demo_withdrawal_recipients (
                owner_account_id,
                status,
                created_at
            );

            CREATE TABLE IF NOT EXISTS
                demo_withdrawal_recipient_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recipient_id TEXT NOT NULL,
                    owner_account_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (
                        recipient_id
                    )
                    REFERENCES demo_withdrawal_recipients (
                        recipient_id
                    )
                    ON DELETE CASCADE
                );

            CREATE INDEX IF NOT EXISTS
                ix_demo_withdrawal_recipient_events_request
            ON demo_withdrawal_recipient_events (
                recipient_id,
                created_at,
                id
            );

            CREATE TABLE IF NOT EXISTS
                demo_withdrawal_destinations (
                    destination_id TEXT PRIMARY KEY,
                    owner_account_id TEXT NOT NULL,
                    recipient_id TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    chain TEXT NOT NULL,
                    address TEXT NOT NULL,
                    memo TEXT NOT NULL,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    verification_method TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    approved_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (
                        owner_account_id,
                        currency,
                        chain,
                        address,
                        memo
                    ),
                    FOREIGN KEY (
                        owner_account_id
                    )
                    REFERENCES demo_wallet_accounts (
                        account_id
                    ),
                    FOREIGN KEY (
                        recipient_id
                    )
                    REFERENCES demo_withdrawal_recipients (
                        recipient_id
                    ),
                    FOREIGN KEY (
                        currency,
                        chain
                    )
                    REFERENCES demo_withdrawal_policies (
                        currency,
                        chain
                    )
                );

            CREATE INDEX IF NOT EXISTS
                ix_demo_withdrawal_destinations_owner_status
            ON demo_withdrawal_destinations (
                owner_account_id,
                status,
                currency,
                chain,
                created_at
            );

            CREATE INDEX IF NOT EXISTS
                ix_demo_withdrawal_destinations_recipient
            ON demo_withdrawal_destinations (
                recipient_id,
                created_at
            );

            CREATE TABLE IF NOT EXISTS
                demo_withdrawal_destination_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    destination_id TEXT NOT NULL,
                    owner_account_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (
                        destination_id
                    )
                    REFERENCES demo_withdrawal_destinations (
                        destination_id
                    )
                    ON DELETE CASCADE
                );

            CREATE INDEX IF NOT EXISTS
                ix_demo_withdrawal_destination_events_request
            ON demo_withdrawal_destination_events (
                destination_id,
                created_at,
                id
            );
            """
        )

    def _feature_tables_empty(
        self,
        db: sqlite3.Connection,
    ) -> bool:
        tables = (
            "demo_withdrawal_policies",
            "demo_withdrawal_recipients",
            "demo_withdrawal_recipient_events",
            "demo_withdrawal_destinations",
            "demo_withdrawal_destination_events",
        )

        return not any(
            int(
                db.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            )
            for table
            in tables
        )

    def _insert_recipient_event(
        self,
        db: sqlite3.Connection,
        *,
        recipient_id: str,
        owner_account_id: str,
        username: str,
        action: str,
        from_status: str,
        to_status: str,
        reason: str,
        created_at: str,
    ) -> None:
        db.execute(
            """
            INSERT INTO demo_withdrawal_recipient_events (
                recipient_id,
                owner_account_id,
                username,
                action,
                from_status,
                to_status,
                reason,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recipient_id,
                owner_account_id,
                username,
                action,
                from_status,
                to_status,
                reason,
                _json(
                    {
                        "demo": True,
                        "gate_read_performed": False,
                        "gate_write_performed": False,
                    }
                ),
                created_at,
            ),
        )

    def _insert_destination_event(
        self,
        db: sqlite3.Connection,
        *,
        destination_id: str,
        owner_account_id: str,
        username: str,
        action: str,
        from_status: str,
        to_status: str,
        reason: str,
        created_at: str,
    ) -> None:
        db.execute(
            """
            INSERT INTO demo_withdrawal_destination_events (
                destination_id,
                owner_account_id,
                username,
                action,
                from_status,
                to_status,
                reason,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                destination_id,
                owner_account_id,
                username,
                action,
                from_status,
                to_status,
                reason,
                _json(
                    {
                        "demo": True,
                        "automatic_demo_approval": True,
                        "gate_read_performed": False,
                        "gate_write_performed": False,
                    }
                ),
                created_at,
            ),
        )

    def _insert_seed(
        self,
        db: sqlite3.Connection,
    ) -> None:
        db.executemany(
            """
            INSERT INTO demo_withdrawal_policies (
                currency,
                chain,
                network_name,
                withdraw_enabled,
                requires_memo,
                decimal_places,
                minimum_withdrawal,
                maximum_per_withdrawal,
                daily_limit,
                fixed_fee,
                sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item["currency"],
                    item["chain"],
                    item["network_name"],
                    int(
                        item["withdraw_enabled"]
                    ),
                    int(
                        item["requires_memo"]
                    ),
                    item["decimal_places"],
                    item["minimum_withdrawal"],
                    item["maximum_per_withdrawal"],
                    item["daily_limit"],
                    item["fixed_fee"],
                    item["sort_order"],
                )
                for item
                in _SEED_POLICIES
            ],
        )

        for item in _SEED_RECIPIENTS:
            owner = _normalize_account_id(
                item["owner_account_id"]
            )

            address = _normalize_address(
                item["address"]
            )

            db.execute(
                """
                INSERT INTO demo_withdrawal_recipients (
                    recipient_id,
                    owner_account_id,
                    address,
                    address_key,
                    label,
                    status,
                    created_by,
                    archived_by,
                    archived_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["recipient_id"],
                    owner,
                    address,
                    _address_key(
                        address
                    ),
                    _normalize_label(
                        item["label"]
                    ),
                    "active",
                    item["created_by"],
                    "",
                    None,
                    DEMO_WITHDRAWAL_SEED_TIMESTAMP,
                    DEMO_WITHDRAWAL_SEED_TIMESTAMP,
                ),
            )

            self._insert_recipient_event(
                db,
                recipient_id=(
                    item["recipient_id"]
                ),
                owner_account_id=owner,
                username=item["created_by"],
                action="created",
                from_status="",
                to_status="active",
                reason=(
                    "Deterministic Demo withdrawal "
                    "recipient seed."
                ),
                created_at=(
                    DEMO_WITHDRAWAL_SEED_TIMESTAMP
                ),
            )

        for item in _SEED_DESTINATIONS:
            recipient = db.execute(
                """
                SELECT
                    owner_account_id,
                    address,
                    label
                FROM demo_withdrawal_recipients
                WHERE recipient_id = ?
                """,
                (
                    item["recipient_id"],
                ),
            ).fetchone()

            if recipient is None:
                raise DemoWalletStateError(
                    "Demo withdrawal seed destination "
                    "references a missing recipient"
                )

            owner = _normalize_account_id(
                item["owner_account_id"]
            )

            if (
                recipient["owner_account_id"]
                != owner
            ):
                raise DemoWalletStateError(
                    "Demo withdrawal seed recipient "
                    "owner mismatch"
                )

            currency = _normalize_currency(
                item["currency"]
            )

            chain = _normalize_chain(
                item["chain"]
            )

            policy = db.execute(
                """
                SELECT
                    withdraw_enabled,
                    requires_memo
                FROM demo_withdrawal_policies
                WHERE currency = ?
                  AND chain = ?
                """,
                (
                    currency,
                    chain,
                ),
            ).fetchone()

            if (
                policy is None
                or not bool(
                    policy[
                        "withdraw_enabled"
                    ]
                )
            ):
                raise DemoWalletStateError(
                    "Demo withdrawal seed destination "
                    "references a disabled policy"
                )

            network = db.execute(
                """
                SELECT withdraw_enabled
                FROM demo_deposit_addresses
                WHERE account_id = ?
                  AND currency = ?
                  AND network = ?
                """,
                (
                    owner,
                    currency,
                    chain,
                ),
            ).fetchone()

            if (
                network is None
                or not bool(
                    network[
                        "withdraw_enabled"
                    ]
                )
            ):
                raise DemoWalletStateError(
                    "Demo withdrawal policy does not match "
                    "the existing synthetic Wallet network"
                )

            memo = _normalize_memo(
                item["memo"]
            )

            db.execute(
                """
                INSERT INTO demo_withdrawal_destinations (
                    destination_id,
                    owner_account_id,
                    recipient_id,
                    currency,
                    chain,
                    address,
                    memo,
                    label,
                    status,
                    source,
                    verification_method,
                    created_by,
                    approved_by,
                    approved_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    item["destination_id"],
                    owner,
                    item["recipient_id"],
                    currency,
                    chain,
                    recipient["address"],
                    memo,
                    recipient["label"],
                    "approved",
                    "demo_recipient",
                    "demo_auto_approved",
                    "demo",
                    "demo:auto",
                    DEMO_WITHDRAWAL_SEED_TIMESTAMP,
                    DEMO_WITHDRAWAL_SEED_TIMESTAMP,
                    DEMO_WITHDRAWAL_SEED_TIMESTAMP,
                ),
            )

            self._insert_destination_event(
                db,
                destination_id=(
                    item["destination_id"]
                ),
                owner_account_id=owner,
                username="demo",
                action="demo_auto_approved",
                from_status="",
                to_status="approved",
                reason=(
                    "Deterministic Demo withdrawal "
                    "destination seed."
                ),
                created_at=(
                    DEMO_WITHDRAWAL_SEED_TIMESTAMP
                ),
            )

        db.executemany(
            """
            INSERT INTO demo_wallet_meta (
                key,
                value
            )
            VALUES (?, ?)
            """,
            (
                (
                    "withdrawal_seed_version",
                    DEMO_WITHDRAWAL_SEED_VERSION,
                ),
                (
                    "withdrawal_seed_timestamp",
                    DEMO_WITHDRAWAL_SEED_TIMESTAMP,
                ),
            ),
        )

    def ensure_seeded(
        self,
    ) -> bool:
        self.wallet_store.ensure_seeded()

        db = self._connect()

        try:
            db.execute(
                "BEGIN IMMEDIATE"
            )

            self._initialize_schema(
                db
            )

            marker = db.execute(
                """
                SELECT value
                FROM demo_wallet_meta
                WHERE key = 'withdrawal_seed_version'
                """
            ).fetchone()

            if marker is not None:
                version = str(
                    marker["value"]
                )

                if (
                    version
                    != DEMO_WITHDRAWAL_SEED_VERSION
                ):
                    raise DemoWalletStateError(
                        "Unsupported Demo withdrawal "
                        f"seed version: {version}"
                    )

                db.commit()
                return False

            if not self._feature_tables_empty(
                db
            ):
                raise DemoWalletStateError(
                    "Demo withdrawal seed metadata is "
                    "missing from non-empty state"
                )

            self._insert_seed(
                db
            )

            db.commit()

            return True

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

    @contextmanager
    def _reader(
        self,
    ) -> Iterator[
        sqlite3.Connection
    ]:
        self.ensure_seeded()

        db = self._connect()

        try:
            yield db

        finally:
            db.close()

    @contextmanager
    def _writer(
        self,
    ) -> Iterator[
        sqlite3.Connection
    ]:
        self.ensure_seeded()

        db = self._connect()

        try:
            db.execute(
                "BEGIN IMMEDIATE"
            )

            yield db

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

    @staticmethod
    def _policy_row(
        row: sqlite3.Row,
    ) -> dict[
        str,
        Any,
    ]:
        return {
            "currency":
                row["currency"],
            "chain":
                row["chain"],
            "network_name":
                row["network_name"],
            "withdraw_enabled":
                bool(
                    row[
                        "withdraw_enabled"
                    ]
                ),
            "requires_memo":
                bool(
                    row[
                        "requires_memo"
                    ]
                ),
            "decimal_places":
                int(
                    row[
                        "decimal_places"
                    ]
                ),
            "minimum_withdrawal":
                row[
                    "minimum_withdrawal"
                ],
            "maximum_per_withdrawal":
                row[
                    "maximum_per_withdrawal"
                ],
            "daily_limit":
                row[
                    "daily_limit"
                ],
            "fixed_fee":
                row["fixed_fee"],
            "source":
                "demo",
        }

    @staticmethod
    def _recipient_row(
        row: sqlite3.Row,
    ) -> dict[
        str,
        Any,
    ]:
        return {
            "recipient_id":
                row["recipient_id"],
            "owner_account_id":
                row[
                    "owner_account_id"
                ],
            "address":
                row["address"],
            "label":
                row["label"],
            "status":
                row["status"],
            "created_by":
                row["created_by"],
            "archived_by":
                row["archived_by"],
            "archived_at":
                row["archived_at"],
            "created_at":
                row["created_at"],
            "updated_at":
                row["updated_at"],
            "source":
                "demo",
        }

    @staticmethod
    def _destination_row(
        row: sqlite3.Row,
    ) -> dict[
        str,
        Any,
    ]:
        return {
            "destination_id":
                row[
                    "destination_id"
                ],
            "owner_account_id":
                row[
                    "owner_account_id"
                ],
            "recipient_id":
                row[
                    "recipient_id"
                ],
            "currency":
                row["currency"],
            "chain":
                row["chain"],
            "address":
                row["address"],
            "memo":
                row["memo"],
            "label":
                row["label"],
            "status":
                row["status"],
            "source":
                row["source"],
            "verification_method":
                row[
                    "verification_method"
                ],
            "created_by":
                row["created_by"],
            "approved_by":
                row["approved_by"],
            "approved_at":
                row["approved_at"],
            "created_at":
                row["created_at"],
            "updated_at":
                row["updated_at"],
            "simulation":
                True,
            "gate_read_performed":
                False,
            "gate_write_performed":
                False,
        }

    def list_policies(
        self,
        currency: str | None = None,
    ) -> list[
        dict[
            str,
            Any,
        ]
    ]:
        symbol = (
            _normalize_currency(
                currency
            )
            if currency
            else None
        )

        with self._reader() as db:
            rows = db.execute(
                """
                SELECT
                    currency,
                    chain,
                    network_name,
                    withdraw_enabled,
                    requires_memo,
                    decimal_places,
                    minimum_withdrawal,
                    maximum_per_withdrawal,
                    daily_limit,
                    fixed_fee,
                    sort_order
                FROM demo_withdrawal_policies
                ORDER BY
                    currency ASC,
                    sort_order ASC,
                    chain ASC
                """
            ).fetchall()

        result = []

        for row in rows:
            if (
                symbol is not None
                and row["currency"]
                != symbol
            ):
                continue

            result.append(
                self._policy_row(
                    row
                )
            )

        return result

    def capabilities(
        self,
        *,
        account_id: str,
        currency: str,
    ) -> dict[
        str,
        Any,
    ]:
        owner = _normalize_account_id(
            account_id
        )

        symbol = _normalize_currency(
            currency
        )

        with self._reader() as db:
            asset = db.execute(
                """
                SELECT
                    available,
                    locked
                FROM demo_wallet_assets
                WHERE account_id = ?
                  AND currency = ?
                """,
                (
                    owner,
                    symbol,
                ),
            ).fetchone()

            if asset is None:
                raise KeyError(
                    "Demo withdrawal asset not found"
                )

            rows = db.execute(
                """
                SELECT
                    p.currency,
                    p.chain,
                    p.network_name,
                    p.withdraw_enabled,
                    p.requires_memo,
                    p.decimal_places,
                    p.minimum_withdrawal,
                    p.maximum_per_withdrawal,
                    p.daily_limit,
                    p.fixed_fee,
                    p.sort_order
                FROM demo_withdrawal_policies AS p
                INNER JOIN demo_deposit_addresses AS d
                    ON d.account_id = ?
                   AND d.currency = p.currency
                   AND d.network = p.chain
                WHERE p.currency = ?
                  AND d.withdraw_enabled = 1
                ORDER BY
                    p.sort_order ASC,
                    p.chain ASC
                """,
                (
                    owner,
                    symbol,
                ),
            ).fetchall()

        return {
            "source":
                "demo",
            "simulation":
                True,
            "account_id":
                owner,
            "currency":
                symbol,
            "available":
                asset["available"],
            "locked":
                asset["locked"],
            "withdrawal_funding_available":
                asset["available"],
            "chains": [
                self._policy_row(
                    row
                )
                for row
                in rows
            ],
            "demo_withdrawals_enabled":
                True,
            "withdrawals_enabled":
                False,
            "gate_read_performed":
                False,
            "gate_write_performed":
                False,
        }

    def create_recipient(
        self,
        *,
        owner_account_id: str,
        address: str,
        label: str = "",
        username: str = "demo",
        occurred_at: str | None = None,
    ) -> dict[
        str,
        Any,
    ]:
        owner = _normalize_account_id(
            owner_account_id
        )

        normalized_address = (
            _normalize_address(
                address
            )
        )

        address_key = _address_key(
            normalized_address
        )

        normalized_label = (
            _normalize_label(
                label
            )
        )

        normalized_username = (
            _normalize_username(
                username
            )
        )

        now = _now(
            occurred_at
        )

        with self._writer() as db:
            existing = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_recipients
                WHERE owner_account_id = ?
                  AND address_key = ?
                """,
                (
                    owner,
                    address_key,
                ),
            ).fetchone()

            if existing is not None:
                return {
                    "created": False,
                    "local_write_performed": False,
                    "gate_write_performed": False,
                    "item":
                        self._recipient_row(
                            existing
                        ),
                }

            recipient_id = _recipient_id(
                owner,
                address_key,
            )

            db.execute(
                """
                INSERT INTO demo_withdrawal_recipients (
                    recipient_id,
                    owner_account_id,
                    address,
                    address_key,
                    label,
                    status,
                    created_by,
                    archived_by,
                    archived_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recipient_id,
                    owner,
                    normalized_address,
                    address_key,
                    normalized_label,
                    "active",
                    normalized_username,
                    "",
                    None,
                    now,
                    now,
                ),
            )

            self._insert_recipient_event(
                db,
                recipient_id=recipient_id,
                owner_account_id=owner,
                username=(
                    normalized_username
                ),
                action="created",
                from_status="",
                to_status="active",
                reason="",
                created_at=now,
            )

            row = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_recipients
                WHERE recipient_id = ?
                """,
                (
                    recipient_id,
                ),
            ).fetchone()

        assert row is not None

        return {
            "created": True,
            "local_write_performed": True,
            "gate_write_performed": False,
            "item":
                self._recipient_row(
                    row
                ),
        }

    def list_recipients(
        self,
        *,
        owner_account_ids: set[str] | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[
        dict[
            str,
            Any,
        ]
    ]:
        if (
            limit < 1
            or limit > 500
        ):
            raise ValueError(
                "Demo withdrawal recipient limit "
                "must be between 1 and 500"
            )

        scope = _normalize_account_scope(
            owner_account_ids
        )

        normalized_status = (
            str(
                status or ""
            ).strip().lower()
            or None
        )

        with self._reader() as db:
            rows = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_recipients
                ORDER BY
                    created_at DESC,
                    recipient_id ASC
                """
            ).fetchall()

        result = []

        for row in rows:
            if (
                scope is not None
                and row[
                    "owner_account_id"
                ] not in scope
            ):
                continue

            if (
                normalized_status
                is not None
                and row["status"]
                != normalized_status
            ):
                continue

            result.append(
                self._recipient_row(
                    row
                )
            )

            if len(result) >= limit:
                break

        return result

    def get_recipient(
        self,
        recipient_id: str,
        *,
        owner_account_ids: set[str] | None = None,
    ) -> dict[
        str,
        Any,
    ]:
        scope = _normalize_account_scope(
            owner_account_ids
        )

        with self._reader() as db:
            row = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_recipients
                WHERE recipient_id = ?
                """,
                (
                    str(
                        recipient_id
                        or ""
                    ).strip(),
                ),
            ).fetchone()

        if (
            row is None
            or (
                scope is not None
                and row[
                    "owner_account_id"
                ] not in scope
            )
        ):
            raise KeyError(
                "Demo withdrawal recipient not found"
            )

        return self._recipient_row(
            row
        )

    def list_recipient_events(
        self,
        recipient_id: str,
    ) -> list[
        dict[
            str,
            Any,
        ]
    ]:
        with self._reader() as db:
            rows = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_recipient_events
                WHERE recipient_id = ?
                ORDER BY
                    created_at ASC,
                    id ASC
                """,
                (
                    str(
                        recipient_id
                        or ""
                    ).strip(),
                ),
            ).fetchall()

        return [
            {
                "id":
                    int(row["id"]),
                "recipient_id":
                    row["recipient_id"],
                "owner_account_id":
                    row[
                        "owner_account_id"
                    ],
                "username":
                    row["username"],
                "action":
                    row["action"],
                "from_status":
                    row["from_status"],
                "to_status":
                    row["to_status"],
                "reason":
                    row["reason"],
                "metadata":
                    _load_json(
                        row[
                            "metadata_json"
                        ]
                    ),
                "created_at":
                    row["created_at"],
            }
            for row
            in rows
        ]

    def rename_recipient(
        self,
        *,
        recipient_id: str,
        label: str,
        username: str = "demo",
        occurred_at: str | None = None,
    ) -> dict[
        str,
        Any,
    ]:
        normalized_label = (
            _normalize_label(
                label
            )
        )

        normalized_username = (
            _normalize_username(
                username
            )
        )

        now = _now(
            occurred_at
        )

        with self._writer() as db:
            row = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_recipients
                WHERE recipient_id = ?
                """,
                (
                    str(
                        recipient_id
                        or ""
                    ).strip(),
                ),
            ).fetchone()

            if row is None:
                raise KeyError(
                    "Demo withdrawal recipient not found"
                )

            if row["label"] == normalized_label:
                return {
                    "changed": False,
                    "local_write_performed": False,
                    "gate_write_performed": False,
                    "item":
                        self._recipient_row(
                            row
                        ),
                }

            db.execute(
                """
                UPDATE demo_withdrawal_recipients
                SET
                    label = ?,
                    updated_at = ?
                WHERE recipient_id = ?
                """,
                (
                    normalized_label,
                    now,
                    row[
                        "recipient_id"
                    ],
                ),
            )

            self._insert_recipient_event(
                db,
                recipient_id=(
                    row["recipient_id"]
                ),
                owner_account_id=(
                    row[
                        "owner_account_id"
                    ]
                ),
                username=(
                    normalized_username
                ),
                action="renamed",
                from_status=(
                    row["status"]
                ),
                to_status=(
                    row["status"]
                ),
                reason="",
                created_at=now,
            )

            updated = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_recipients
                WHERE recipient_id = ?
                """,
                (
                    row["recipient_id"],
                ),
            ).fetchone()

        assert updated is not None

        return {
            "changed": True,
            "local_write_performed": True,
            "gate_write_performed": False,
            "item":
                self._recipient_row(
                    updated
                ),
        }

    def _set_recipient_status(
        self,
        *,
        recipient_id: str,
        status: str,
        username: str,
        reason: str,
        occurred_at: str | None,
    ) -> dict[
        str,
        Any,
    ]:
        if status not in {
            "active",
            "archived",
        }:
            raise ValueError(
                "Invalid Demo recipient status"
            )

        normalized_username = (
            _normalize_username(
                username
            )
        )

        normalized_reason = str(
            reason or ""
        ).strip()

        if len(normalized_reason) > 1000:
            raise ValueError(
                "Demo withdrawal recipient reason "
                "is too long"
            )

        now = _now(
            occurred_at
        )

        with self._writer() as db:
            row = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_recipients
                WHERE recipient_id = ?
                """,
                (
                    str(
                        recipient_id
                        or ""
                    ).strip(),
                ),
            ).fetchone()

            if row is None:
                raise KeyError(
                    "Demo withdrawal recipient not found"
                )

            if row["status"] == status:
                return {
                    "changed": False,
                    "local_write_performed": False,
                    "gate_write_performed": False,
                    "item":
                        self._recipient_row(
                            row
                        ),
                }

            if status == "archived":
                archived_by = (
                    normalized_username
                )
                archived_at = now
                action = "archived"

            else:
                archived_by = ""
                archived_at = None
                action = "restored"

            db.execute(
                """
                UPDATE demo_withdrawal_recipients
                SET
                    status = ?,
                    archived_by = ?,
                    archived_at = ?,
                    updated_at = ?
                WHERE recipient_id = ?
                """,
                (
                    status,
                    archived_by,
                    archived_at,
                    now,
                    row[
                        "recipient_id"
                    ],
                ),
            )

            self._insert_recipient_event(
                db,
                recipient_id=(
                    row["recipient_id"]
                ),
                owner_account_id=(
                    row[
                        "owner_account_id"
                    ]
                ),
                username=(
                    normalized_username
                ),
                action=action,
                from_status=(
                    row["status"]
                ),
                to_status=status,
                reason=(
                    normalized_reason
                ),
                created_at=now,
            )

            updated = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_recipients
                WHERE recipient_id = ?
                """,
                (
                    row["recipient_id"],
                ),
            ).fetchone()

        assert updated is not None

        return {
            "changed": True,
            "local_write_performed": True,
            "gate_write_performed": False,
            "item":
                self._recipient_row(
                    updated
                ),
        }

    def archive_recipient(
        self,
        *,
        recipient_id: str,
        username: str = "demo",
        reason: str = "",
        occurred_at: str | None = None,
    ) -> dict[
        str,
        Any,
    ]:
        return self._set_recipient_status(
            recipient_id=recipient_id,
            status="archived",
            username=username,
            reason=reason,
            occurred_at=occurred_at,
        )

    def restore_recipient(
        self,
        *,
        recipient_id: str,
        username: str = "demo",
        reason: str = "",
        occurred_at: str | None = None,
    ) -> dict[
        str,
        Any,
    ]:
        return self._set_recipient_status(
            recipient_id=recipient_id,
            status="active",
            username=username,
            reason=reason,
            occurred_at=occurred_at,
        )

    def create_destination_from_recipient(
        self,
        *,
        recipient_id: str,
        currency: str,
        chain: str,
        memo: str = "",
        username: str = "demo",
        occurred_at: str | None = None,
    ) -> dict[
        str,
        Any,
    ]:
        symbol = _normalize_currency(
            currency
        )

        network = _normalize_chain(
            chain
        )

        normalized_memo = (
            _normalize_memo(
                memo
            )
        )

        normalized_username = (
            _normalize_username(
                username
            )
        )

        now = _now(
            occurred_at
        )

        with self._writer() as db:
            recipient = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_recipients
                WHERE recipient_id = ?
                """,
                (
                    str(
                        recipient_id
                        or ""
                    ).strip(),
                ),
            ).fetchone()

            if recipient is None:
                raise KeyError(
                    "Demo withdrawal recipient not found"
                )

            if (
                recipient["status"]
                != "active"
            ):
                raise DemoWithdrawalRegistryError(
                    "Demo withdrawal recipient "
                    "is not active"
                )

            owner = recipient[
                "owner_account_id"
            ]

            policy = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_policies
                WHERE currency = ?
                  AND chain = ?
                """,
                (
                    symbol,
                    network,
                ),
            ).fetchone()

            if (
                policy is None
                or not bool(
                    policy[
                        "withdraw_enabled"
                    ]
                )
            ):
                raise DemoWithdrawalRegistryError(
                    "Demo withdrawal network "
                    "is not available"
                )

            network_row = db.execute(
                """
                SELECT withdraw_enabled
                FROM demo_deposit_addresses
                WHERE account_id = ?
                  AND currency = ?
                  AND network = ?
                """,
                (
                    owner,
                    symbol,
                    network,
                ),
            ).fetchone()

            if (
                network_row is None
                or not bool(
                    network_row[
                        "withdraw_enabled"
                    ]
                )
            ):
                raise DemoWithdrawalRegistryError(
                    "Demo Wallet does not expose "
                    "this withdrawal network"
                )

            if (
                bool(
                    policy[
                        "requires_memo"
                    ]
                )
                and not normalized_memo
            ):
                raise DemoWithdrawalRegistryError(
                    "Demo withdrawal network "
                    "requires a memo"
                )

            existing = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_destinations
                WHERE owner_account_id = ?
                  AND currency = ?
                  AND chain = ?
                  AND address = ?
                  AND memo = ?
                """,
                (
                    owner,
                    symbol,
                    network,
                    recipient["address"],
                    normalized_memo,
                ),
            ).fetchone()

            if existing is not None:
                if (
                    existing[
                        "recipient_id"
                    ]
                    != recipient[
                        "recipient_id"
                    ]
                ):
                    raise (
                        DemoWithdrawalRegistryConflict(
                            "Equivalent Demo withdrawal "
                            "destination belongs to another "
                            "recipient"
                        )
                    )

                return {
                    "created": False,
                    "linked": True,
                    "auto_approved": (
                        existing["status"]
                        == "approved"
                    ),
                    "local_write_performed": False,
                    "gate_write_performed": False,
                    "item":
                        self._destination_row(
                            existing
                        ),
                }

            destination_id = (
                _destination_id(
                    owner_account_id=owner,
                    currency=symbol,
                    chain=network,
                    address=(
                        recipient[
                            "address"
                        ]
                    ),
                    memo=normalized_memo,
                )
            )

            db.execute(
                """
                INSERT INTO demo_withdrawal_destinations (
                    destination_id,
                    owner_account_id,
                    recipient_id,
                    currency,
                    chain,
                    address,
                    memo,
                    label,
                    status,
                    source,
                    verification_method,
                    created_by,
                    approved_by,
                    approved_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    destination_id,
                    owner,
                    recipient[
                        "recipient_id"
                    ],
                    symbol,
                    network,
                    recipient["address"],
                    normalized_memo,
                    recipient["label"],
                    "approved",
                    "demo_recipient",
                    "demo_auto_approved",
                    normalized_username,
                    "demo:auto",
                    now,
                    now,
                    now,
                ),
            )

            self._insert_destination_event(
                db,
                destination_id=(
                    destination_id
                ),
                owner_account_id=owner,
                username=(
                    normalized_username
                ),
                action="demo_auto_approved",
                from_status="",
                to_status="approved",
                reason=(
                    "Demo destinations are "
                    "automatically approved only "
                    "inside isolated Demo state."
                ),
                created_at=now,
            )

            row = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_destinations
                WHERE destination_id = ?
                """,
                (
                    destination_id,
                ),
            ).fetchone()

        assert row is not None

        return {
            "created": True,
            "linked": True,
            "auto_approved": True,
            "local_write_performed": True,
            "gate_write_performed": False,
            "item":
                self._destination_row(
                    row
                ),
        }

    def list_destinations(
        self,
        *,
        owner_account_ids: set[str] | None = None,
        status: str | None = None,
        currency: str | None = None,
        limit: int = 100,
    ) -> list[
        dict[
            str,
            Any,
        ]
    ]:
        if (
            limit < 1
            or limit > 500
        ):
            raise ValueError(
                "Demo withdrawal destination limit "
                "must be between 1 and 500"
            )

        scope = _normalize_account_scope(
            owner_account_ids
        )

        normalized_status = (
            str(
                status or ""
            ).strip().lower()
            or None
        )

        symbol = (
            _normalize_currency(
                currency
            )
            if currency
            else None
        )

        with self._reader() as db:
            rows = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_destinations
                ORDER BY
                    created_at DESC,
                    destination_id ASC
                """
            ).fetchall()

        result = []

        for row in rows:
            if (
                scope is not None
                and row[
                    "owner_account_id"
                ] not in scope
            ):
                continue

            if (
                normalized_status
                is not None
                and row["status"]
                != normalized_status
            ):
                continue

            if (
                symbol is not None
                and row["currency"]
                != symbol
            ):
                continue

            result.append(
                self._destination_row(
                    row
                )
            )

            if len(result) >= limit:
                break

        return result

    def get_destination(
        self,
        destination_id: str,
        *,
        owner_account_ids: set[str] | None = None,
    ) -> dict[
        str,
        Any,
    ]:
        scope = _normalize_account_scope(
            owner_account_ids
        )

        with self._reader() as db:
            row = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_destinations
                WHERE destination_id = ?
                """,
                (
                    str(
                        destination_id
                        or ""
                    ).strip(),
                ),
            ).fetchone()

        if (
            row is None
            or (
                scope is not None
                and row[
                    "owner_account_id"
                ] not in scope
            )
        ):
            raise KeyError(
                "Demo withdrawal destination not found"
            )

        return self._destination_row(
            row
        )

    def list_destination_events(
        self,
        destination_id: str,
    ) -> list[
        dict[
            str,
            Any,
        ]
    ]:
        with self._reader() as db:
            rows = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_destination_events
                WHERE destination_id = ?
                ORDER BY
                    created_at ASC,
                    id ASC
                """,
                (
                    str(
                        destination_id
                        or ""
                    ).strip(),
                ),
            ).fetchall()

        return [
            {
                "id":
                    int(row["id"]),
                "destination_id":
                    row[
                        "destination_id"
                    ],
                "owner_account_id":
                    row[
                        "owner_account_id"
                    ],
                "username":
                    row["username"],
                "action":
                    row["action"],
                "from_status":
                    row["from_status"],
                "to_status":
                    row["to_status"],
                "reason":
                    row["reason"],
                "metadata":
                    _load_json(
                        row[
                            "metadata_json"
                        ]
                    ),
                "created_at":
                    row["created_at"],
            }
            for row
            in rows
        ]
