from __future__ import annotations

import hashlib
import json
import re
import sqlite3

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from .demo_trading import (
    DEMO_TRADING_REQUIRED_CONFIRMATION,
    DemoTradingError,
    DemoTradingStore,
    _decimal_text,
    _normalize_account_id,
    _normalize_pair,
    _normalize_side,
    _normalize_tif,
    _positive_decimal,
)


DEMO_TRADING_ORDER_SCHEMA_VERSION = "1"

_DEMO_ORDER_REQUEST_ID_RE = re.compile(
    r"^[A-Za-z0-9]"
    r"[A-Za-z0-9._:-]{7,127}$"
)


class DemoTradingOrderError(
    DemoTradingError
):
    """Isolated Demo order creation failed."""


class DemoTradingOrderConflict(
    DemoTradingOrderError
):
    """A Demo Trading request ID is bound to another intent."""


def _timestamp(
    value: str | None = None,
) -> str:
    return str(
        value
        or datetime.now(
            timezone.utc
        ).isoformat()
    ).strip()


def _normalize_request_id(
    value: str,
) -> str:
    request_id = str(
        value or ""
    ).strip()

    if not _DEMO_ORDER_REQUEST_ID_RE.fullmatch(
        request_id
    ):
        raise ValueError(
            "Invalid Demo Trading request ID"
        )

    return request_id


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
            "Invalid Demo Trading username"
        )

    return username


