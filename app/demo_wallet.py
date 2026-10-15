from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from .demo_auth import DEMO_ACCOUNT_IDS


DEMO_WALLET_SEED_VERSION = "1"

# Deliberately fixed so a fresh Demo database produces exactly
# the same state every time. API presentation can later use a
# current response timestamp without changing repository state.
DEMO_WALLET_SEED_TIMESTAMP = (
    "2026-10-15T12:00:00+00:00"
)


class DemoWalletStateError(
    RuntimeError
):
    """Demo Wallet state is inconsistent or incompatible."""


_SEED_ACCOUNTS = (
    {
        "account_id":
            "demo-wallet-1",
        "display_name":
            "Demo Growth Wallet",
        "sort_order":
            1,
        "quant_value_usdt":
            "8500",
        "bot_initial_capital":
            "8000",
        "bot_current_value":
            "8500",
        "bot_pnl":
            "500",
        "running_bots":
            3,
        "tracked_bots":
            4,
    },
    {
        "account_id":
            "demo-wallet-2",
        "display_name":
            "Demo Treasury Wallet",
        "sort_order":
            2,
        "quant_value_usdt":
            "15000",
        "bot_initial_capital":
            "14250",
        "bot_current_value":
            "15000",
        "bot_pnl":
            "750",
        "running_bots":
            2,
        "tracked_bots":
            3,
    },
)


_SEED_CURRENCIES = (
    {
        "currency":
            "USDT",
        "name":
            "Tether",
        "main_chain":
            "ETH",
        "trade_disabled":
            0,
        "sort_order":
            1,
    },
    {
        "currency":
            "EQTY",
        "name":
            "EQTY",
        "main_chain":
            "BASE",
        "trade_disabled":
            0,
        "sort_order":
            2,
    },
    {
        "currency":
            "BTC",
        "name":
            "Bitcoin",
        "main_chain":
            "BTC",
        "trade_disabled":
            0,
        "sort_order":
            3,
    },
    {
        "currency":
            "ETH",
        "name":
            "Ethereum",
        "main_chain":
            "ETH",
        "trade_disabled":
            0,
        "sort_order":
            4,
    },
)


_SEED_ASSETS = (
    # Demo Growth Wallet
    (
        "demo-wallet-1",
        "USDT",
        "12500",
        "250",
        "1",
    ),
    (
        "demo-wallet-1",
        "EQTY",
        "750000",
        "100000",
        "0.0042",
    ),
    (
        "demo-wallet-1",
        "BTC",
        "0.018",
        "0.002",
        "65000",
    ),
    (
        "demo-wallet-1",
        "ETH",
        "0.75",
        "0.05",
        "3500",
    ),

    # Demo Treasury Wallet
    (
        "demo-wallet-2",
        "USDT",
        "42000",
        "1000",
        "1",
    ),
    (
        "demo-wallet-2",
        "EQTY",
        "2500000",
        "500000",
        "0.0042",
    ),
    (
        "demo-wallet-2",
        "BTC",
        "0.04",
        "0.005",
        "65000",
    ),
    (
        "demo-wallet-2",
        "ETH",
        "2.1",
        "0.2",
        "3500",
    ),
)


def _address_seed(
    account_id: str,
    suffix: str,
) -> str:
    # Intentionally not a routable blockchain address.
    return (
        "DEMO-ONLY-"
        + account_id.upper()
        + "-"
        + suffix
    )


_SEED_ADDRESSES = tuple(
    (
        account_id,
        currency,
        network,
        network_name,
        _address_seed(
            account_id,
            address_suffix,
        ),
        "",
        contract_address,
        minimum,
        confirmations,
        deposit_enabled,
        withdraw_enabled,
        requires_memo,
        decimal_places,
        sort_order,
    )
    for account_id in DEMO_ACCOUNT_IDS
    for (
        currency,
        network,
        network_name,
        address_suffix,
        contract_address,
        minimum,
        confirmations,
        deposit_enabled,
        withdraw_enabled,
        requires_memo,
        decimal_places,
        sort_order,
    )
    in (
        (
            "USDT",
            "ETH",
            "Ethereum",
            "USDT-ETH",
            (
                "0xdAC17F958D2ee523a220620"
                "6994597C13D831ec7"
            ),
            "1",
            12,
            1,
            1,
            0,
            "6",
            1,
        ),
        (
            "USDT",
            "TRX",
            "TRON",
            "USDT-TRX",
            "",
            "1",
            20,
            1,
            1,
            0,
            "6",
            2,
        ),
        (
            "EQTY",
            "BASE",
            "Base",
            "EQTY-BASE",
            "",
            "100",
            20,
            1,
            1,
            0,
            "18",
            1,
        ),
        (
            "BTC",
            "BTC",
            "Bitcoin",
            "BTC-BTC",
            "",
            "0.0001",
            2,
            1,
            1,
            0,
            "8",
            1,
        ),
        (
            "ETH",
            "ETH",
            "Ethereum",
            "ETH-ETH",
            "",
            "0.001",
            12,
            1,
            1,
            0,
            "18",
            1,
        ),
    )
)


