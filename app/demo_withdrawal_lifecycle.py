from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from .demo_withdrawal_flow import (
    DemoWithdrawalFlowError,
    DemoWithdrawalFlowStore,
    _canonical_json,
    _decimal,
    _decimal_text,
    _normalize_request_id,
    _normalize_username,
    _timestamp,
)


class DemoWithdrawalLifecycleError(
    DemoWithdrawalFlowError
):
    """A Demo withdrawal lifecycle transition is invalid."""


class DemoWithdrawalLocked(
    DemoWithdrawalLifecycleError
):
    """Another unresolved Demo withdrawal owns this Wallet/currency lock."""


def _short_ref(
    request_id: str,
) -> str:
    return hashlib.sha256(
        request_id.encode(
            "utf-8"
        )
    ).hexdigest()[:16]


def demo_withdrawal_reservation_confirmation_text(
    request_id: str,
) -> str:
    normalized = _normalize_request_id(
        request_id
    )

    return (
        "RESERVE DEMO WITHDRAWAL "
        + normalized
    )


def demo_withdrawal_confirmation_text(
    request: dict[str, Any],
) -> str:
    request_id = _normalize_request_id(
        request["request_id"]
    )

    owner = str(
        request[
            "owner_account_id"
        ]
    ).strip().lower()

    currency = str(
        request["currency"]
    ).strip().upper()

    amount = _decimal_text(
        _decimal(
            request["amount"],
            name="amount",
        )
    )

    chain = str(
        request["chain"]
    ).strip().upper()

    destination_id = str(
        request[
            "destination_id"
        ]
    ).strip()

    if (
        not owner
        or not currency
        or not chain
        or not destination_id
    ):
        raise DemoWithdrawalLifecycleError(
            "Demo withdrawal confirmation "
            "cannot be built from incomplete state"
        )

    return " ".join(
        (
            "CONFIRM DEMO WITHDRAWAL",
            request_id,
            owner,
            currency,
            amount,
            chain,
            destination_id,
        )
    )


def demo_withdrawal_jit_preparation_confirmation_text(
    request_id: str,
) -> str:
    normalized = _normalize_request_id(
        request_id
    )

    return (
        "PREPARE DEMO WITHDRAWAL JIT "
        + normalized
    )


def demo_withdrawal_jit_execution_confirmation_text(
    request: dict[str, Any],
) -> str:
    request_id = _normalize_request_id(
        request["request_id"]
    )

    owner = str(
        request[
            "owner_account_id"
        ]
    ).strip().lower()

    currency = str(
        request["currency"]
    ).strip().upper()

    if (
        not owner
        or not currency
    ):
        raise DemoWithdrawalLifecycleError(
            "Demo withdrawal JIT confirmation "
            "cannot be built from incomplete state"
        )

    return " ".join(
        (
            "READY DEMO WITHDRAWAL NO-JIT",
            owner,
            currency,
            "0",
            "TO",
            owner,
            "REF",
            _short_ref(
                request_id
            ),
        )
    )


def demo_withdrawal_execution_confirmation_text(
    request: dict[str, Any],
) -> str:
    request_id = _normalize_request_id(
        request["request_id"]
    )

    owner = str(
        request[
            "owner_account_id"
        ]
    ).strip().lower()

    currency = str(
        request["currency"]
    ).strip().upper()

    amount = _decimal_text(
        _decimal(
            request["amount"],
            name="amount",
        )
    )

    chain = str(
        request["chain"]
    ).strip().upper()

    destination_id = str(
        request[
            "destination_id"
        ]
    ).strip()

    if (
        not owner
        or not currency
        or not chain
        or not destination_id
    ):
        raise DemoWithdrawalLifecycleError(
            "Demo withdrawal execution confirmation "
            "cannot be built from incomplete state"
        )

    result = " ".join(
        (
            "SIMULATE WITHDRAWAL",
            owner,
            currency,
            amount,
            chain,
            "TO",
            destination_id,
            "REF",
            _short_ref(
                request_id
            ),
        )
    )

    if len(result) > 255:
        raise DemoWithdrawalLifecycleError(
            "Demo withdrawal execution confirmation "
            "exceeds 255 characters"
        )

    return result


