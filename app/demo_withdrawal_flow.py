from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

from .demo_auth import DEMO_ACCOUNT_IDS
from .demo_wallet import DemoWalletStateError
from .demo_withdrawal import DemoWithdrawalStore


DEMO_WITHDRAWAL_FLOW_SCHEMA_VERSION = "1"

_DEMO_WITHDRAWAL_REQUEST_ID_RE = re.compile(
    r"^[A-Za-z0-9]"
    r"[A-Za-z0-9._:-]{7,127}$"
)


class DemoWithdrawalFlowError(
    DemoWalletStateError
):
    """Demo withdrawal request/preflight state is invalid."""


class DemoWithdrawalIdempotencyConflict(
    DemoWithdrawalFlowError
):
    """A Demo withdrawal request ID is already bound elsewhere."""


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
            value
        )
        for value
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


def _normalize_request_id(
    value: str,
) -> str:
    request_id = str(
        value or ""
    ).strip()

    if not _DEMO_WITHDRAWAL_REQUEST_ID_RE.fullmatch(
        request_id
    ):
        raise ValueError(
            "Invalid Demo withdrawal request ID"
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
            "Invalid Demo withdrawal username"
        )

    return username


def _positive_decimal(
    value: Decimal | str | int,
) -> Decimal:
    try:
        amount = Decimal(
            str(
                value
            )
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ) as exc:
        raise ValueError(
            "Invalid Demo withdrawal amount"
        ) from exc

    if (
        not amount.is_finite()
        or amount <= 0
    ):
        raise ValueError(
            "Demo withdrawal amount must be positive"
        )

    return amount


def _decimal(
    value: Any,
    *,
    name: str,
) -> Decimal:
    try:
        result = Decimal(
            str(
                value
            )
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ) as exc:
        raise DemoWithdrawalFlowError(
            f"Invalid Demo withdrawal {name}"
        ) from exc

    if not result.is_finite():
        raise DemoWithdrawalFlowError(
            f"Invalid Demo withdrawal {name}"
        )

    return result


def _decimal_text(
    value: Decimal,
) -> str:
    text = format(
        value,
        "f",
    )

    if "." in text:
        text = (
            text.rstrip("0")
            .rstrip(".")
        )

    return text or "0"


def _precision_places(
    value: Decimal,
) -> int:
    normalized = value.normalize()

    exponent = int(
        normalized.as_tuple().exponent
    )

    return max(
        0,
        -exponent,
    )


def _timestamp(
    value: str | None = None,
) -> str:
    if value is None:
        moment = datetime.now(
            timezone.utc
        )

    else:
        text = str(
            value
        ).strip()

        if text.endswith("Z"):
            text = (
                text[:-1]
                + "+00:00"
            )

        try:
            moment = datetime.fromisoformat(
                text
            )

        except ValueError as exc:
            raise ValueError(
                "Invalid Demo withdrawal timestamp"
            ) from exc

        if moment.tzinfo is None:
            moment = moment.replace(
                tzinfo=timezone.utc
            )

        moment = moment.astimezone(
            timezone.utc
        )

    return moment.isoformat()


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


def _blocker(
    blocker_type: str,
    message: str,
) -> dict[str, str]:
    return {
        "type":
            blocker_type,
        "message":
            message,
    }