def _deposit_raw(
    *,
    deposit_id: int,
    account_id: str,
    currency: str,
    chain: str,
    amount: str,
    status: str,
) -> str:
    return json.dumps(
        {
            "demo": True,
            "id": (
                f"demo-gate-"
                f"{deposit_id}"
            ),
            "account_id":
                account_id,
            "currency":
                currency,
            "chain":
                chain,
            "amount":
                amount,
            "status":
                status,
        },
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )


_SEED_DEPOSITS = (
    {
        "id":
            900001,
        "account_id":
            "demo-wallet-1",
        "currency":
            "USDT",
        "chain":
            "ETH",
        "amount":
            "750",
        "status":
            "DONE",
        "deposited_at":
            "2026-10-13T10:15:00+00:00",
    },
    {
        "id":
            900002,
        "account_id":
            "demo-wallet-1",
        "currency":
            "EQTY",
        "chain":
            "BASE",
        "amount":
            "125000",
        "status":
            "DONE",
        "deposited_at":
            "2026-10-12T14:25:00+00:00",
    },
    {
        "id":
            900003,
        "account_id":
            "demo-wallet-1",
        "currency":
            "BTC",
        "chain":
            "BTC",
        "amount":
            "0.005",
        "status":
            "PENDING",
        "deposited_at":
            "2026-10-15T08:05:00+00:00",
    },
    {
        "id":
            900101,
        "account_id":
            "demo-wallet-2",
        "currency":
            "USDT",
        "chain":
            "TRX",
        "amount":
            "5000",
        "status":
            "DONE",
        "deposited_at":
            "2026-10-11T17:40:00+00:00",
    },
    {
        "id":
            900102,
        "account_id":
            "demo-wallet-2",
        "currency":
            "ETH",
        "chain":
            "ETH",
        "amount":
            "1.25",
        "status":
            "DONE",
        "deposited_at":
            "2026-10-09T09:10:00+00:00",
    },
    {
        "id":
            900103,
        "account_id":
            "demo-wallet-2",
        "currency":
            "EQTY",
        "chain":
            "BASE",
        "amount":
            "500000",
        "status":
            "DONE",
        "deposited_at":
            "2026-10-07T12:30:00+00:00",
    },
)


def _normalize_account_id(
    value: str,
) -> str:
    account_id = str(
        value or ""
    ).strip().lower()

    if (
        account_id
        not in DEMO_ACCOUNT_IDS
    ):
        raise KeyError(
            "Unknown Demo Wallet account"
        )

    return account_id


def _normalize_currency(
    value: str,
) -> str:
    currency = str(
        value or ""
    ).strip().upper()

    if not currency:
        raise ValueError(
            "Demo Wallet currency is required"
        )

    return currency


def _normalize_network(
    value: str,
) -> str:
    network = str(
        value or ""
    ).strip().upper()

    if not network:
        raise ValueError(
            "Demo Wallet network is required"
        )

    return network


def _decimal_text(
    value: Decimal,
) -> str:
    return format(
        value,
        "f",
    )


