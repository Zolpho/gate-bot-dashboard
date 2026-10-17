from __future__ import annotations

import sqlite3

from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from .demo_trading import (
    _decimal_text,
    _positive_decimal,
)
from .demo_trading_orders import (
    DemoTradingOrderConflict,
    DemoTradingOrderError,
    DemoTradingOrderStore,
    _canonical_json,
    _fingerprint,
    _load_json,
    _normalize_request_id,
    _normalize_scope,
    _normalize_username,
    _timestamp,
)


DEMO_TRADING_LIFECYCLE_SCHEMA_VERSION = "1"


class DemoTradingOrderLifecycleError(
    DemoTradingOrderError
):
    """An isolated Demo order lifecycle transition is invalid."""


class DemoTradingOrderAmendmentConflict(
    DemoTradingOrderLifecycleError
):
    """A Demo amendment ID is bound to another amendment intent."""


def demo_trading_cancel_confirmation_text(
    request_id: str,
) -> str:
    return (
        "CANCEL DEMO LIMIT ORDER "
        + _normalize_request_id(
            request_id
        )
    )


def demo_trading_amend_confirmation_text(
    request_id: str,
    new_price: Decimal | str | int,
) -> str:
    return " ".join(
        (
            "AMEND DEMO LIMIT ORDER",
            _normalize_request_id(
                request_id
            ),
            "PRICE",
            _decimal_text(
                _positive_decimal(
                    new_price,
                    "amend price",
                )
            ),
        )
    )