def _demo_withdrawal_id(
    request_id: str,
) -> str:
    return (
        "demo-withdrawal-"
        + hashlib.sha256(
            request_id.encode(
                "utf-8"
            )
        ).hexdigest()[:24]
    )


class DemoWithdrawalLifecycleStore:
    """
    Money-moving lifecycle for isolated Demo withdrawals.

    All state is confined to the Demo SQLite database.

    The only balance mutation in this module is the final
    simulated external withdrawal. It uses BEGIN IMMEDIATE
    and commits the Wallet debit, audit transition, event and
    operation-lock release atomically.

    There is no Gate transport, production repository,
    credential reader, Treasury service, or HTTP routing.
    """

    def __init__(
        self,
        database_path: Path,
    ) -> None:
        self.database_path = Path(
            database_path
        )

        self.flow = DemoWithdrawalFlowStore(
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
                demo_withdrawal_locks (
                    owner_account_id TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    owner_request_id TEXT NOT NULL UNIQUE,
                    username TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    PRIMARY KEY (
                        owner_account_id,
                        currency
                    ),
                    FOREIGN KEY (
                        owner_request_id
                    )
                    REFERENCES demo_withdrawal_requests (
                        request_id
                    )
                    ON DELETE CASCADE,
                    FOREIGN KEY (
                        owner_account_id
                    )
                    REFERENCES demo_wallet_accounts (
                        account_id
                    )
                );
            """
        )

    def ensure_ready(
        self,
    ) -> None:
        self.flow.ensure_ready()

        db = self._connect()

        try:
            db.execute(
                "BEGIN IMMEDIATE"
            )

            self._initialize_schema(
                db
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

    def _request_from_row(
        self,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        return self.flow._request_row(
            row
        )

    def _request_in_db(
        self,
        db: sqlite3.Connection,
        request_id: str,
    ) -> sqlite3.Row:
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
            raise KeyError(
                "Demo withdrawal request not found"
            )

        return row

    @staticmethod
    def _lock_payload(
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        return {
            "owner_account_id":
                row[
                    "owner_account_id"
                ],
            "currency":
                row["currency"],
            "owner_request_id":
                row[
                    "owner_request_id"
                ],
            "username":
                row["username"],
            "acquired_at":
                row["acquired_at"],
            "source":
                "demo",
        }

    def get_lock(
        self,
        request_id: str,
    ) -> dict[str, Any] | None:
        normalized = _normalize_request_id(
            request_id
        )

        with self._reader() as db:
            row = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_locks
                WHERE owner_request_id = ?
                """,
                (
                    normalized,
                ),
            ).fetchone()

        if row is None:
            return None

        return self._lock_payload(
            row
        )

    def list_locks(
        self,
    ) -> list[
        dict[str, Any]
    ]:
        with self._reader() as db:
            rows = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_locks
                ORDER BY
                    acquired_at ASC,
                    owner_request_id ASC
                """
            ).fetchall()

        return [
            self._lock_payload(
                row
            )
            for row
            in rows
        ]

    def _require_lock(
        self,
        db: sqlite3.Connection,
        request: dict[str, Any],
    ) -> sqlite3.Row:
        row = db.execute(
            """
            SELECT *
            FROM demo_withdrawal_locks
            WHERE owner_account_id = ?
              AND currency = ?
            """,
            (
                request[
                    "owner_account_id"
                ],
                request[
                    "currency"
                ],
            ),
        ).fetchone()

        if (
            row is None
            or row[
                "owner_request_id"
            ]
            != request[
                "request_id"
            ]
        ):
            raise DemoWithdrawalLifecycleError(
                "Demo withdrawal request does not own "
                "its Wallet/currency operation lock"
            )

        return row

    @staticmethod
    def _insert_event(
        db: sqlite3.Connection,
        *,
        request: dict[str, Any],
        username: str,
        action: str,
        from_status: str,
        to_status: str,
        details: dict[str, Any],
        created_at: str,
    ) -> None:
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
                request[
                    "request_id"
                ],
                request[
                    "owner_account_id"
                ],
                username,
                action,
                from_status,
                to_status,
                _canonical_json(
                    {
                        **details,
                        "demo":
                            True,
                        "gate_read_performed":
                            False,
                        "gate_write_performed":
                            False,
                    }
                ),
                created_at,
            ),
        )

    @staticmethod
    def _snapshot_mismatches(
        request: dict[str, Any],
        preflight: dict[str, Any],
    ) -> list[str]:
        current = dict(
            preflight.get(
                "destination"
            )
            or {}
        )

        stored = dict(
            request.get(
                "destination_snapshot"
            )
            or {}
        )

        fields = (
            "destination_id",
            "owner_account_id",
            "recipient_id",
            "currency",
            "chain",
            "address",
            "memo",
        )

        return [
            field
            for field
            in fields
            if str(
                stored.get(
                    field
                )
                or ""
            )
            != str(
                current.get(
                    field
                )
                or ""
            )
        ]

    def _fresh_preflight(
        self,
        request: dict[str, Any],
        *,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        preflight = self.flow.preflight(
            owner_account_id=(
                request[
                    "owner_account_id"
                ]
            ),
            destination_id=(
                request[
                    "destination_id"
                ]
            ),
            currency=(
                request[
                    "currency"
                ]
            ),
            amount=(
                request[
                    "amount"
                ]
            ),
            as_of=occurred_at,
        )

        if not preflight[
            "preflight_valid"
        ]:
            raise DemoWithdrawalLifecycleError(
                "Fresh Demo withdrawal preflight "
                "rejected the lifecycle transition"
            )

        mismatches = (
            self._snapshot_mismatches(
                request,
                preflight,
            )
        )

        if mismatches:
            raise DemoWithdrawalLifecycleError(
                "Fresh Demo withdrawal destination "
                "does not match the immutable request "
                "snapshot: "
                + ", ".join(
                    mismatches
                )
            )

        fresh_fee = _decimal(
            preflight[
                "fee"
            ][
                "estimated_fee"
            ],
            name="fresh fee",
        )

        stored_fee = _decimal(
            request[
                "estimated_fee"
            ],
            name="stored fee",
        )

        fresh_required = _decimal(
            preflight[
                "funding"
            ][
                "conservative_funding_required"
            ],
            name=(
                "fresh funding requirement"
            ),
        )

        stored_required = _decimal(
            request[
                "conservative_funding_required"
            ],
            name=(
                "stored funding requirement"
            ),
        )

        if (
            fresh_fee
            != stored_fee
            or fresh_required
            != stored_required
        ):
            raise DemoWithdrawalLifecycleError(
                "Fresh Demo withdrawal fee or funding "
                "requirement no longer matches the "
                "immutable request snapshot"
            )

        return preflight

    @staticmethod
    def _base_response(
        *,
        phase: str,
        status: str,
        replay: bool,
    ) -> dict[str, Any]:
        return {
            "phase":
                phase,
            "status":
                status,
            "simulation":
                True,
            "idempotent_replay":
                replay,
            "gate_read_performed":
                False,
            "gate_write_performed":
                False,
            "withdrawals_enabled":
                False,
            "demo_withdrawals_enabled":
                True,
        }

    def reserve(
        self,
        *,
        request_id: str,
        confirmation: str,
        username: str = "demo",
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_request_id(
            request_id
        )

        request = self.flow.get_request(
            normalized
        )

        if request[
            "status"
        ] == "reserved":
            return {
                **self._base_response(
                    phase=(
                        "DEMO_WITHDRAWAL_RESERVATION"
                    ),
                    status="reserved",
                    replay=True,
                ),
                "current_preflight_rechecked":
                    False,
                "reservation_created":
                    False,
                "audit":
                    request,
                "operation_lock":
                    self.get_lock(
                        normalized
                    ),
                "required_confirmation":
                    demo_withdrawal_confirmation_text(
                        request
                    ),
            }

        if request[
            "status"
        ] != "simulated":
            raise DemoWithdrawalLifecycleError(
                "Demo withdrawal request is not "
                "eligible for reservation"
            )

        required = (
            demo_withdrawal_reservation_confirmation_text(
                normalized
            )
        )

        if confirmation != required:
            raise DemoWithdrawalLifecycleError(
                "Invalid Demo withdrawal reservation "
                "confirmation text"
            )

        preflight = self._fresh_preflight(
            request,
            occurred_at=occurred_at,
        )

        username_value = _normalize_username(
            username
        )

        now = _timestamp(
            occurred_at
        )

        with self._writer() as db:
            row = self._request_in_db(
                db,
                normalized,
            )

            current = self._request_from_row(
                row
            )

            if current[
                "status"
            ] == "reserved":
                lock = self._require_lock(
                    db,
                    current,
                )

                return {
                    **self._base_response(
                        phase=(
                            "DEMO_WITHDRAWAL_RESERVATION"
                        ),
                        status="reserved",
                        replay=True,
                    ),
                    "current_preflight_rechecked":
                        False,
                    "reservation_created":
                        False,
                    "audit":
                        current,
                    "operation_lock":
                        self._lock_payload(
                            lock
                        ),
                    "required_confirmation":
                        demo_withdrawal_confirmation_text(
                            current
                        ),
                }

            if current[
                "status"
            ] != "simulated":
                raise DemoWithdrawalLifecycleError(
                    "Demo withdrawal request changed "
                    "before reservation"
                )

            conflict = db.execute(
                """
                SELECT *
                FROM demo_withdrawal_locks
                WHERE owner_account_id = ?
                  AND currency = ?
                """,
                (
                    current[
                        "owner_account_id"
                    ],
                    current[
                        "currency"
                    ],
                ),
            ).fetchone()

            if conflict is not None:
                if (
                    conflict[
                        "owner_request_id"
                    ]
                    != normalized
                ):
                    raise DemoWithdrawalLocked(
                        "Another unresolved Demo withdrawal "
                        "already owns this Wallet/currency "
                        "operation lock"
                    )

            else:
                db.execute(
                    """
                    INSERT INTO demo_withdrawal_locks (
                        owner_account_id,
                        currency,
                        owner_request_id,
                        username,
                        acquired_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        current[
                            "owner_account_id"
                        ],
                        current[
                            "currency"
                        ],
                        normalized,
                        username_value,
                        now,
                    ),
                )

            db.execute(
                """
                UPDATE demo_withdrawal_requests
                SET
                    status = 'reserved',
                    updated_at = ?
                WHERE request_id = ?
                """,
                (
                    now,
                    normalized,
                ),
            )

            self._insert_event(
                db,
                request=current,
                username=username_value,
                action="reserved",
                from_status="simulated",
                to_status="reserved",
                details={
                    "preflight":
                        preflight,
                },
                created_at=now,
            )

            updated_row = self._request_in_db(
                db,
                normalized,
            )

            updated = self._request_from_row(
                updated_row
            )

            lock_row = self._require_lock(
                db,
                updated,
            )

        return {
            **self._base_response(
                phase=(
                    "DEMO_WITHDRAWAL_RESERVATION"
                ),
                status="reserved",
                replay=False,
            ),
            "current_preflight_rechecked":
                True,
            "reservation_created":
                True,
            "audit":
                updated,
            "operation_lock":
                self._lock_payload(
                    lock_row
                ),
            "required_confirmation":
                demo_withdrawal_confirmation_text(
                    updated
                ),
        }

    def confirm(
        self,
        *,
        request_id: str,
        confirmation: str,
        username: str = "demo",
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_request_id(
            request_id
        )

        request = self.flow.get_request(
            normalized
        )

        if request[
            "status"
        ] == "confirmed_ready":
            return {
                **self._base_response(
                    phase=(
                        "DEMO_WITHDRAWAL_CONFIRMATION"
                    ),
                    status="confirmed_ready",
                    replay=True,
                ),
                "current_preflight_rechecked":
                    False,
                "confirmation_created":
                    False,
                "audit":
                    request,
                "operation_lock":
                    self.get_lock(
                        normalized
                    ),
            }

        if request[
            "status"
        ] != "reserved":
            raise DemoWithdrawalLifecycleError(
                "Demo withdrawal request must be "
                "reserved before confirmation"
            )

        lock = self.get_lock(
            normalized
        )

        if lock is None:
            raise DemoWithdrawalLifecycleError(
                "Reserved Demo withdrawal request "
                "has no operation lock"
            )

        required = (
            demo_withdrawal_confirmation_text(
                request
            )
        )

        if confirmation != required:
            raise DemoWithdrawalLifecycleError(
                "Invalid Demo withdrawal "
                "confirmation text"
            )

        preflight = self._fresh_preflight(
            request,
            occurred_at=occurred_at,
        )

        username_value = _normalize_username(
            username
        )

        now = _timestamp(
            occurred_at
        )

        with self._writer() as db:
            row = self._request_in_db(
                db,
                normalized,
            )

            current = self._request_from_row(
                row
            )

            if current[
                "status"
            ] == "confirmed_ready":
                lock_row = self._require_lock(
                    db,
                    current,
                )

                return {
                    **self._base_response(
                        phase=(
                            "DEMO_WITHDRAWAL_CONFIRMATION"
                        ),
                        status="confirmed_ready",
                        replay=True,
                    ),
                    "current_preflight_rechecked":
                        False,
                    "confirmation_created":
                        False,
                    "audit":
                        current,
                    "operation_lock":
                        self._lock_payload(
                            lock_row
                        ),
                }

            if current[
                "status"
            ] != "reserved":
                raise DemoWithdrawalLifecycleError(
                    "Demo withdrawal request changed "
                    "before confirmation"
                )

            lock_row = self._require_lock(
                db,
                current,
            )

            db.execute(
                """
                UPDATE demo_withdrawal_requests
                SET
                    status = 'confirmed_ready',
                    updated_at = ?
                WHERE request_id = ?
                """,
                (
                    now,
                    normalized,
                ),
            )

            self._insert_event(
                db,
                request=current,
                username=username_value,
                action="confirmed_ready",
                from_status="reserved",
                to_status="confirmed_ready",
                details={
                    "preflight":
                        preflight,
                },
                created_at=now,
            )

            updated = self._request_from_row(
                self._request_in_db(
                    db,
                    normalized,
                )
            )

        return {
            **self._base_response(
                phase=(
                    "DEMO_WITHDRAWAL_CONFIRMATION"
                ),
                status="confirmed_ready",
                replay=False,
            ),
            "current_preflight_rechecked":
                True,
            "confirmation_created":
                True,
            "audit":
                updated,
            "operation_lock":
                self._lock_payload(
                    lock_row
                ),
        }

    @staticmethod
    def _no_jit_plan(
        request: dict[str, Any],
    ) -> dict[str, Any]:
        owner = str(
            request[
                "owner_account_id"
            ]
        ).strip().lower()

        currency = str(
            request["currency"]
        ).strip().upper()

        return {
            "jit_required":
                False,
            "jit_amount_preview":
                "0",
            "jit_transfer_request_id":
                None,
            "source_account_id":
                owner,
            "custody_account_id":
                owner,
            "currency":
                currency,
            "derived_from_fresh_preflight":
                True,
            "amount_is_execution_authority":
                False,
            "gate_write_performed":
                False,
            "transfer_audit_created":
                False,
            "simulation":
                True,
        }

    def prepare_jit(
        self,
        *,
        request_id: str,
        confirmation: str,
        username: str = "demo",
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_request_id(
            request_id
        )

        request = self.flow.get_request(
            normalized
        )

        if request[
            "status"
        ] == "jit_prepared":
            plan = self._no_jit_plan(
                request
            )

            return {
                **self._base_response(
                    phase=(
                        "DEMO_WITHDRAWAL_JIT_PREPARATION"
                    ),
                    status="jit_prepared",
                    replay=True,
                ),
                "current_preflight_rechecked":
                    False,
                "jit_preparation_created":
                    False,
                "jit_execution_enabled":
                    True,
                "jit_plan":
                    plan,
                "required_execution_confirmation":
                    demo_withdrawal_jit_execution_confirmation_text(
                        request
                    ),
                "audit":
                    request,
                "operation_lock":
                    self.get_lock(
                        normalized
                    ),
            }

        if request[
            "status"
        ] != "confirmed_ready":
            raise DemoWithdrawalLifecycleError(
                "Demo withdrawal request must be "
                "confirmed before JIT preparation"
            )

        if self.get_lock(
            normalized
        ) is None:
            raise DemoWithdrawalLifecycleError(
                "Confirmed Demo withdrawal request "
                "has no operation lock"
            )

        required = (
            demo_withdrawal_jit_preparation_confirmation_text(
                normalized
            )
        )

        if confirmation != required:
            raise DemoWithdrawalLifecycleError(
                "Invalid Demo withdrawal JIT "
                "preparation confirmation text"
            )

        preflight = self._fresh_preflight(
            request,
            occurred_at=occurred_at,
        )

        plan = self._no_jit_plan(
            request
        )

        username_value = _normalize_username(
            username
        )

        now = _timestamp(
            occurred_at
        )

        with self._writer() as db:
            current = self._request_from_row(
                self._request_in_db(
                    db,
                    normalized,
                )
            )

            if current[
                "status"
            ] != "confirmed_ready":
                raise DemoWithdrawalLifecycleError(
                    "Demo withdrawal request changed "
                    "before JIT preparation"
                )

            lock_row = self._require_lock(
                db,
                current,
            )

            db.execute(
                """
                UPDATE demo_withdrawal_requests
                SET
                    status = 'jit_prepared',
                    updated_at = ?
                WHERE request_id = ?
                """,
                (
                    now,
                    normalized,
                ),
            )

            self._insert_event(
                db,
                request=current,
                username=username_value,
                action="jit_prepared",
                from_status="confirmed_ready",
                to_status="jit_prepared",
                details={
                    "preflight":
                        preflight,
                    "jit_plan":
                        plan,
                },
                created_at=now,
            )

            updated = self._request_from_row(
                self._request_in_db(
                    db,
                    normalized,
                )
            )

        return {
            **self._base_response(
                phase=(
                    "DEMO_WITHDRAWAL_JIT_PREPARATION"
                ),
                status="jit_prepared",
                replay=False,
            ),
            "current_preflight_rechecked":
                True,
            "jit_preparation_created":
                True,
            "jit_execution_enabled":
                True,
            "jit_plan":
                plan,
            "required_execution_confirmation":
                demo_withdrawal_jit_execution_confirmation_text(
                    updated
                ),
            "audit":
                updated,
            "operation_lock":
                self._lock_payload(
                    lock_row
                ),
        }

    def execute_jit(
        self,
        *,
        request_id: str,
        confirmation: str,
        username: str = "demo",
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_request_id(
            request_id
        )

        request = self.flow.get_request(
            normalized
        )

        if request[
            "status"
        ] == "jit_ready":
            return {
                **self._base_response(
                    phase=(
                        "DEMO_WITHDRAWAL_JIT_EXECUTION"
                    ),
                    status="jit_ready",
                    replay=True,
                ),
                "current_preflight_rechecked":
                    False,
                "jit_required":
                    False,
                "jit_transfer_performed":
                    False,
                "audit":
                    request,
                "operation_lock":
                    self.get_lock(
                        normalized
                    ),
                "required_execution_confirmation":
                    demo_withdrawal_execution_confirmation_text(
                        request
                    ),
            }

        if request[
            "status"
        ] != "jit_prepared":
            raise DemoWithdrawalLifecycleError(
                "Demo withdrawal request must be "
                "JIT-prepared before JIT execution"
            )

        if self.get_lock(
            normalized
        ) is None:
            raise DemoWithdrawalLifecycleError(
                "JIT-prepared Demo withdrawal request "
                "has no operation lock"
            )

        required = (
            demo_withdrawal_jit_execution_confirmation_text(
                request
            )
        )

        if confirmation != required:
            raise DemoWithdrawalLifecycleError(
                "Invalid Demo withdrawal JIT "
                "execution confirmation text"
            )

        preflight = self._fresh_preflight(
            request,
            occurred_at=occurred_at,
        )

        username_value = _normalize_username(
            username
        )

        now = _timestamp(
            occurred_at
        )

        with self._writer() as db:
            current = self._request_from_row(
                self._request_in_db(
                    db,
                    normalized,
                )
            )

            if current[
                "status"
            ] != "jit_prepared":
                raise DemoWithdrawalLifecycleError(
                    "Demo withdrawal request changed "
                    "before JIT execution"
                )

            lock_row = self._require_lock(
                db,
                current,
            )

            db.execute(
                """
                UPDATE demo_withdrawal_requests
                SET
                    status = 'jit_ready',
                    updated_at = ?
                WHERE request_id = ?
                """,
                (
                    now,
                    normalized,
                ),
            )

            self._insert_event(
                db,
                request=current,
                username=username_value,
                action="jit_not_required",
                from_status="jit_prepared",
                to_status="jit_ready",
                details={
                    "preflight":
                        preflight,
                    "jit_plan":
                        self._no_jit_plan(
                            current
                        ),
                    "jit_transfer_performed":
                        False,
                },
                created_at=now,
            )

            updated = self._request_from_row(
                self._request_in_db(
                    db,
                    normalized,
                )
            )

        return {
            **self._base_response(
                phase=(
                    "DEMO_WITHDRAWAL_JIT_EXECUTION"
                ),
                status="jit_ready",
                replay=False,
            ),
            "current_preflight_rechecked":
                True,
            "jit_required":
                False,
            "jit_transfer_performed":
                False,
            "audit":
                updated,
            "operation_lock":
                self._lock_payload(
                    lock_row
                ),
            "required_execution_confirmation":
                demo_withdrawal_execution_confirmation_text(
                    updated
                ),
        }

    def execute(
        self,
        *,
        request_id: str,
        confirmation: str,
        username: str = "demo",
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_request_id(
            request_id
        )

        request = self.flow.get_request(
            normalized
        )

        if request[
            "status"
        ] == "withdrawal_settled":
            return {
                **self._base_response(
                    phase=(
                        "DEMO_WITHDRAWAL_EXECUTION"
                    ),
                    status="withdrawal_settled",
                    replay=True,
                ),
                "current_preflight_rechecked":
                    False,
                "local_write_performed":
                    False,
                "balance_debited":
                    bool(
                        request[
                            "balance_debited"
                        ]
                    ),
                "demo_withdrawal_id":
                    request[
                        "demo_withdrawal_id"
                    ],
                "audit":
                    request,
                "operation_lock":
                    None,
            }

        if request[
            "status"
        ] != "jit_ready":
            raise DemoWithdrawalLifecycleError(
                "Demo withdrawal request must be "
                "jit_ready before simulated execution"
            )

        if self.get_lock(
            normalized
        ) is None:
            raise DemoWithdrawalLifecycleError(
                "JIT-ready Demo withdrawal request "
                "has no operation lock"
            )

        required = (
            demo_withdrawal_execution_confirmation_text(
                request
            )
        )

        if confirmation != required:
            raise DemoWithdrawalLifecycleError(
                "Invalid Demo withdrawal execution "
                "confirmation text"
            )

        preflight = self._fresh_preflight(
            request,
            occurred_at=occurred_at,
        )

        username_value = _normalize_username(
            username
        )

        now = _timestamp(
            occurred_at
        )

        with self._writer() as db:
            row = self._request_in_db(
                db,
                normalized,
            )

            current = self._request_from_row(
                row
            )

            if current[
                "status"
            ] == "withdrawal_settled":
                return {
                    **self._base_response(
                        phase=(
                            "DEMO_WITHDRAWAL_EXECUTION"
                        ),
                        status="withdrawal_settled",
                        replay=True,
                    ),
                    "current_preflight_rechecked":
                        False,
                    "local_write_performed":
                        False,
                    "balance_debited":
                        bool(
                            current[
                                "balance_debited"
                            ]
                        ),
                    "demo_withdrawal_id":
                        current[
                            "demo_withdrawal_id"
                        ],
                    "audit":
                        current,
                    "operation_lock":
                        None,
                }

            if current[
                "status"
            ] != "jit_ready":
                raise DemoWithdrawalLifecycleError(
                    "Demo withdrawal request changed "
                    "before simulated execution"
                )

            self._require_lock(
                db,
                current,
            )

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
                    current[
                        "owner_account_id"
                    ],
                    current[
                        "currency"
                    ],
                ),
            ).fetchone()

            if asset is None:
                raise DemoWithdrawalLifecycleError(
                    "Demo Wallet asset state is missing"
                )

            available_before = _decimal(
                asset["available"],
                name="available balance",
            )

            locked_before = _decimal(
                asset["locked"],
                name="locked balance",
            )

            amount = _decimal(
                current["amount"],
                name="withdrawal amount",
            )

            if available_before < amount:
                raise DemoWithdrawalLifecycleError(
                    "Demo Wallet available balance changed "
                    "before simulated withdrawal execution"
                )

            available_after = (
                available_before
                - amount
            )

            withdrawal_id = (
                _demo_withdrawal_id(
                    normalized
                )
            )

            db.execute(
                """
                UPDATE demo_wallet_assets
                SET available = ?
                WHERE account_id = ?
                  AND currency = ?
                """,
                (
                    _decimal_text(
                        available_after
                    ),
                    current[
                        "owner_account_id"
                    ],
                    current[
                        "currency"
                    ],
                ),
            )

            db.execute(
                """
                UPDATE demo_withdrawal_requests
                SET
                    status = 'withdrawal_settled',
                    write_performed = 0,
                    balance_debited = 1,
                    demo_withdrawal_id = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE request_id = ?
                """,
                (
                    withdrawal_id,
                    now,
                    now,
                    normalized,
                ),
            )

            self._insert_event(
                db,
                request=current,
                username=username_value,
                action=(
                    "simulated_withdrawal_settled"
                ),
                from_status="jit_ready",
                to_status="withdrawal_settled",
                details={
                    "preflight":
                        preflight,
                    "gross_debit":
                        current[
                            "amount"
                        ],
                    "estimated_fee":
                        current[
                            "estimated_fee"
                        ],
                    "recipient_amount":
                        current[
                            "recipient_amount"
                        ],
                    "available_before":
                        _decimal_text(
                            available_before
                        ),
                    "available_after":
                        _decimal_text(
                            available_after
                        ),
                    "locked_before":
                        _decimal_text(
                            locked_before
                        ),
                    "locked_after":
                        _decimal_text(
                            locked_before
                        ),
                    "demo_withdrawal_id":
                        withdrawal_id,
                    "local_balance_write":
                        True,
                },
                created_at=now,
            )

            deleted = db.execute(
                """
                DELETE FROM demo_withdrawal_locks
                WHERE owner_request_id = ?
                """,
                (
                    normalized,
                ),
            )

            if deleted.rowcount != 1:
                raise DemoWithdrawalLifecycleError(
                    "Demo withdrawal operation lock "
                    "could not be released atomically"
                )

            updated = self._request_from_row(
                self._request_in_db(
                    db,
                    normalized,
                )
            )

        return {
            **self._base_response(
                phase=(
                    "DEMO_WITHDRAWAL_EXECUTION"
                ),
                status="withdrawal_settled",
                replay=False,
            ),
            "current_preflight_rechecked":
                True,
            "local_write_performed":
                True,
            "balance_debited":
                True,
            "gross_debit":
                updated[
                    "amount"
                ],
            "estimated_fee":
                updated[
                    "estimated_fee"
                ],
            "recipient_amount":
                updated[
                    "recipient_amount"
                ],
            "demo_withdrawal_id":
                updated[
                    "demo_withdrawal_id"
                ],
            "audit":
                updated,
            "operation_lock":
                None,
        }