class DemoWithdrawalFlowStore:
    """
    Request/preflight layer for isolated Demo withdrawals.

    F6C1 intentionally stops before all money-moving lifecycle
    transitions. It can inspect Demo balances and persist immutable
    request snapshots only inside the dedicated Demo SQLite file.

    It has no Gate transport, no Treasury service, no production
    SQLAlchemy repository, no credential reader and no HTTP routing.
    """

    def __init__(
        self,
        database_path: Path,
    ) -> None:
        self.database_path = Path(
            database_path
        )

        self.registry = (
            DemoWithdrawalStore(
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
                demo_withdrawal_requests (
                    request_id TEXT PRIMARY KEY,
                    owner_account_id TEXT NOT NULL,
                    custody_account_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    destination_id TEXT NOT NULL,
                    recipient_id TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    chain TEXT NOT NULL,
                    address TEXT NOT NULL,
                    memo TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    estimated_fee TEXT NOT NULL,
                    recipient_amount TEXT NOT NULL,
                    conservative_funding_required TEXT NOT NULL,
                    minimum_jit_transfer TEXT NOT NULL,
                    jit_required INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    preflight_json TEXT NOT NULL,
                    destination_snapshot_json TEXT NOT NULL,
                    simulation INTEGER NOT NULL,
                    write_performed INTEGER NOT NULL,
                    balance_debited INTEGER NOT NULL,
                    demo_withdrawal_id TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY (
                        owner_account_id
                    )
                    REFERENCES demo_wallet_accounts (
                        account_id
                    ),
                    FOREIGN KEY (
                        destination_id
                    )
                    REFERENCES demo_withdrawal_destinations (
                        destination_id
                    )
                );

            CREATE INDEX IF NOT EXISTS
                ix_demo_withdrawal_requests_owner_time
            ON demo_withdrawal_requests (
                owner_account_id,
                created_at DESC,
                request_id
            );

            CREATE INDEX IF NOT EXISTS
                ix_demo_withdrawal_requests_owner_currency_status
            ON demo_withdrawal_requests (
                owner_account_id,
                currency,
                status,
                updated_at DESC
            );

            CREATE TABLE IF NOT EXISTS
                demo_withdrawal_request_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    owner_account_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (
                        request_id
                    )
                    REFERENCES demo_withdrawal_requests (
                        request_id
                    )
                    ON DELETE CASCADE
                );

            CREATE INDEX IF NOT EXISTS
                ix_demo_withdrawal_request_events_request_time
            ON demo_withdrawal_request_events (
                request_id,
                created_at ASC,
                id ASC
            );
            """
        )

    def ensure_ready(
        self,
    ) -> bool:
        self.registry.ensure_seeded()

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
                WHERE key = 'withdrawal_flow_schema_version'
                """
            ).fetchone()

            if marker is not None:
                version = str(
                    marker["value"]
                )

                if (
                    version
                    != DEMO_WITHDRAWAL_FLOW_SCHEMA_VERSION
                ):
                    raise DemoWithdrawalFlowError(
                        "Unsupported Demo withdrawal flow "
                        f"schema version: {version}"
                    )

                db.commit()
                return False

            request_count = int(
                db.execute(
                    """
                    SELECT COUNT(*)
                    FROM demo_withdrawal_requests
                    """
                ).fetchone()[0]
            )

            event_count = int(
                db.execute(
                    """
                    SELECT COUNT(*)
                    FROM demo_withdrawal_request_events
                    """
                ).fetchone()[0]
            )

            if (
                request_count
                or event_count
            ):
                raise DemoWithdrawalFlowError(
                    "Demo withdrawal flow metadata is "
                    "missing from non-empty state"
                )

            db.execute(
                """
                INSERT INTO demo_wallet_meta (
                    key,
                    value
                )
                VALUES (?, ?)
                """,
                (
                    "withdrawal_flow_schema_version",
                    DEMO_WITHDRAWAL_FLOW_SCHEMA_VERSION,
                ),
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
    def _request_row(
        row: sqlite3.Row,
    ) -> dict[
        str,
        Any,
    ]:
        return {
            "request_id":
                row["request_id"],
            "owner_account_id":
                row[
                    "owner_account_id"
                ],
            "custody_account_id":
                row[
                    "custody_account_id"
                ],
            "username":
                row["username"],
            "destination_id":
                row[
                    "destination_id"
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
            "amount":
                row["amount"],
            "estimated_fee":
                row[
                    "estimated_fee"
                ],
            "recipient_amount":
                row[
                    "recipient_amount"
                ],
            "conservative_funding_required":
                row[
                    "conservative_funding_required"
                ],
            "minimum_jit_transfer":
                row[
                    "minimum_jit_transfer"
                ],
            "jit_required":
                bool(
                    row[
                        "jit_required"
                    ]
                ),
            "status":
                row["status"],
            "request_hash":
                row[
                    "request_hash"
                ],
            "request":
                _load_json(
                    row[
                        "request_json"
                    ]
                ),
            "preflight":
                _load_json(
                    row[
                        "preflight_json"
                    ]
                ),
            "destination_snapshot":
                _load_json(
                    row[
                        "destination_snapshot_json"
                    ]
                ),
            "simulation":
                bool(
                    row[
                        "simulation"
                    ]
                ),
            "write_performed":
                bool(
                    row[
                        "write_performed"
                    ]
                ),
            "balance_debited":
                bool(
                    row[
                        "balance_debited"
                    ]
                ),
            "demo_withdrawal_id": (
                row[
                    "demo_withdrawal_id"
                ]
                or None
            ),
            "error":
                row["error"],
            "created_at":
                row["created_at"],
            "updated_at":
                row["updated_at"],
            "completed_at": (
                row[
                    "completed_at"
                ]
                or None
            ),
        }

    def _daily_debited_amount(
        self,
        *,
        owner_account_id: str,
        currency: str,
        as_of: str,
    ) -> Decimal:
        moment = datetime.fromisoformat(
            as_of
        )

        cutoff = (
            moment
            - timedelta(
                days=1
            )
        ).isoformat()

        with self._reader() as db:
            rows = db.execute(
                """
                SELECT amount
                FROM demo_withdrawal_requests
                WHERE owner_account_id = ?
                  AND currency = ?
                  AND balance_debited = 1
                  AND updated_at >= ?
                """,
                (
                    owner_account_id,
                    currency,
                    cutoff,
                ),
            ).fetchall()

        total = Decimal(
            "0"
        )

        for row in rows:
            total += _decimal(
                row["amount"],
                name=(
                    "historical withdrawal amount"
                ),
            )

        return total

    def preflight(
        self,
        *,
        owner_account_id: str,
        destination_id: str,
        currency: str,
        amount: Decimal | str | int,
        as_of: str | None = None,
    ) -> dict[
        str,
        Any,
    ]:
        owner = _normalize_account_id(
            owner_account_id
        )

        symbol = _normalize_currency(
            currency
        )

        amount_value = (
            _positive_decimal(
                amount
            )
        )

        amount_text = (
            _decimal_text(
                amount_value
            )
        )

        timestamp = _timestamp(
            as_of
        )

        destination = (
            self.registry.get_destination(
                destination_id,
                owner_account_ids={
                    owner
                },
            )
        )

        blockers: list[
            dict[
                str,
                str,
            ]
        ] = []

        if (
            destination["status"]
            != "approved"
        ):
            blockers.append(
                _blocker(
                    "destination_not_approved",
                    (
                        "The Demo withdrawal destination "
                        "is not approved."
                    ),
                )
            )

        destination_currency = (
            _normalize_currency(
                destination[
                    "currency"
                ]
            )
        )

        destination_chain = str(
            destination[
                "chain"
            ]
        ).strip().upper()

        if (
            destination_currency
            != symbol
        ):
            blockers.append(
                _blocker(
                    "destination_currency_mismatch",
                    (
                        "The selected currency does not "
                        "match the immutable Demo "
                        "withdrawal destination."
                    ),
                )
            )

        policies = (
            self.registry.list_policies(
                symbol
            )
        )

        policy = next(
            (
                item
                for item
                in policies
                if str(
                    item[
                        "chain"
                    ]
                ).upper()
                == destination_chain
            ),
            None,
        )

        if policy is None:
            blockers.append(
                _blocker(
                    "withdrawal_network_unavailable",
                    (
                        "The Demo withdrawal network is "
                        "not available for this currency."
                    ),
                )
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
            raise DemoWithdrawalFlowError(
                "Demo withdrawal asset state is missing"
            )

        available = _decimal(
            asset[
                "available"
            ],
            name="available balance",
        )

        locked = _decimal(
            asset[
                "locked"
            ],
            name="locked balance",
        )

        estimated_fee = Decimal(
            "0"
        )

        minimum = Decimal(
            "0"
        )

        maximum = Decimal(
            "0"
        )

        daily_limit = Decimal(
            "0"
        )

        decimal_places = 0

        requires_memo = False

        if policy is not None:
            estimated_fee = _decimal(
                policy[
                    "fixed_fee"
                ],
                name="fixed fee",
            )

            minimum = _decimal(
                policy[
                    "minimum_withdrawal"
                ],
                name="minimum withdrawal",
            )

            maximum = _decimal(
                policy[
                    "maximum_per_withdrawal"
                ],
                name=(
                    "maximum per withdrawal"
                ),
            )

            daily_limit = _decimal(
                policy[
                    "daily_limit"
                ],
                name="daily limit",
            )

            decimal_places = int(
                policy[
                    "decimal_places"
                ]
            )

            requires_memo = bool(
                policy[
                    "requires_memo"
                ]
            )

            if not bool(
                policy[
                    "withdraw_enabled"
                ]
            ):
                blockers.append(
                    _blocker(
                        "withdrawal_disabled",
                        (
                            "Demo withdrawals are disabled "
                            "for this network."
                        ),
                    )
                )

        recipient_amount = (
            amount_value
            - estimated_fee
        )

        if (
            policy is not None
            and _precision_places(
                amount_value
            ) > decimal_places
        ):
            blockers.append(
                _blocker(
                    "amount_precision_exceeded",
                    (
                        f"{symbol} withdrawal amount "
                        "exceeds the Demo network "
                        f"precision of {decimal_places} "
                        "decimal places."
                    ),
                )
            )

        if (
            policy is not None
            and amount_value
            > maximum
        ):
            blockers.append(
                _blocker(
                    "maximum_per_withdrawal_exceeded",
                    (
                        f"Requested {amount_text} {symbol} "
                        "exceeds the Demo maximum per "
                        "withdrawal of "
                        f"{_decimal_text(maximum)} "
                        f"{symbol}."
                    ),
                )
            )

        if amount_value > available:
            blockers.append(
                _blocker(
                    "insufficient_available_balance",
                    (
                        f"Requested {amount_text} {symbol}, "
                        "but only "
                        f"{_decimal_text(available)} "
                        f"{symbol} is available."
                    ),
                )
            )

        if recipient_amount <= 0:
            blockers.append(
                _blocker(
                    "recipient_amount_not_positive",
                    (
                        "The Demo withdrawal fee would "
                        "leave no positive recipient amount."
                    ),
                )
            )

        if (
            policy is not None
            and recipient_amount
            < minimum
        ):
            blockers.append(
                _blocker(
                    "recipient_below_minimum",
                    (
                        "The estimated recipient amount "
                        f"{_decimal_text(recipient_amount)} "
                        f"{symbol} is below the Demo "
                        "network minimum of "
                        f"{_decimal_text(minimum)} "
                        f"{symbol}."
                    ),
                )
            )

        daily_used = (
            self._daily_debited_amount(
                owner_account_id=owner,
                currency=symbol,
                as_of=timestamp,
            )
        )

        daily_remaining = max(
            Decimal(
                "0"
            ),
            daily_limit
            - daily_used,
        )

        if (
            policy is not None
            and amount_value
            > daily_remaining
        ):
            blockers.append(
                _blocker(
                    "daily_limit_exceeded",
                    (
                        f"Requested {amount_text} {symbol} "
                        "exceeds the remaining Demo "
                        "24-hour withdrawal allowance of "
                        f"{_decimal_text(daily_remaining)} "
                        f"{symbol}."
                    ),
                )
            )

        preflight_valid = not blockers

        destination_snapshot = {
            "destination_id":
                destination[
                    "destination_id"
                ],
            "owner_account_id":
                destination[
                    "owner_account_id"
                ],
            "recipient_id":
                destination[
                    "recipient_id"
                ],
            "currency":
                destination[
                    "currency"
                ],
            "chain":
                destination[
                    "chain"
                ],
            "address":
                destination[
                    "address"
                ],
            "memo":
                destination[
                    "memo"
                ],
            "label":
                destination[
                    "label"
                ],
            "status":
                destination[
                    "status"
                ],
            "verification_method":
                destination[
                    "verification_method"
                ],
        }

        return {
            "source":
                "demo",
            "simulation":
                True,
            "as_of":
                timestamp,
            "owner_account_id":
                owner,
            "custody_account_id":
                owner,
            "currency":
                symbol,
            "amount":
                amount_text,
            "preflight_valid":
                preflight_valid,
            "status": (
                "ready"
                if preflight_valid
                else "blocked"
            ),
            "errors":
                blockers,
            "operation_blockers":
                blockers,
            "destination":
                destination_snapshot,
            "fee": {
                "fee_model":
                    "fixed",
                "estimated_fee":
                    _decimal_text(
                        estimated_fee
                    ),
                "fee_is_inside_gross_amount":
                    True,
                "recipient_amount_estimate":
                    _decimal_text(
                        recipient_amount
                    ),
            },
            "funding": {
                "source_available":
                    _decimal_text(
                        available
                    ),
                "source_locked":
                    _decimal_text(
                        locked
                    ),
                "withdrawal_funding_available":
                    _decimal_text(
                        available
                    ),
                "conservative_funding_required":
                    amount_text,
                "minimum_jit_transfer":
                    "0",
                "jit_required":
                    False,
            },
            "limits": {
                "minimum_recipient_amount":
                    _decimal_text(
                        minimum
                    ),
                "maximum_per_withdrawal":
                    _decimal_text(
                        maximum
                    ),
                "daily_limit":
                    _decimal_text(
                        daily_limit
                    ),
                "daily_used":
                    _decimal_text(
                        daily_used
                    ),
                "daily_remaining":
                    _decimal_text(
                        daily_remaining
                    ),
                "withdrawal_precision":
                    decimal_places,
                "requires_memo":
                    requires_memo,
            },
            "demo_withdrawals_enabled":
                True,
            "withdrawals_enabled":
                False,
            "gate_read_performed":
                False,
            "gate_write_performed":
                False,
        }

    def _existing_request(
        self,
        request_id: str,
    ) -> dict[
        str,
        Any,
    ] | None:
        with self._reader() as db:
            row = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_requests
                WHERE request_id = ?
                """,
                (
                    request_id,
                ),
            ).fetchone()

        if row is None:
            return None

        return self._request_row(
            row
        )

    @staticmethod
    def _assert_matching_request(
        existing: dict[
            str,
            Any,
        ],
        fingerprint: str,
    ) -> None:
        if (
            existing[
                "request_hash"
            ]
            != fingerprint
        ):
            raise (
                DemoWithdrawalIdempotencyConflict(
                    "Demo withdrawal request ID is "
                    "already bound to a different "
                    "withdrawal operation"
                )
            )

    @staticmethod
    def _replay_response(
        existing: dict[
            str,
            Any,
        ],
    ) -> dict[
        str,
        Any,
    ]:
        return {
            "phase":
                "DEMO_WITHDRAWAL_REQUEST_AUDIT",
            "status":
                "simulated_replay",
            "simulation":
                True,
            "idempotent_replay":
                True,
            "current_preflight_rechecked":
                False,
            "audit_recorded":
                True,
            "audit_created":
                False,
            "gate_read_performed":
                False,
            "gate_write_performed":
                False,
            "withdrawals_enabled":
                False,
            "demo_withdrawals_enabled":
                True,
            "executable":
                False,
            "audit":
                existing,
            "preflight":
                existing[
                    "preflight"
                ],
        }

    def create_request(
        self,
        *,
        request_id: str,
        owner_account_id: str,
        destination_id: str,
        currency: str,
        amount: Decimal | str | int,
        username: str = "demo",
        occurred_at: str | None = None,
    ) -> dict[
        str,
        Any,
    ]:
        normalized_request_id = (
            _normalize_request_id(
                request_id
            )
        )

        owner = _normalize_account_id(
            owner_account_id
        )

        symbol = _normalize_currency(
            currency
        )

        amount_value = (
            _positive_decimal(
                amount
            )
        )

        amount_text = (
            _decimal_text(
                amount_value
            )
        )

        normalized_username = (
            _normalize_username(
                username
            )
        )

        normalized_destination_id = str(
            destination_id
            or ""
        ).strip()

        if not normalized_destination_id:
            raise ValueError(
                "Demo withdrawal destination ID "
                "is required"
            )

        request_payload = {
            "operation":
                "external_withdrawal_simulation",
            "request_id":
                normalized_request_id,
            "owner_account_id":
                owner,
            "custody_account_id":
                owner,
            "destination_id":
                normalized_destination_id,
            "currency":
                symbol,
            "amount":
                amount_text,
            "username":
                normalized_username,
            "demo":
                True,
        }

        fingerprint = _fingerprint(
            request_payload
        )

        existing = self._existing_request(
            normalized_request_id
        )

        if existing is not None:
            self._assert_matching_request(
                existing,
                fingerprint,
            )

            return (
                self._replay_response(
                    existing
                )
            )

        preflight = self.preflight(
            owner_account_id=owner,
            destination_id=(
                normalized_destination_id
            ),
            currency=symbol,
            amount=amount_value,
            as_of=occurred_at,
        )

        base_response = {
            "phase":
                "DEMO_WITHDRAWAL_REQUEST_AUDIT",
            "status": (
                "ready"
                if preflight[
                    "preflight_valid"
                ]
                else "invalid"
            ),
            "simulation":
                True,
            "idempotent_replay":
                False,
            "current_preflight_rechecked":
                True,
            "gate_read_performed":
                False,
            "gate_write_performed":
                False,
            "withdrawals_enabled":
                False,
            "demo_withdrawals_enabled":
                True,
            "executable":
                False,
            "preflight":
                preflight,
        }

        if not preflight[
            "preflight_valid"
        ]:
            return {
                **base_response,
                "audit_recorded":
                    False,
                "audit_created":
                    False,
            }

        destination = dict(
            preflight[
                "destination"
            ]
        )

        fee = dict(
            preflight[
                "fee"
            ]
        )

        funding = dict(
            preflight[
                "funding"
            ]
        )

        timestamp = _timestamp(
            occurred_at
        )

        with self._writer() as db:
            race_row = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_requests
                WHERE request_id = ?
                """,
                (
                    normalized_request_id,
                ),
            ).fetchone()

            if race_row is not None:
                race_existing = (
                    self._request_row(
                        race_row
                    )
                )

                self._assert_matching_request(
                    race_existing,
                    fingerprint,
                )

                return (
                    self._replay_response(
                        race_existing
                    )
                )

            db.execute(
                """
                INSERT INTO demo_withdrawal_requests (
                    request_id,
                    owner_account_id,
                    custody_account_id,
                    username,
                    destination_id,
                    recipient_id,
                    currency,
                    chain,
                    address,
                    memo,
                    amount,
                    estimated_fee,
                    recipient_amount,
                    conservative_funding_required,
                    minimum_jit_transfer,
                    jit_required,
                    status,
                    request_hash,
                    request_json,
                    preflight_json,
                    destination_snapshot_json,
                    simulation,
                    write_performed,
                    balance_debited,
                    demo_withdrawal_id,
                    error,
                    created_at,
                    updated_at,
                    completed_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    normalized_request_id,
                    owner,
                    owner,
                    normalized_username,
                    destination[
                        "destination_id"
                    ],
                    destination[
                        "recipient_id"
                    ],
                    symbol,
                    destination[
                        "chain"
                    ],
                    destination[
                        "address"
                    ],
                    destination.get(
                        "memo"
                    )
                    or "",
                    amount_text,
                    fee[
                        "estimated_fee"
                    ],
                    fee[
                        "recipient_amount_estimate"
                    ],
                    funding[
                        "conservative_funding_required"
                    ],
                    funding[
                        "minimum_jit_transfer"
                    ],
                    int(
                        bool(
                            funding[
                                "jit_required"
                            ]
                        )
                    ),
                    "simulated",
                    fingerprint,
                    _canonical_json(
                        request_payload
                    ),
                    _canonical_json(
                        preflight
                    ),
                    _canonical_json(
                        destination
                    ),
                    1,
                    0,
                    0,
                    "",
                    "",
                    timestamp,
                    timestamp,
                    None,
                ),
            )

            db.execute(
                """
                INSERT INTO demo_withdrawal_request_events (
                    request_id,
                    owner_account_id,
                    username,
                    action,
                    from_status,
                    to_status,
                    details_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_request_id,
                    owner,
                    normalized_username,
                    "simulated",
                    "",
                    "simulated",
                    _canonical_json(
                        {
                            "demo":
                                True,
                            "preflight":
                                preflight,
                            "gate_read_performed":
                                False,
                            "gate_write_performed":
                                False,
                        }
                    ),
                    timestamp,
                ),
            )

            row = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_requests
                WHERE request_id = ?
                """,
                (
                    normalized_request_id,
                ),
            ).fetchone()

        assert row is not None

        audit = self._request_row(
            row
        )

        return {
            **base_response,
            "audit_recorded":
                True,
            "audit_created":
                True,
            "audit":
                audit,
        }

    def list_requests(
        self,
        *,
        account_ids: set[str] | None = None,
        limit: int = 50,
    ) -> list[
        dict[
            str,
            Any,
        ]
    ]:
        if (
            limit < 1
            or limit > 200
        ):
            raise ValueError(
                "Demo withdrawal request limit "
                "must be between 1 and 200"
            )

        scope = _normalize_account_scope(
            account_ids
        )

        if (
            scope is not None
            and not scope
        ):
            return []

        with self._reader() as db:
            rows = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_requests
                ORDER BY
                    created_at DESC,
                    request_id ASC
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

            result.append(
                self._request_row(
                    row
                )
            )

            if len(result) >= limit:
                break

        return result

    def get_request(
        self,
        request_id: str,
        *,
        account_ids: set[str] | None = None,
    ) -> dict[
        str,
        Any,
    ]:
        normalized_request_id = (
            _normalize_request_id(
                request_id
            )
        )

        scope = _normalize_account_scope(
            account_ids
        )

        with self._reader() as db:
            row = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_requests
                WHERE request_id = ?
                """,
                (
                    normalized_request_id,
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
                "Demo withdrawal request not found"
            )

        return self._request_row(
            row
        )

    def list_request_events(
        self,
        request_id: str,
    ) -> list[
        dict[
            str,
            Any,
        ]
    ]:
        normalized_request_id = (
            _normalize_request_id(
                request_id
            )
        )

        with self._reader() as db:
            exists = db.execute(
                """
                SELECT request_id
                FROM demo_withdrawal_requests
                WHERE request_id = ?
                """,
                (
                    normalized_request_id,
                ),
            ).fetchone()

            if exists is None:
                raise KeyError(
                    "Demo withdrawal request not found"
                )

            rows = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_request_events
                WHERE request_id = ?
                ORDER BY
                    created_at ASC,
                    id ASC
                """,
                (
                    normalized_request_id,
                ),
            ).fetchall()

        return [
            {
                "id":
                    int(
                        row["id"]
                    ),
                "request_id":
                    row[
                        "request_id"
                    ],
                "owner_account_id":
                    row[
                        "owner_account_id"
                    ],
                "username":
                    row[
                        "username"
                    ],
                "action":
                    row["action"],
                "from_status":
                    row[
                        "from_status"
                    ],
                "to_status":
                    row[
                        "to_status"
                    ],
                "details":
                    _load_json(
                        row[
                            "details_json"
                        ]
                    ),
                "created_at":
                    row[
                        "created_at"
                    ],
            }
            for row
            in rows
        ]