class DemoWalletStore:
    """
    Dedicated isolated Demo Wallet repository.

    The caller supplies the same isolated SQLite path used by
    DemoSessionStore, but this class owns only demo_wallet_*
    tables.

    It deliberately has no dependency on production SQLAlchemy
    sessions, Gate account configuration, Gate transports,
    Treasury services, or HTTP routing.
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
            "PRAGMA foreign_keys = ON"
        )

        return connection

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

    def _initialize_schema(
        self,
        db: sqlite3.Connection,
    ) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS demo_wallet_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS demo_wallet_accounts (
                account_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                sort_order INTEGER NOT NULL,
                quant_value_usdt TEXT NOT NULL,
                bot_initial_capital TEXT NOT NULL,
                bot_current_value TEXT NOT NULL,
                bot_pnl TEXT NOT NULL,
                running_bots INTEGER NOT NULL,
                tracked_bots INTEGER NOT NULL,
                seeded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS demo_wallet_currencies (
                currency TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                main_chain TEXT NOT NULL,
                trade_disabled INTEGER NOT NULL,
                sort_order INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS demo_wallet_assets (
                account_id TEXT NOT NULL,
                currency TEXT NOT NULL,
                available TEXT NOT NULL,
                locked TEXT NOT NULL,
                price_usdt TEXT NOT NULL,
                PRIMARY KEY (
                    account_id,
                    currency
                ),
                FOREIGN KEY (
                    account_id
                )
                REFERENCES demo_wallet_accounts (
                    account_id
                )
                ON DELETE CASCADE,
                FOREIGN KEY (
                    currency
                )
                REFERENCES demo_wallet_currencies (
                    currency
                )
            );

            CREATE TABLE IF NOT EXISTS demo_deposit_addresses (
                account_id TEXT NOT NULL,
                currency TEXT NOT NULL,
                network TEXT NOT NULL,
                network_name TEXT NOT NULL,
                address TEXT NOT NULL,
                payment_id TEXT NOT NULL,
                contract_address TEXT NOT NULL,
                minimum_deposit_amount TEXT NOT NULL,
                min_confirmations INTEGER NOT NULL,
                deposit_enabled INTEGER NOT NULL,
                withdraw_enabled INTEGER NOT NULL,
                requires_memo INTEGER NOT NULL,
                decimal_places TEXT NOT NULL,
                sort_order INTEGER NOT NULL,
                PRIMARY KEY (
                    account_id,
                    currency,
                    network
                ),
                FOREIGN KEY (
                    account_id
                )
                REFERENCES demo_wallet_accounts (
                    account_id
                )
                ON DELETE CASCADE,
                FOREIGN KEY (
                    currency
                )
                REFERENCES demo_wallet_currencies (
                    currency
                )
            );

            CREATE TABLE IF NOT EXISTS demo_deposits (
                id INTEGER PRIMARY KEY,
                account_id TEXT NOT NULL,
                gate_deposit_id TEXT NOT NULL UNIQUE,
                txid TEXT NOT NULL,
                reference_id TEXT NOT NULL,
                currency TEXT NOT NULL,
                chain TEXT NOT NULL,
                amount TEXT NOT NULL,
                address TEXT NOT NULL,
                memo TEXT NOT NULL,
                status TEXT NOT NULL,
                refund_status TEXT NOT NULL,
                deposited_at TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                FOREIGN KEY (
                    account_id
                )
                REFERENCES demo_wallet_accounts (
                    account_id
                )
                ON DELETE CASCADE,
                FOREIGN KEY (
                    currency
                )
                REFERENCES demo_wallet_currencies (
                    currency
                )
            );

            CREATE INDEX IF NOT EXISTS
                ix_demo_deposits_account_time
            ON demo_deposits (
                account_id,
                deposited_at DESC,
                id DESC
            );
            """
        )

    def _assert_empty_without_seed_marker(
        self,
        db: sqlite3.Connection,
    ) -> None:
        tables = (
            "demo_wallet_accounts",
            "demo_wallet_currencies",
            "demo_wallet_assets",
            "demo_deposit_addresses",
            "demo_deposits",
        )

        populated = []

        for table in tables:
            count = int(
                db.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            )

            if count:
                populated.append(
                    table
                )

        if populated:
            raise DemoWalletStateError(
                "Demo Wallet seed metadata is missing "
                "from non-empty state: "
                + ", ".join(
                    populated
                )
            )

    def _insert_seed(
        self,
        db: sqlite3.Connection,
    ) -> None:
        account_ids = tuple(
            item[
                "account_id"
            ]
            for item
            in _SEED_ACCOUNTS
        )

        if (
            account_ids
            != DEMO_ACCOUNT_IDS
        ):
            raise DemoWalletStateError(
                "Demo Wallet seed accounts do not "
                "match Demo identity accounts"
            )

        db.executemany(
            """
            INSERT INTO demo_wallet_accounts (
                account_id,
                display_name,
                sort_order,
                quant_value_usdt,
                bot_initial_capital,
                bot_current_value,
                bot_pnl,
                running_bots,
                tracked_bots,
                seeded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item[
                        "account_id"
                    ],
                    item[
                        "display_name"
                    ],
                    item[
                        "sort_order"
                    ],
                    item[
                        "quant_value_usdt"
                    ],
                    item[
                        "bot_initial_capital"
                    ],
                    item[
                        "bot_current_value"
                    ],
                    item[
                        "bot_pnl"
                    ],
                    item[
                        "running_bots"
                    ],
                    item[
                        "tracked_bots"
                    ],
                    DEMO_WALLET_SEED_TIMESTAMP,
                )
                for item
                in _SEED_ACCOUNTS
            ],
        )

        db.executemany(
            """
            INSERT INTO demo_wallet_currencies (
                currency,
                name,
                main_chain,
                trade_disabled,
                sort_order
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    item[
                        "currency"
                    ],
                    item[
                        "name"
                    ],
                    item[
                        "main_chain"
                    ],
                    item[
                        "trade_disabled"
                    ],
                    item[
                        "sort_order"
                    ],
                )
                for item
                in _SEED_CURRENCIES
            ],
        )

        db.executemany(
            """
            INSERT INTO demo_wallet_assets (
                account_id,
                currency,
                available,
                locked,
                price_usdt
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            _SEED_ASSETS,
        )

        db.executemany(
            """
            INSERT INTO demo_deposit_addresses (
                account_id,
                currency,
                network,
                network_name,
                address,
                payment_id,
                contract_address,
                minimum_deposit_amount,
                min_confirmations,
                deposit_enabled,
                withdraw_enabled,
                requires_memo,
                decimal_places,
                sort_order
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            _SEED_ADDRESSES,
        )

        for item in _SEED_DEPOSITS:
            account_id = item[
                "account_id"
            ]

            currency = item[
                "currency"
            ]

            chain = item[
                "chain"
            ]

            address_row = db.execute(
                """
                SELECT
                    address,
                    payment_id
                FROM demo_deposit_addresses
                WHERE account_id = ?
                  AND currency = ?
                  AND network = ?
                """,
                (
                    account_id,
                    currency,
                    chain,
                ),
            ).fetchone()

            if address_row is None:
                raise DemoWalletStateError(
                    "Demo deposit seed references "
                    "a missing Demo address"
                )

            deposit_id = int(
                item[
                    "id"
                ]
            )

            gate_deposit_id = (
                f"demo-gate-{deposit_id}"
            )

            txid = (
                f"DEMO-TX-{deposit_id}"
            )

            deposited_at = str(
                item[
                    "deposited_at"
                ]
            )

            raw_json = _deposit_raw(
                deposit_id=deposit_id,
                account_id=account_id,
                currency=currency,
                chain=chain,
                amount=str(
                    item[
                        "amount"
                    ]
                ),
                status=str(
                    item[
                        "status"
                    ]
                ),
            )

            db.execute(
                """
                INSERT INTO demo_deposits (
                    id,
                    account_id,
                    gate_deposit_id,
                    txid,
                    reference_id,
                    currency,
                    chain,
                    amount,
                    address,
                    memo,
                    status,
                    refund_status,
                    deposited_at,
                    first_seen_at,
                    last_seen_at,
                    updated_at,
                    raw_json
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    deposit_id,
                    account_id,
                    gate_deposit_id,
                    txid,
                    "",
                    currency,
                    chain,
                    str(
                        item[
                            "amount"
                        ]
                    ),
                    address_row[
                        "address"
                    ],
                    address_row[
                        "payment_id"
                    ],
                    str(
                        item[
                            "status"
                        ]
                    ),
                    "",
                    deposited_at,
                    deposited_at,
                    deposited_at,
                    deposited_at,
                    raw_json,
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
                    "seed_version",
                    DEMO_WALLET_SEED_VERSION,
                ),
                (
                    "seed_timestamp",
                    DEMO_WALLET_SEED_TIMESTAMP,
                ),
            ),
        )

    def ensure_seeded(
        self,
    ) -> bool:
        """
        Create schema and deterministic seed once.

        Returns True only for the initial seed. Existing matching
        state is left untouched so later simulated mutations will
        survive subsequent requests.

        Unknown seed versions fail closed instead of destructively
        replacing state.
        """

        db = self._connect()

        try:
            db.execute(
                "BEGIN IMMEDIATE"
            )

            self._initialize_schema(
                db
            )

            version_row = db.execute(
                """
                SELECT value
                FROM demo_wallet_meta
                WHERE key = 'seed_version'
                """
            ).fetchone()

            if version_row is not None:
                version = str(
                    version_row[
                        "value"
                    ]
                )

                if (
                    version
                    != DEMO_WALLET_SEED_VERSION
                ):
                    raise DemoWalletStateError(
                        "Unsupported Demo Wallet seed "
                        f"version: {version}"
                    )

                db.commit()

                return False

            self._assert_empty_without_seed_marker(
                db
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

    def list_accounts(
        self,
    ) -> list[
        dict[
            str,
            Any,
        ]
    ]:
        with self._reader() as db:
            rows = db.execute(
                """
                SELECT
                    account_id,
                    display_name,
                    sort_order,
                    seeded_at
                FROM demo_wallet_accounts
                ORDER BY
                    sort_order ASC,
                    account_id ASC
                """
            ).fetchall()

        return [
            {
                "account_id":
                    row[
                        "account_id"
                    ],
                "display_name":
                    row[
                        "display_name"
                    ],
                "sort_order":
                    int(
                        row[
                            "sort_order"
                        ]
                    ),
                "seeded_at":
                    row[
                        "seeded_at"
                    ],
            }
            for row
            in rows
        ]

    def get_balance_state(
        self,
        account_id: str,
    ) -> dict[
        str,
        Any,
    ]:
        normalized = (
            _normalize_account_id(
                account_id
            )
        )

        with self._reader() as db:
            account = db.execute(
                """
                SELECT
                    account_id,
                    display_name,
                    quant_value_usdt,
                    bot_initial_capital,
                    bot_current_value,
                    bot_pnl,
                    running_bots,
                    tracked_bots
                FROM demo_wallet_accounts
                WHERE account_id = ?
                """,
                (
                    normalized,
                ),
            ).fetchone()

            if account is None:
                raise DemoWalletStateError(
                    "Demo Wallet account seed is missing"
                )

            asset_rows = db.execute(
                """
                SELECT
                    currency,
                    available,
                    locked,
                    price_usdt
                FROM demo_wallet_assets
                WHERE account_id = ?
                ORDER BY currency ASC
                """,
                (
                    normalized,
                ),
            ).fetchall()

        assets = []

        spot_value = Decimal(
            "0"
        )

        for row in asset_rows:
            available = Decimal(
                row[
                    "available"
                ]
            )

            locked = Decimal(
                row[
                    "locked"
                ]
            )

            total = (
                available
                + locked
            )

            price = Decimal(
                row[
                    "price_usdt"
                ]
            )

            value = (
                total
                * price
            )

            spot_value += value

            assets.append(
                {
                    "currency":
                        row[
                            "currency"
                        ],
                    "available":
                        _decimal_text(
                            available
                        ),
                    "locked":
                        _decimal_text(
                            locked
                        ),
                    "total":
                        _decimal_text(
                            total
                        ),
                    "price_usdt":
                        _decimal_text(
                            price
                        ),
                    "value_usdt":
                        _decimal_text(
                            value
                        ),
                }
            )

        quant_value = Decimal(
            account[
                "quant_value_usdt"
            ]
        )

        total_value = (
            spot_value
            + quant_value
        )

        return {
            "account_id":
                account[
                    "account_id"
                ],
            "display_name":
                account[
                    "display_name"
                ],
            "source":
                "demo",
            "seed_version":
                DEMO_WALLET_SEED_VERSION,
            "spot_value_usdt":
                _decimal_text(
                    spot_value
                ),
            "quant_value_usdt":
                _decimal_text(
                    quant_value
                ),
            "total_value_usdt":
                _decimal_text(
                    total_value
                ),
            "assets":
                assets,
            "bot_summary": {
                "invest_amount":
                    account[
                        "bot_initial_capital"
                    ],
                "current_value":
                    account[
                        "bot_current_value"
                    ],
                "pnl":
                    account[
                        "bot_pnl"
                    ],
                "running_bots":
                    int(
                        account[
                            "running_bots"
                        ]
                    ),
                "tracked_bots":
                    int(
                        account[
                            "tracked_bots"
                        ]
                    ),
            },
        }

    def list_currencies(
        self,
    ) -> list[
        dict[
            str,
            Any,
        ]
    ]:
        with self._reader() as db:
            rows = db.execute(
                """
                SELECT
                    currency,
                    name,
                    main_chain,
                    trade_disabled,
                    sort_order
                FROM demo_wallet_currencies
                ORDER BY
                    sort_order ASC,
                    currency ASC
                """
            ).fetchall()

        return [
            {
                "currency":
                    row[
                        "currency"
                    ],
                "name":
                    row[
                        "name"
                    ],
                "main_chain":
                    row[
                        "main_chain"
                    ],
                "trade_disabled":
                    bool(
                        row[
                            "trade_disabled"
                        ]
                    ),
                "sort_order":
                    int(
                        row[
                            "sort_order"
                        ]
                    ),
            }
            for row
            in rows
        ]

    def list_deposit_networks(
        self,
        account_id: str,
        currency: str,
    ) -> list[
        dict[
            str,
            Any,
        ]
    ]:
        normalized_account = (
            _normalize_account_id(
                account_id
            )
        )

        normalized_currency = (
            _normalize_currency(
                currency
            )
        )

        with self._reader() as db:
            rows = db.execute(
                """
                SELECT
                    network,
                    network_name,
                    address,
                    payment_id,
                    contract_address,
                    minimum_deposit_amount,
                    min_confirmations,
                    deposit_enabled,
                    withdraw_enabled,
                    requires_memo,
                    decimal_places,
                    sort_order
                FROM demo_deposit_addresses
                WHERE account_id = ?
                  AND currency = ?
                ORDER BY
                    sort_order ASC,
                    network ASC
                """,
                (
                    normalized_account,
                    normalized_currency,
                ),
            ).fetchall()

        return [
            {
                "chain":
                    row[
                        "network"
                    ],
                "name":
                    row[
                        "network_name"
                    ],
                "address":
                    row[
                        "address"
                    ],
                "payment_id": (
                    row[
                        "payment_id"
                    ]
                    or None
                ),
                "contract_address":
                    row[
                        "contract_address"
                    ],
                "minimum_deposit_amount":
                    row[
                        "minimum_deposit_amount"
                    ],
                "min_confirmations":
                    int(
                        row[
                            "min_confirmations"
                        ]
                    ),
                "deposit_enabled":
                    bool(
                        row[
                            "deposit_enabled"
                        ]
                    ),
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
                "decimal":
                    row[
                        "decimal_places"
                    ],
            }
            for row
            in rows
        ]

    def get_deposit_address(
        self,
        account_id: str,
        currency: str,
        network: str,
    ) -> dict[
        str,
        Any,
    ]:
        normalized_account = (
            _normalize_account_id(
                account_id
            )
        )

        normalized_currency = (
            _normalize_currency(
                currency
            )
        )

        normalized_network = (
            _normalize_network(
                network
            )
        )

        with self._reader() as db:
            row = db.execute(
                """
                SELECT
                    network,
                    network_name,
                    address,
                    payment_id,
                    contract_address,
                    minimum_deposit_amount,
                    min_confirmations,
                    deposit_enabled,
                    withdraw_enabled,
                    requires_memo,
                    decimal_places
                FROM demo_deposit_addresses
                WHERE account_id = ?
                  AND currency = ?
                  AND network = ?
                """,
                (
                    normalized_account,
                    normalized_currency,
                    normalized_network,
                ),
            ).fetchone()

        if row is None:
            raise KeyError(
                "Unknown Demo deposit network"
            )

        return {
            "account_id":
                normalized_account,
            "currency":
                normalized_currency,
            "chain":
                row[
                    "network"
                ],
            "name":
                row[
                    "network_name"
                ],
            "address":
                row[
                    "address"
                ],
            "payment_id": (
                row[
                    "payment_id"
                ]
                or None
            ),
            "contract_address":
                row[
                    "contract_address"
                ],
            "minimum_deposit_amount":
                row[
                    "minimum_deposit_amount"
                ],
            "min_confirmations":
                int(
                    row[
                        "min_confirmations"
                    ]
                ),
            "deposit_enabled":
                bool(
                    row[
                        "deposit_enabled"
                    ]
                ),
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
            "decimal":
                row[
                    "decimal_places"
                ],
            "source":
                "demo",
        }

    def list_deposits(
        self,
        account_id: str,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[
        str,
        Any,
    ]:
        normalized = (
            _normalize_account_id(
                account_id
            )
        )

        if (
            limit < 1
            or limit > 200
        ):
            raise ValueError(
                "Demo deposit limit must be between 1 and 200"
            )

        if offset < 0:
            raise ValueError(
                "Demo deposit offset must not be negative"
            )

        with self._reader() as db:
            total = int(
                db.execute(
                    """
                    SELECT COUNT(*)
                    FROM demo_deposits
                    WHERE account_id = ?
                    """,
                    (
                        normalized,
                    ),
                ).fetchone()[0]
            )

            rows = db.execute(
                """
                SELECT
                    id,
                    account_id,
                    gate_deposit_id,
                    txid,
                    reference_id,
                    currency,
                    chain,
                    amount,
                    address,
                    memo,
                    status,
                    refund_status,
                    deposited_at,
                    first_seen_at,
                    last_seen_at,
                    updated_at
                FROM demo_deposits
                WHERE account_id = ?
                ORDER BY
                    deposited_at DESC,
                    id DESC
                LIMIT ?
                OFFSET ?
                """,
                (
                    normalized,
                    limit,
                    offset,
                ),
            ).fetchall()

        return {
            "account_id":
                normalized,
            "total":
                total,
            "limit":
                limit,
            "offset":
                offset,
            "items": [
                self._deposit_row_to_dict(
                    row
                )
                for row
                in rows
            ],
        }

    def get_deposit(
        self,
        account_id: str,
        deposit_id: int,
    ) -> dict[
        str,
        Any,
    ]:
        normalized = (
            _normalize_account_id(
                account_id
            )
        )

        with self._reader() as db:
            row = db.execute(
                """
                SELECT
                    id,
                    account_id,
                    gate_deposit_id,
                    txid,
                    reference_id,
                    currency,
                    chain,
                    amount,
                    address,
                    memo,
                    status,
                    refund_status,
                    deposited_at,
                    first_seen_at,
                    last_seen_at,
                    updated_at,
                    raw_json
                FROM demo_deposits
                WHERE account_id = ?
                  AND id = ?
                """,
                (
                    normalized,
                    int(
                        deposit_id
                    ),
                ),
            ).fetchone()

        if row is None:
            raise KeyError(
                "Demo deposit not found"
            )

        result = (
            self._deposit_row_to_dict(
                row
            )
        )

        try:
            result[
                "raw"
            ] = json.loads(
                row[
                    "raw_json"
                ]
            )

        except json.JSONDecodeError:
            result[
                "raw"
            ] = {}

        return result

    @staticmethod
    def _deposit_row_to_dict(
        row: sqlite3.Row,
    ) -> dict[
        str,
        Any,
    ]:
        status = str(
            row[
                "status"
            ]
        ).upper()

        return {
            "id":
                int(
                    row[
                        "id"
                    ]
                ),
            "account_id":
                row[
                    "account_id"
                ],
            "gate_deposit_id":
                row[
                    "gate_deposit_id"
                ],
            "txid":
                row[
                    "txid"
                ],
            "reference_id":
                row[
                    "reference_id"
                ],
            "currency":
                row[
                    "currency"
                ],
            "chain":
                row[
                    "chain"
                ],
            "amount":
                row[
                    "amount"
                ],
            "address":
                row[
                    "address"
                ],
            "memo":
                row[
                    "memo"
                ],
            "status":
                status,
            "refund_status":
                row[
                    "refund_status"
                ],
            "deposited_at":
                row[
                    "deposited_at"
                ],
            "first_seen_at":
                row[
                    "first_seen_at"
                ],
            "last_seen_at":
                row[
                    "last_seen_at"
                ],
            "updated_at":
                row[
                    "updated_at"
                ],
            "final":
                status
                in {
                    "DONE",
                    "INVALID",
                    "BLOCKED",
                },
        }