class DemoTradingOrderLifecycleStore:
    """
    Isolated cancellation and price-amend accounting.

    Cancellation atomically releases the active reservation.

    BUY price amendments adjust only the quote reservation delta.
    SELL price amendments do not change the locked base amount.

    There is no Gate transport, production Trading repository,
    live credential reader, production lock/rate-limit state,
    HTTP routing, browser recovery or reconciliation.
    """

    def __init__(
        self,
        database_path: Path,
    ) -> None:
        self.database_path = Path(
            database_path
        )

        self.orders = (
            DemoTradingOrderStore(
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
                demo_trading_order_cancellations (
                    request_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    released_asset TEXT NOT NULL,
                    released_amount TEXT NOT NULL,
                    order_snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,

                    FOREIGN KEY (
                        request_id
                    )
                    REFERENCES demo_trading_orders (
                        request_id
                    )
                    ON DELETE CASCADE,

                    FOREIGN KEY (
                        account_id
                    )
                    REFERENCES demo_wallet_accounts (
                        account_id
                    )
                );

            CREATE TABLE IF NOT EXISTS
                demo_trading_order_amendments (
                    amendment_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    old_price TEXT NOT NULL,
                    new_price TEXT NOT NULL,
                    old_total TEXT NOT NULL,
                    new_total TEXT NOT NULL,
                    old_reserved_amount TEXT NOT NULL,
                    new_reserved_amount TEXT NOT NULL,
                    reservation_delta TEXT NOT NULL,
                    intent_hash TEXT NOT NULL,
                    intent_json TEXT NOT NULL,
                    order_snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,

                    FOREIGN KEY (
                        request_id
                    )
                    REFERENCES demo_trading_orders (
                        request_id
                    )
                    ON DELETE CASCADE,

                    FOREIGN KEY (
                        account_id
                    )
                    REFERENCES demo_wallet_accounts (
                        account_id
                    )
                );

            CREATE INDEX IF NOT EXISTS
                ix_demo_trading_order_amendments_request
            ON demo_trading_order_amendments (
                request_id,
                created_at ASC,
                amendment_id ASC
            );
            """
        )

    def ensure_ready(
        self,
    ) -> None:
        self.orders.ensure_ready()

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
                FROM demo_trading_meta
                WHERE key = 'order_lifecycle_schema_version'
                """
            ).fetchone()

            cancellation_count = int(
                db.execute(
                    """
                    SELECT COUNT(*)
                    FROM demo_trading_order_cancellations
                    """
                ).fetchone()[0]
            )

            amendment_count = int(
                db.execute(
                    """
                    SELECT COUNT(*)
                    FROM demo_trading_order_amendments
                    """
                ).fetchone()[0]
            )

            if marker is None:
                if (
                    cancellation_count
                    or amendment_count
                ):
                    raise DemoTradingOrderLifecycleError(
                        "Demo Trading lifecycle schema marker "
                        "is missing for non-empty state"
                    )

                db.execute(
                    """
                    INSERT INTO demo_trading_meta (
                        key,
                        value
                    )
                    VALUES (
                        'order_lifecycle_schema_version',
                        ?
                    )
                    """,
                    (
                        DEMO_TRADING_LIFECYCLE_SCHEMA_VERSION,
                    ),
                )

            elif (
                str(marker["value"])
                != DEMO_TRADING_LIFECYCLE_SCHEMA_VERSION
            ):
                raise DemoTradingOrderLifecycleError(
                    "Unsupported Demo Trading lifecycle schema version"
                )

            db.commit()

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
        self.ensure_ready()

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
        self.ensure_ready()

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
    def _scope_allows(
        scope: set[str] | None,
        account_id: str,
    ) -> bool:
        return (
            scope is None
            or account_id in scope
        )

    @staticmethod
    def _cancellation_payload(
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        return {
            "request_id":
                row["request_id"],
            "account_id":
                row["account_id"],
            "username":
                row["username"],
            "released_asset":
                row["released_asset"],
            "released_amount":
                row["released_amount"],
            "order":
                _load_json(
                    row[
                        "order_snapshot_json"
                    ]
                ),
            "created_at":
                row["created_at"],
            "source":
                "demo",
        }

    @staticmethod
    def _amendment_payload(
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        return {
            "amendment_id":
                row["amendment_id"],
            "request_id":
                row["request_id"],
            "account_id":
                row["account_id"],
            "username":
                row["username"],
            "old_price":
                row["old_price"],
            "new_price":
                row["new_price"],
            "old_total":
                row["old_total"],
            "new_total":
                row["new_total"],
            "old_reserved_amount":
                row[
                    "old_reserved_amount"
                ],
            "new_reserved_amount":
                row[
                    "new_reserved_amount"
                ],
            "reservation_delta":
                row[
                    "reservation_delta"
                ],
            "order":
                _load_json(
                    row[
                        "order_snapshot_json"
                    ]
                ),
            "created_at":
                row["created_at"],
            "source":
                "demo",
        }

    @staticmethod
    def _cancellation_in_db(
        db: sqlite3.Connection,
        request_id: str,
    ) -> sqlite3.Row | None:
        return db.execute(
            """
            SELECT *
            FROM demo_trading_order_cancellations
            WHERE request_id = ?
            """,
            (
                request_id,
            ),
        ).fetchone()

    @staticmethod
    def _amendment_in_db(
        db: sqlite3.Connection,
        amendment_id: str,
    ) -> sqlite3.Row | None:
        return db.execute(
            """
            SELECT *
            FROM demo_trading_order_amendments
            WHERE amendment_id = ?
            """,
            (
                amendment_id,
            ),
        ).fetchone()

    @staticmethod
    def _base_response(
        *,
        replay: bool,
        demo_write: bool,
    ) -> dict[str, Any]:
        return {
            "source":
                "demo",
            "simulation":
                True,
            "gate_read_performed":
                False,
            "gate_write_performed":
                False,
            "write_performed":
                False,
            "demo_write_performed":
                demo_write,
            "idempotent_replay":
                replay,
        }

    def cancel_order(
        self,
        *,
        request_id: str,
        username: str,
        confirmation: str,
        account_ids: set[str] | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_request_id = (
            _normalize_request_id(
                request_id
            )
        )

        normalized_username = (
            _normalize_username(
                username
            )
        )

        scope = _normalize_scope(
            account_ids
        )

        self.ensure_ready()

        # Terminal replay is resolved before confirmation and before
        # any fresh balance validation.
        with self._reader() as db:
            cancellation = (
                self._cancellation_in_db(
                    db,
                    normalized_request_id,
                )
            )

            if cancellation is not None:
                account_id = str(
                    cancellation[
                        "account_id"
                    ]
                )

                if not self._scope_allows(
                    scope,
                    account_id,
                ):
                    raise KeyError(
                        "Demo Trading order not found"
                    )

                return {
                    **self._base_response(
                        replay=True,
                        demo_write=False,
                    ),
                    "balance_release_performed":
                        False,
                    "cancellation":
                        self._cancellation_payload(
                            cancellation
                        ),
                }

            order_row = (
                self.orders._existing_row(
                    db,
                    normalized_request_id,
                )
            )

            if order_row is None:
                raise KeyError(
                    "Demo Trading order not found"
                )

            account_id = str(
                order_row[
                    "account_id"
                ]
            )

            if not self._scope_allows(
                scope,
                account_id,
            ):
                raise KeyError(
                    "Demo Trading order not found"
                )

            if (
                str(
                    order_row["status"]
                )
                != "open"
                or not bool(
                    order_row[
                        "balance_reserved"
                    ]
                )
            ):
                raise DemoTradingOrderLifecycleError(
                    "Only an open reserved Demo order can be cancelled"
                )

        required_confirmation = (
            demo_trading_cancel_confirmation_text(
                normalized_request_id
            )
        )

        if (
            str(
                confirmation or ""
            )
            != required_confirmation
        ):
            raise DemoTradingOrderLifecycleError(
                "Exact Demo Trading cancel confirmation is required"
            )

        created_at = _timestamp(
            occurred_at
        )

        with self._writer() as db:
            cancellation = (
                self._cancellation_in_db(
                    db,
                    normalized_request_id,
                )
            )

            if cancellation is not None:
                account_id = str(
                    cancellation[
                        "account_id"
                    ]
                )

                if not self._scope_allows(
                    scope,
                    account_id,
                ):
                    raise KeyError(
                        "Demo Trading order not found"
                    )

                return {
                    **self._base_response(
                        replay=True,
                        demo_write=False,
                    ),
                    "balance_release_performed":
                        False,
                    "cancellation":
                        self._cancellation_payload(
                            cancellation
                        ),
                }

            order_row = (
                self.orders._existing_row(
                    db,
                    normalized_request_id,
                )
            )

            if order_row is None:
                raise KeyError(
                    "Demo Trading order not found"
                )

            account_id = str(
                order_row[
                    "account_id"
                ]
            )

            if not self._scope_allows(
                scope,
                account_id,
            ):
                raise KeyError(
                    "Demo Trading order not found"
                )

            if (
                str(
                    order_row["status"]
                )
                != "open"
                or not bool(
                    order_row[
                        "balance_reserved"
                    ]
                )
            ):
                raise DemoTradingOrderLifecycleError(
                    "Only an open reserved Demo order can be cancelled"
                )

            funding_asset = str(
                order_row[
                    "funding_asset"
                ]
            )

            reserved = Decimal(
                str(
                    order_row[
                        "reserved_amount"
                    ]
                )
            )

            if reserved <= 0:
                raise DemoTradingOrderLifecycleError(
                    "Demo order has no active reservation to release"
                )

            balance = db.execute(
                """
                SELECT
                    available,
                    locked
                FROM demo_wallet_assets
                WHERE
                    account_id = ?
                    AND currency = ?
                """,
                (
                    account_id,
                    funding_asset,
                ),
            ).fetchone()

            if balance is None:
                raise DemoTradingOrderLifecycleError(
                    "Demo Trading funding asset is unavailable"
                )

            available = Decimal(
                str(
                    balance[
                        "available"
                    ]
                )
            )

            locked = Decimal(
                str(
                    balance[
                        "locked"
                    ]
                )
            )

            if locked < reserved:
                raise DemoTradingOrderLifecycleError(
                    "Demo Wallet locked balance is below "
                    "the order reservation"
                )

            available_after = (
                available
                + reserved
            )

            locked_after = (
                locked
                - reserved
            )

            db.execute(
                """
                UPDATE demo_wallet_assets
                SET
                    available = ?,
                    locked = ?
                WHERE
                    account_id = ?
                    AND currency = ?
                """,
                (
                    _decimal_text(
                        available_after
                    ),
                    _decimal_text(
                        locked_after
                    ),
                    account_id,
                    funding_asset,
                ),
            )

            db.execute(
                """
                UPDATE demo_trading_orders
                SET
                    reserved_amount = '0',
                    balance_reserved = 0,
                    status = 'cancelled',
                    updated_at = ?
                WHERE request_id = ?
                """,
                (
                    created_at,
                    normalized_request_id,
                ),
            )

            updated_row = (
                self.orders._existing_row(
                    db,
                    normalized_request_id,
                )
            )

            if updated_row is None:
                raise DemoTradingOrderLifecycleError(
                    "Demo Trading order disappeared during cancellation"
                )

            order = (
                self.orders._row_payload(
                    updated_row
                )
            )

            db.execute(
                """
                INSERT INTO demo_trading_order_cancellations (
                    request_id,
                    account_id,
                    username,
                    released_asset,
                    released_amount,
                    order_snapshot_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_request_id,
                    account_id,
                    normalized_username,
                    funding_asset,
                    _decimal_text(
                        reserved
                    ),
                    _canonical_json(
                        order
                    ),
                    created_at,
                ),
            )

            details = {
                "demo":
                    True,
                "simulation":
                    True,
                "gate_read_performed":
                    False,
                "gate_write_performed":
                    False,
                "released_asset":
                    funding_asset,
                "released_amount":
                    _decimal_text(
                        reserved
                    ),
                "available_before":
                    _decimal_text(
                        available
                    ),
                "available_after":
                    _decimal_text(
                        available_after
                    ),
                "locked_before":
                    _decimal_text(
                        locked
                    ),
                "locked_after":
                    _decimal_text(
                        locked_after
                    ),
            }

            db.execute(
                """
                INSERT INTO demo_trading_order_events (
                    request_id,
                    account_id,
                    username,
                    action,
                    from_status,
                    to_status,
                    details_json,
                    created_at
                )
                VALUES (?, ?, ?, 'cancelled', 'open', 'cancelled', ?, ?)
                """,
                (
                    normalized_request_id,
                    account_id,
                    normalized_username,
                    _canonical_json(
                        details
                    ),
                    created_at,
                ),
            )

            cancellation = (
                self._cancellation_in_db(
                    db,
                    normalized_request_id,
                )
            )

            if cancellation is None:
                raise DemoTradingOrderLifecycleError(
                    "Demo cancellation audit was not created"
                )

            payload = (
                self._cancellation_payload(
                    cancellation
                )
            )

        return {
            **self._base_response(
                replay=False,
                demo_write=True,
            ),
            "balance_release_performed":
                True,
            "cancellation":
                payload,
        }

    def amend_order_price(
        self,
        *,
        amendment_id: str,
        request_id: str,
        username: str,
        new_price: Decimal | str | int,
        confirmation: str,
        account_ids: set[str] | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_amendment_id = (
            _normalize_request_id(
                amendment_id
            )
        )

        normalized_request_id = (
            _normalize_request_id(
                request_id
            )
        )

        normalized_username = (
            _normalize_username(
                username
            )
        )

        normalized_new_price = (
            _positive_decimal(
                new_price,
                "amend price",
            )
        )

        scope = _normalize_scope(
            account_ids
        )

        intent = {
            "operation":
                "demo_limit_order_price_amend",
            "amendment_id":
                normalized_amendment_id,
            "request_id":
                normalized_request_id,
            "username":
                normalized_username,
            "new_price":
                _decimal_text(
                    normalized_new_price
                ),
            "execution_mode":
                "demo",
        }

        intent_json = _canonical_json(
            intent
        )

        intent_hash = _fingerprint(
            intent
        )

        self.ensure_ready()

        # Amendment-ID replay occurs before confirmation, fresh
        # preview or balance validation.
        with self._reader() as db:
            existing = (
                self._amendment_in_db(
                    db,
                    normalized_amendment_id,
                )
            )

            if existing is not None:
                if (
                    str(
                        existing[
                            "intent_hash"
                        ]
                    )
                    != intent_hash
                ):
                    raise DemoTradingOrderAmendmentConflict(
                        "Demo Trading amendment ID is already "
                        "bound to a different amendment intent"
                    )

                account_id = str(
                    existing[
                        "account_id"
                    ]
                )

                if not self._scope_allows(
                    scope,
                    account_id,
                ):
                    raise KeyError(
                        "Demo Trading order not found"
                    )

                return {
                    **self._base_response(
                        replay=True,
                        demo_write=False,
                    ),
                    "balance_adjustment_performed":
                        False,
                    "amendment":
                        self._amendment_payload(
                            existing
                        ),
                }

        order = self.orders.get_order(
            normalized_request_id,
            account_ids=
                scope,
        )

        if (
            order["status"]
            != "open"
            or order[
                "balance_reserved"
            ]
            is not True
        ):
            raise DemoTradingOrderLifecycleError(
                "Only an open reserved Demo order can be amended"
            )

        old_price = Decimal(
            str(
                order["price"]
            )
        )

        if (
            normalized_new_price
            == old_price
        ):
            raise DemoTradingOrderLifecycleError(
                "New Demo Trading price must differ from the current price"
            )

        required_confirmation = (
            demo_trading_amend_confirmation_text(
                normalized_request_id,
                normalized_new_price,
            )
        )

        if (
            str(
                confirmation or ""
            )
            != required_confirmation
        ):
            raise DemoTradingOrderLifecycleError(
                "Exact Demo Trading amend confirmation is required"
            )

        remaining = Decimal(
            str(
                order[
                    "remaining_amount"
                ]
            )
        )

        old_reserved = Decimal(
            str(
                order[
                    "reserved_amount"
                ]
            )
        )

        if (
            remaining <= 0
            or old_reserved <= 0
        ):
            raise DemoTradingOrderLifecycleError(
                "Demo order has no remaining active reservation"
            )

        preview = (
            self.orders.trading
            .preview_limit_order(
                account_id=
                    order["account_id"],
                pair=
                    order["pair"],
                side=
                    order["side"],
                price=
                    normalized_new_price,
                amount=
                    remaining,
                time_in_force=
                    order[
                        "time_in_force"
                    ],
            )
        )

        # The ordinary new-order preview only sees Wallet available
        # funds. An amendment may also reuse the amount already locked
        # by this exact order, so funding is recomputed atomically
        # below from the reservation delta.
        blockers = [
            str(item)
            for item in (
                preview.get(
                    "blockers"
                )
                or []
            )
            if str(item)
            != (
                "Insufficient Demo Wallet "
                "available balance."
            )
        ]

        if blockers:
            raise DemoTradingOrderLifecycleError(
                "Demo Trading amend preview rejected order: "
                + "; ".join(
                    blockers
                )
            )

        new_total = (
            normalized_new_price
            * remaining
        )

        if order["side"] == "buy":
            new_reserved = (
                new_total
            )

        else:
            new_reserved = (
                remaining
            )

        delta = (
            new_reserved
            - old_reserved
        )

        preview[
            "blockers"
        ] = []

        preview[
            "status"
        ] = "ready"

        preview[
            "demo_execution_ready"
        ] = True

        created_at = _timestamp(
            occurred_at
        )

        with self._writer() as db:
            existing = (
                self._amendment_in_db(
                    db,
                    normalized_amendment_id,
                )
            )

            if existing is not None:
                if (
                    str(
                        existing[
                            "intent_hash"
                        ]
                    )
                    != intent_hash
                ):
                    raise DemoTradingOrderAmendmentConflict(
                        "Demo Trading amendment ID is already "
                        "bound to a different amendment intent"
                    )

                account_id = str(
                    existing[
                        "account_id"
                    ]
                )

                if not self._scope_allows(
                    scope,
                    account_id,
                ):
                    raise KeyError(
                        "Demo Trading order not found"
                    )

                return {
                    **self._base_response(
                        replay=True,
                        demo_write=False,
                    ),
                    "balance_adjustment_performed":
                        False,
                    "amendment":
                        self._amendment_payload(
                            existing
                        ),
                }

            row = self.orders._existing_row(
                db,
                normalized_request_id,
            )

            if row is None:
                raise KeyError(
                    "Demo Trading order not found"
                )

            account_id = str(
                row["account_id"]
            )

            if not self._scope_allows(
                scope,
                account_id,
            ):
                raise KeyError(
                    "Demo Trading order not found"
                )

            if (
                str(
                    row["status"]
                )
                != "open"
                or not bool(
                    row[
                        "balance_reserved"
                    ]
                )
            ):
                raise DemoTradingOrderLifecycleError(
                    "Only an open reserved Demo order can be amended"
                )

            current_price = Decimal(
                str(
                    row["price"]
                )
            )

            current_reserved = Decimal(
                str(
                    row[
                        "reserved_amount"
                    ]
                )
            )

            current_remaining = Decimal(
                str(
                    row[
                        "remaining_amount"
                    ]
                )
            )

            if (
                current_price
                != old_price
                or current_reserved
                != old_reserved
                or current_remaining
                != remaining
            ):
                raise DemoTradingOrderLifecycleError(
                    "Demo Trading order changed before amendment"
                )

            funding_asset = str(
                row[
                    "funding_asset"
                ]
            )

            balance = db.execute(
                """
                SELECT
                    available,
                    locked
                FROM demo_wallet_assets
                WHERE
                    account_id = ?
                    AND currency = ?
                """,
                (
                    account_id,
                    funding_asset,
                ),
            ).fetchone()

            if balance is None:
                raise DemoTradingOrderLifecycleError(
                    "Demo Trading funding asset is unavailable"
                )

            available = Decimal(
                str(
                    balance[
                        "available"
                    ]
                )
            )

            locked = Decimal(
                str(
                    balance[
                        "locked"
                    ]
                )
            )

            available_after = available
            locked_after = locked

            if delta > 0:
                if available < delta:
                    raise DemoTradingOrderLifecycleError(
                        "Insufficient Demo Wallet available balance "
                        "for amendment reservation increase"
                    )

                available_after = (
                    available
                    - delta
                )

                locked_after = (
                    locked
                    + delta
                )

            elif delta < 0:
                release = -delta

                if locked < release:
                    raise DemoTradingOrderLifecycleError(
                        "Demo Wallet locked balance is below "
                        "the amendment release"
                    )

                available_after = (
                    available
                    + release
                )

                locked_after = (
                    locked
                    - release
                )

            effective_available = (
                available
                + old_reserved
            )

            preview_funds = dict(
                preview.get(
                    "funds"
                )
                or {}
            )

            preview_funds.update(
                {
                    "asset":
                        funding_asset,
                    "available":
                        _decimal_text(
                            effective_available
                        ),
                    "required":
                        _decimal_text(
                            new_reserved
                        ),
                    "remaining":
                        _decimal_text(
                            effective_available
                            - new_reserved
                        ),
                    "existing_reservation":
                        _decimal_text(
                            old_reserved
                        ),
                    "reservation_delta":
                        _decimal_text(
                            delta
                        ),
                }
            )

            preview[
                "funds"
            ] = preview_funds

            db.execute(
                """
                UPDATE demo_wallet_assets
                SET
                    available = ?,
                    locked = ?
                WHERE
                    account_id = ?
                    AND currency = ?
                """,
                (
                    _decimal_text(
                        available_after
                    ),
                    _decimal_text(
                        locked_after
                    ),
                    account_id,
                    funding_asset,
                ),
            )

            db.execute(
                """
                UPDATE demo_trading_orders
                SET
                    price = ?,
                    total = ?,
                    reserved_amount = ?,
                    preview_json = ?,
                    updated_at = ?
                WHERE request_id = ?
                """,
                (
                    _decimal_text(
                        normalized_new_price
                    ),
                    _decimal_text(
                        new_total
                    ),
                    _decimal_text(
                        new_reserved
                    ),
                    _canonical_json(
                        preview
                    ),
                    created_at,
                    normalized_request_id,
                ),
            )

            updated_row = (
                self.orders._existing_row(
                    db,
                    normalized_request_id,
                )
            )

            if updated_row is None:
                raise DemoTradingOrderLifecycleError(
                    "Demo Trading order disappeared during amendment"
                )

            updated_order = (
                self.orders._row_payload(
                    updated_row
                )
            )

            db.execute(
                """
                INSERT INTO demo_trading_order_amendments (
                    amendment_id,
                    request_id,
                    account_id,
                    username,
                    old_price,
                    new_price,
                    old_total,
                    new_total,
                    old_reserved_amount,
                    new_reserved_amount,
                    reservation_delta,
                    intent_hash,
                    intent_json,
                    order_snapshot_json,
                    created_at
                )
                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?
                )
                """,
                (
                    normalized_amendment_id,
                    normalized_request_id,
                    account_id,
                    normalized_username,
                    _decimal_text(
                        old_price
                    ),
                    _decimal_text(
                        normalized_new_price
                    ),
                    str(
                        row["total"]
                    ),
                    _decimal_text(
                        new_total
                    ),
                    _decimal_text(
                        old_reserved
                    ),
                    _decimal_text(
                        new_reserved
                    ),
                    _decimal_text(
                        delta
                    ),
                    intent_hash,
                    intent_json,
                    _canonical_json(
                        updated_order
                    ),
                    created_at,
                ),
            )

            details = {
                "demo":
                    True,
                "simulation":
                    True,
                "gate_read_performed":
                    False,
                "gate_write_performed":
                    False,
                "amendment_id":
                    normalized_amendment_id,
                "old_price":
                    _decimal_text(
                        old_price
                    ),
                "new_price":
                    _decimal_text(
                        normalized_new_price
                    ),
                "old_reserved_amount":
                    _decimal_text(
                        old_reserved
                    ),
                "new_reserved_amount":
                    _decimal_text(
                        new_reserved
                    ),
                "reservation_delta":
                    _decimal_text(
                        delta
                    ),
                "available_before":
                    _decimal_text(
                        available
                    ),
                "available_after":
                    _decimal_text(
                        available_after
                    ),
                "locked_before":
                    _decimal_text(
                        locked
                    ),
                "locked_after":
                    _decimal_text(
                        locked_after
                    ),
            }

            db.execute(
                """
                INSERT INTO demo_trading_order_events (
                    request_id,
                    account_id,
                    username,
                    action,
                    from_status,
                    to_status,
                    details_json,
                    created_at
                )
                VALUES (?, ?, ?, 'amended', 'open', 'open', ?, ?)
                """,
                (
                    normalized_request_id,
                    account_id,
                    normalized_username,
                    _canonical_json(
                        details
                    ),
                    created_at,
                ),
            )

            amendment = (
                self._amendment_in_db(
                    db,
                    normalized_amendment_id,
                )
            )

            if amendment is None:
                raise DemoTradingOrderLifecycleError(
                    "Demo Trading amendment audit was not created"
                )

            payload = (
                self._amendment_payload(
                    amendment
                )
            )

        return {
            **self._base_response(
                replay=False,
                demo_write=True,
            ),
            "balance_adjustment_performed":
                delta != 0,
            "amendment":
                payload,
        }

    def get_cancellation(
        self,
        request_id: str,
        *,
        account_ids: set[str] | None = None,
    ) -> dict[str, Any] | None:
        normalized_request_id = (
            _normalize_request_id(
                request_id
            )
        )

        scope = _normalize_scope(
            account_ids
        )

        with self._reader() as db:
            row = (
                self._cancellation_in_db(
                    db,
                    normalized_request_id,
                )
            )

        if row is None:
            return None

        account_id = str(
            row["account_id"]
        )

        if not self._scope_allows(
            scope,
            account_id,
        ):
            raise KeyError(
                "Demo Trading order not found"
            )

        return self._cancellation_payload(
            row
        )

    def list_amendments(
        self,
        request_id: str,
        *,
        account_ids: set[str] | None = None,
    ) -> list[
        dict[str, Any]
    ]:
        normalized_request_id = (
            _normalize_request_id(
                request_id
            )
        )

        self.orders.get_order(
            normalized_request_id,
            account_ids=
                account_ids,
        )

        with self._reader() as db:
            rows = db.execute(
                """
                SELECT *
                FROM demo_trading_order_amendments
                WHERE request_id = ?
                ORDER BY
                    created_at ASC,
                    amendment_id ASC
                """,
                (
                    normalized_request_id,
                ),
            ).fetchall()

        return [
            self._amendment_payload(
                row
            )
            for row in rows
        ]