def _canonical_json(
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


def _fingerprint(
    value: Any,
) -> str:
    return hashlib.sha256(
        _canonical_json(
            value
        ).encode(
            "utf-8"
        )
    ).hexdigest()


def _demo_order_id(
    request_id: str,
) -> str:
    return (
        "demo-order-"
        + hashlib.sha256(
            request_id.encode(
                "utf-8"
            )
        ).hexdigest()[:24]
    )


def _normalize_scope(
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


class DemoTradingOrderStore:
    """
    Isolated persistent Demo limit-order creation.

    The create boundary performs one atomic local transaction:

      Wallet available -> Wallet locked
      + Demo order audit
      + Demo event

    No Gate transport exists here. There is no production
    trading repository, live credential reader, account-action
    policy, live rate limiter, production Trading lock, HTTP
    routing, reconciliation, cancellation or amendment.
    """

    def __init__(
        self,
        database_path: Path,
    ) -> None:
        self.database_path = Path(
            database_path
        )

        self.trading = DemoTradingStore(
            self.database_path
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
                demo_trading_orders (
                    request_id TEXT PRIMARY KEY,
                    demo_order_id TEXT NOT NULL UNIQUE,
                    username TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    price TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    total TEXT NOT NULL,
                    time_in_force TEXT NOT NULL,
                    funding_asset TEXT NOT NULL,
                    reserved_amount TEXT NOT NULL,
                    filled_amount TEXT NOT NULL,
                    remaining_amount TEXT NOT NULL,
                    status TEXT NOT NULL,
                    intent_hash TEXT NOT NULL,
                    intent_json TEXT NOT NULL,
                    preview_json TEXT NOT NULL,
                    balance_reserved INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,

                    FOREIGN KEY (
                        account_id
                    )
                    REFERENCES demo_wallet_accounts (
                        account_id
                    ),

                    FOREIGN KEY (
                        pair
                    )
                    REFERENCES demo_trading_markets (
                        pair
                    )
                );

            CREATE INDEX IF NOT EXISTS
                ix_demo_trading_orders_account_time
            ON demo_trading_orders (
                account_id,
                created_at DESC,
                request_id DESC
            );

            CREATE INDEX IF NOT EXISTS
                ix_demo_trading_orders_account_status
            ON demo_trading_orders (
                account_id,
                status,
                created_at DESC
            );

            CREATE TABLE IF NOT EXISTS
                demo_trading_order_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    details_json TEXT NOT NULL,
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
                ix_demo_trading_order_events_request
            ON demo_trading_order_events (
                request_id,
                id ASC
            );
            """
        )

    def ensure_ready(
        self,
    ) -> None:
        self.trading.ensure_ready()

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
                WHERE key = 'order_schema_version'
                """
            ).fetchone()

            order_count = int(
                db.execute(
                    """
                    SELECT COUNT(*)
                    FROM demo_trading_orders
                    """
                ).fetchone()[0]
            )

            event_count = int(
                db.execute(
                    """
                    SELECT COUNT(*)
                    FROM demo_trading_order_events
                    """
                ).fetchone()[0]
            )

            if marker is None:
                if (
                    order_count
                    or event_count
                ):
                    raise DemoTradingOrderError(
                        "Demo Trading order schema marker "
                        "is missing for non-empty state"
                    )

                db.execute(
                    """
                    INSERT INTO demo_trading_meta (
                        key,
                        value
                    )
                    VALUES (
                        'order_schema_version',
                        ?
                    )
                    """,
                    (
                        DEMO_TRADING_ORDER_SCHEMA_VERSION,
                    ),
                )

            elif (
                str(marker["value"])
                != DEMO_TRADING_ORDER_SCHEMA_VERSION
            ):
                raise DemoTradingOrderError(
                    "Unsupported Demo Trading order schema version"
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
    def _intent(
        *,
        request_id: str,
        username: str,
        account_id: str,
        pair: str,
        side: str,
        price: Decimal,
        amount: Decimal,
        time_in_force: str,
    ) -> dict[str, Any]:
        return {
            "operation":
                "demo_limit_order_create",
            "request_id":
                request_id,
            "username":
                username,
            "account_id":
                account_id,
            "pair":
                pair,
            "side":
                side,
            "price":
                _decimal_text(
                    price
                ),
            "amount":
                _decimal_text(
                    amount
                ),
            "time_in_force":
                time_in_force,
            "execution_mode":
                "demo",
        }

    @staticmethod
    def _row_payload(
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        return {
            "request_id":
                row["request_id"],
            "demo_order_id":
                row["demo_order_id"],
            "account_id":
                row["account_id"],
            "pair":
                row["pair"],
            "side":
                row["side"],
            "order_type":
                row["order_type"],
            "price":
                row["price"],
            "amount":
                row["amount"],
            "total":
                row["total"],
            "time_in_force":
                row["time_in_force"],
            "funding_asset":
                row["funding_asset"],
            "reserved_amount":
                row["reserved_amount"],
            "filled_amount":
                row["filled_amount"],
            "remaining_amount":
                row["remaining_amount"],
            "status":
                row["status"],
            "balance_reserved":
                bool(
                    row[
                        "balance_reserved"
                    ]
                ),
            "preview":
                _load_json(
                    row[
                        "preview_json"
                    ]
                ),
            "created_at":
                row["created_at"],
            "updated_at":
                row["updated_at"],
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
                True,
        }

    @staticmethod
    def _event_payload(
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        return {
            "id":
                int(row["id"]),
            "request_id":
                row["request_id"],
            "account_id":
                row["account_id"],
            "username":
                row["username"],
            "action":
                row["action"],
            "from_status":
                row["from_status"],
            "to_status":
                row["to_status"],
            "details":
                _load_json(
                    row[
                        "details_json"
                    ]
                ),
            "created_at":
                row["created_at"],
            "source":
                "demo",
        }

    @staticmethod
    def _existing_row(
        db: sqlite3.Connection,
        request_id: str,
    ) -> sqlite3.Row | None:
        return db.execute(
            """
            SELECT *
            FROM demo_trading_orders
            WHERE request_id = ?
            """,
            (
                request_id,
            ),
        ).fetchone()

    def _existing_response(
        self,
        row: sqlite3.Row,
        *,
        intent_hash: str,
    ) -> dict[str, Any]:
        if (
            str(
                row["intent_hash"]
            )
            != intent_hash
        ):
            raise DemoTradingOrderConflict(
                "Demo Trading request ID is already "
                "bound to a different order intent"
            )

        order = self._row_payload(
            row
        )

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
                False,
            "balance_reservation_performed":
                False,
            "idempotent_replay":
                True,
            "order":
                order,
        }

    def create_limit_order(
        self,
        *,
        request_id: str,
        username: str,
        account_id: str,
        pair: str,
        side: str,
        price: Decimal | str | int,
        amount: Decimal | str | int,
        time_in_force: str = "gtc",
        confirmation: str,
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

        normalized_account = (
            _normalize_account_id(
                account_id
            )
        )

        normalized_pair = (
            _normalize_pair(
                pair
            )
        )

        normalized_side = (
            _normalize_side(
                side
            )
        )

        normalized_price = (
            _positive_decimal(
                price,
                "price",
            )
        )

        normalized_amount = (
            _positive_decimal(
                amount,
                "amount",
            )
        )

        normalized_tif = (
            _normalize_tif(
                time_in_force
            )
        )

        intent = self._intent(
            request_id=
                normalized_request_id,
            username=
                normalized_username,
            account_id=
                normalized_account,
            pair=
                normalized_pair,
            side=
                normalized_side,
            price=
                normalized_price,
            amount=
                normalized_amount,
            time_in_force=
                normalized_tif,
        )

        intent_json = _canonical_json(
            intent
        )

        intent_hash = _fingerprint(
            intent
        )

        self.ensure_ready()

        # Idempotency lookup deliberately occurs BEFORE:
        #   confirmation validation,
        #   a fresh preview,
        #   or any balance read used for a new reservation.
        db = self._connect()

        try:
            existing = self._existing_row(
                db,
                normalized_request_id,
            )

        finally:
            db.close()

        if existing is not None:
            return self._existing_response(
                existing,
                intent_hash=
                    intent_hash,
            )

        if (
            str(
                confirmation or ""
            )
            != DEMO_TRADING_REQUIRED_CONFIRMATION
        ):
            raise DemoTradingOrderError(
                "Exact Demo Trading confirmation is required"
            )

        preview = (
            self.trading
            .preview_limit_order(
                account_id=
                    normalized_account,
                pair=
                    normalized_pair,
                side=
                    normalized_side,
                price=
                    normalized_price,
                amount=
                    normalized_amount,
                time_in_force=
                    normalized_tif,
            )
        )

        if (
            preview.get(
                "status"
            )
            != "ready"
            or preview.get(
                "demo_execution_ready"
            )
            is not True
        ):
            blockers = [
                str(item)
                for item in (
                    preview.get(
                        "blockers"
                    )
                    or []
                )
            ]

            raise DemoTradingOrderError(
                "Demo Trading preview rejected order"
                + (
                    ": "
                    + "; ".join(
                        blockers
                    )
                    if blockers
                    else ""
                )
            )

        preview_order = dict(
            preview.get(
                "order"
            )
            or {}
        )

        funds = dict(
            preview.get(
                "funds"
            )
            or {}
        )

        funding_asset = str(
            funds.get(
                "asset"
            )
            or ""
        ).strip().upper()

        required = _positive_decimal(
            funds.get(
                "required"
            ),
            "reservation",
        )

        total = _positive_decimal(
            preview_order.get(
                "total"
            ),
            "total",
        )

        if (
            str(
                preview.get(
                    "account_id"
                )
                or ""
            )
            != normalized_account
            or str(
                preview_order.get(
                    "side"
                )
                or ""
            )
            != normalized_side
            or str(
                preview_order.get(
                    "price"
                )
                or ""
            )
            != _decimal_text(
                normalized_price
            )
            or str(
                preview_order.get(
                    "amount"
                )
                or ""
            )
            != _decimal_text(
                normalized_amount
            )
            or str(
                preview_order.get(
                    "time_in_force"
                )
                or ""
            )
            != normalized_tif
            or not funding_asset
        ):
            raise DemoTradingOrderError(
                "Demo Trading preview identity mismatch"
            )

        created_at = _timestamp(
            occurred_at
        )

        with self._writer() as db:
            # Re-check after obtaining the write lock so concurrent
            # calls with the same request ID cannot double-reserve.
            existing = self._existing_row(
                db,
                normalized_request_id,
            )

            if existing is not None:
                return self._existing_response(
                    existing,
                    intent_hash=
                        intent_hash,
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
                    normalized_account,
                    funding_asset,
                ),
            ).fetchone()

            if balance is None:
                raise DemoTradingOrderError(
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

            if available < required:
                raise DemoTradingOrderError(
                    "Demo Wallet available balance changed "
                    "before order reservation"
                )

            available_after = (
                available
                - required
            )

            locked_after = (
                locked
                + required
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
                    normalized_account,
                    funding_asset,
                ),
            )

            demo_order_id = (
                _demo_order_id(
                    normalized_request_id
                )
            )

            db.execute(
                """
                INSERT INTO demo_trading_orders (
                    request_id,
                    demo_order_id,
                    username,
                    account_id,
                    pair,
                    side,
                    order_type,
                    price,
                    amount,
                    total,
                    time_in_force,
                    funding_asset,
                    reserved_amount,
                    filled_amount,
                    remaining_amount,
                    status,
                    intent_hash,
                    intent_json,
                    preview_json,
                    balance_reserved,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    'limit',
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    '0',
                    ?,
                    'open',
                    ?,
                    ?,
                    ?,
                    1,
                    ?,
                    ?
                )
                """,
                (
                    normalized_request_id,
                    demo_order_id,
                    normalized_username,
                    normalized_account,
                    normalized_pair,
                    normalized_side,
                    _decimal_text(
                        normalized_price
                    ),
                    _decimal_text(
                        normalized_amount
                    ),
                    _decimal_text(
                        total
                    ),
                    normalized_tif,
                    funding_asset,
                    _decimal_text(
                        required
                    ),
                    _decimal_text(
                        normalized_amount
                    ),
                    intent_hash,
                    intent_json,
                    _canonical_json(
                        preview
                    ),
                    created_at,
                    created_at,
                ),
            )

            event_details = {
                "demo":
                    True,
                "simulation":
                    True,
                "gate_read_performed":
                    False,
                "gate_write_performed":
                    False,
                "funding_asset":
                    funding_asset,
                "reserved_amount":
                    _decimal_text(
                        required
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
                VALUES (
                    ?,
                    ?,
                    ?,
                    'created',
                    '',
                    'open',
                    ?,
                    ?
                )
                """,
                (
                    normalized_request_id,
                    normalized_account,
                    normalized_username,
                    _canonical_json(
                        event_details
                    ),
                    created_at,
                ),
            )

            row = self._existing_row(
                db,
                normalized_request_id,
            )

            if row is None:
                raise DemoTradingOrderError(
                    "Demo Trading order audit was not created"
                )

            order = self._row_payload(
                row
            )

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
                True,
            "balance_reservation_performed":
                True,
            "idempotent_replay":
                False,
            "order":
                order,
        }

    def get_order(
        self,
        request_id: str,
        *,
        account_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        normalized_request_id = (
            _normalize_request_id(
                request_id
            )
        )

        scope = _normalize_scope(
            account_ids
        )

        with self._reader() as db:
            row = self._existing_row(
                db,
                normalized_request_id,
            )

        if row is None:
            raise KeyError(
                "Demo Trading order not found"
            )

        if (
            scope is not None
            and str(
                row["account_id"]
            )
            not in scope
        ):
            raise KeyError(
                "Demo Trading order not found"
            )

        return self._row_payload(
            row
        )

    def list_orders(
        self,
        *,
        account_ids: set[str] | None = None,
        limit: int = 100,
    ) -> list[
        dict[str, Any]
    ]:
        scope = _normalize_scope(
            account_ids
        )

        normalized_limit = max(
            1,
            min(
                int(limit),
                500,
            ),
        )

        with self._reader() as db:
            rows = db.execute(
                """
                SELECT *
                FROM demo_trading_orders
                ORDER BY
                    created_at DESC,
                    request_id DESC
                """
            ).fetchall()

        result = [
            self._row_payload(
                row
            )
            for row in rows
            if (
                scope is None
                or str(
                    row["account_id"]
                )
                in scope
            )
        ]

        return result[
            :normalized_limit
        ]

    def list_events(
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

        # Parent lookup enforces account scope before event access.
        self.get_order(
            normalized_request_id,
            account_ids=
                account_ids,
        )

        with self._reader() as db:
            rows = db.execute(
                """
                SELECT *
                FROM demo_trading_order_events
                WHERE request_id = ?
                ORDER BY id ASC
                """,
                (
                    normalized_request_id,
                ),
            ).fetchall()

        return [
            self._event_payload(
                row
            )
            for row in rows
        ]
