from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect

from app.config import Settings
from app.db import init_db
from app.migrations import migrate_database
from app.treasury_rate_limit import (
    TreasuryRateLimitExceeded,
    enforce_treasury_rate_limit,
    policy_for_action,
)
from app.treasury_transfer_locks import (
    acquire_transfer_lock,
    get_transfer_lock_for_request,
    release_transfer_lock,
)


@pytest.fixture(
    scope="module",
    autouse=True,
)
def _initialize_treasury_test_database():
    # This test module must also work when run alone.
    # Do not rely on another test or TestClient lifespan
    # to initialize the shared pytest SQLite database.
    init_db()


@pytest.fixture(autouse=True)
def _isolate_treasury_operational_state():
    from sqlalchemy import delete

    from app.db import session_scope
    from app.models import (
        TreasuryRateLimitEvent,
        TreasuryTransferOperationLock,
    )

    def clear() -> None:
        with session_scope() as db:
            db.execute(
                delete(
                    TreasuryTransferOperationLock
                )
            )
            db.execute(
                delete(
                    TreasuryRateLimitEvent
                )
            )

    # Every test gets an empty operational lock/rate
    # state. Request/reconciliation audit history is
    # deliberately left intact.
    clear()

    try:
        yield
    finally:
        clear()


def test_treasury_rate_limit_defaults() -> None:
    settings = Settings(_env_file=None)

    execute = policy_for_action(
        settings,
        "execute",
    )

    assert execute is not None
    assert execute.user_limit == 3
    assert execute.user_window_seconds == 600
    assert execute.account_limit == 5
    assert execute.account_window_seconds == 600

    reconcile = policy_for_action(
        settings,
        "reconcile",
    )

    assert reconcile is not None
    assert reconcile.user_limit == 20

    release = policy_for_action(
        settings,
        "lock_release",
    )

    assert release is not None
    assert release.user_limit == 2


def test_treasury_rate_limit_can_be_disabled() -> None:
    settings = Settings(
        _env_file=None,
        treasury_rate_limit_enabled=False,
    )

    assert (
        policy_for_action(
            settings,
            "execute",
        )
        is None
    )


def test_treasury_user_rate_limit() -> None:
    suffix = uuid4().hex

    settings = Settings(
        _env_file=None,
        treasury_rate_limit_enabled=True,
        treasury_execute_user_limit=2,
        treasury_execute_user_window_seconds=600,
        treasury_execute_account_limit=100,
        treasury_execute_account_window_seconds=600,
    )

    for _ in range(2):
        enforce_treasury_rate_limit(
            settings=settings,
            username=f"user-{suffix}",
            source_account_id=f"source-{suffix}",
            action="execute",
        )

    with pytest.raises(
        TreasuryRateLimitExceeded,
    ) as exc_info:
        enforce_treasury_rate_limit(
            settings=settings,
            username=f"user-{suffix}",
            source_account_id=f"source-{suffix}",
            action="execute",
        )

    assert exc_info.value.scope == "user"


def test_treasury_account_rate_limit() -> None:
    suffix = uuid4().hex

    settings = Settings(
        _env_file=None,
        treasury_rate_limit_enabled=True,
        treasury_execute_user_limit=100,
        treasury_execute_user_window_seconds=600,
        treasury_execute_account_limit=2,
        treasury_execute_account_window_seconds=600,
    )

    source_account_id = f"source-{suffix}"

    for index in range(2):
        enforce_treasury_rate_limit(
            settings=settings,
            username=f"user-{index}-{suffix}",
            source_account_id=source_account_id,
            action="execute",
        )

    with pytest.raises(
        TreasuryRateLimitExceeded,
    ) as exc_info:
        enforce_treasury_rate_limit(
            settings=settings,
            username=f"user-3-{suffix}",
            source_account_id=source_account_id,
            action="execute",
        )

    assert (
        exc_info.value.scope
        == "source_account"
    )


def test_transfer_lock_lookup_by_request() -> None:
    suffix = uuid4().hex
    request_id = f"treasury-lock-{suffix}"

    acquire_transfer_lock(
        source_account_id="arnold",
        currency="USDT",
        owner_request_id=request_id,
        username="admin",
    )

    try:
        lock = get_transfer_lock_for_request(
            request_id
        )

        assert lock is not None
        assert (
            lock["owner_request_id"]
            == request_id
        )
        assert (
            lock["source_account_id"]
            == "arnold"
        )

    finally:
        release_transfer_lock(
            source_account_id="arnold",
            currency="USDT",
            owner_request_id=request_id,
        )


def test_operational_migration_tables(
    tmp_path,
) -> None:
    db_path = (
        tmp_path
        / "treasury-operational.db"
    )

    engine = create_engine(
        f"sqlite:///{db_path}"
    )

    try:
        migrate_database(engine)

        names = set(
            inspect(engine).get_table_names()
        )

        assert (
            "treasury_rate_limit_events"
            in names
        )

        assert (
            "treasury_transfer_lock_resolutions"
            in names
        )

    finally:
        engine.dispose()


def _auth(
    username: str,
    password: str,
) -> dict[str, str]:
    import base64

    token = base64.b64encode(
        f"{username}:{password}".encode()
    ).decode()

    return {
        "Authorization": f"Basic {token}"
    }


def _create_unresolved_treasury_request(
    request_id: str,
    *,
    status: str = "uncertain",
    confidence: str | None = "inconclusive",
) -> None:
    from decimal import Decimal

    from sqlalchemy import select

    from app.db import session_scope
    from app.models import (
        TreasuryTransferReconciliation,
        TreasuryTransferRequest,
    )
    from app.treasury_transfer_audit import (
        record_simulation,
    )
    from app.treasury_transfer_locks import (
        acquire_transfer_lock,
    )

    record_simulation(
        request_id=request_id,
        source_account_id="arnold",
        destination_account_id="zolnode",
        username="arnold",
        currency="USDT",
        amount=Decimal("1"),
        payload={
            "operation": "test",
            "request_id": request_id,
        },
        response={
            "simulation": True,
        },
    )

    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryTransferRequest
            ).where(
                TreasuryTransferRequest.request_id
                == request_id
            )
        )

        assert row is not None

        row.simulation = False
        row.write_performed = True
        row.status = status
        row.completed_at = None

        if confidence is not None:
            db.add(
                TreasuryTransferReconciliation(
                    request_id=request_id,
                    source_account_id="arnold",
                    username="rootadmin",
                    outcome=(
                        "inconclusive"
                        if confidence
                        == "inconclusive"
                        else "pending"
                    ),
                    confidence=confidence,
                    gate_status="",
                    tx_id="",
                    summary=(
                        "Synthetic Treasury "
                        "reconciliation test"
                    ),
                    details_json="{}",
                )
            )

    acquire_transfer_lock(
        source_account_id="arnold",
        currency="USDT",
        owner_request_id=request_id,
        username="arnold",
    )


def test_manual_release_requires_super_admin() -> None:
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from app.main import app
    from app.treasury_transfer_locks import (
        get_transfer_lock_for_request,
    )

    request_id = (
        "treasury-release-auth-"
        + uuid4().hex
    )

    _create_unresolved_treasury_request(
        request_id
    )

    with TestClient(app) as client:
        response = client.post(
            (
                "/api/treasury/transfers/"
                f"{request_id}/lock/release"
            ),
            headers=_auth(
                "arnold",
                "arnold-test-password",
            ),
            json={
                "confirmation": (
                    "RELEASE TREASURY LOCK "
                    + request_id
                ),
                "reason": (
                    "This account operator must not "
                    "be permitted to release it."
                ),
            },
        )

    assert response.status_code == 403

    assert (
        get_transfer_lock_for_request(
            request_id
        )
        is not None
    )


def test_manual_release_requires_exact_confirmation() -> None:
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from app.main import app
    from app.treasury_transfer_locks import (
        get_transfer_lock_for_request,
    )

    request_id = (
        "treasury-release-confirm-"
        + uuid4().hex
    )

    _create_unresolved_treasury_request(
        request_id
    )

    with TestClient(app) as client:
        response = client.post(
            (
                "/api/treasury/transfers/"
                f"{request_id}/lock/release"
            ),
            headers=_auth(
                "rootadmin",
                "rootadmin-test-password",
            ),
            json={
                "confirmation": "RELEASE",
                "reason": (
                    "The confirmation must remain "
                    "bound to the request identifier."
                ),
            },
        )

    assert response.status_code == 400

    assert (
        get_transfer_lock_for_request(
            request_id
        )
        is not None
    )


def test_manual_release_refuses_pending() -> None:
    from uuid import uuid4

    import pytest

    from app.treasury_transfer_lock_resolution import (
        TreasuryLockResolutionError,
        manual_release_transfer_lock,
    )
    from app.treasury_transfer_locks import (
        get_transfer_lock_for_request,
    )

    request_id = (
        "treasury-release-pending-"
        + uuid4().hex
    )

    _create_unresolved_treasury_request(
        request_id,
        status="pending",
        confidence="provisional",
    )

    with pytest.raises(
        TreasuryLockResolutionError,
        match="only allowed for an uncertain",
    ):
        manual_release_transfer_lock(
            request_id=request_id,
            username="rootadmin",
            reason=(
                "Pending transfers must remain "
                "protected by their operation lock."
            ),
            live_armed=False,
        )

    assert (
        get_transfer_lock_for_request(
            request_id
        )
        is not None
    )


def test_manual_release_refuses_without_reconciliation() -> None:
    from uuid import uuid4

    import pytest

    from app.treasury_transfer_lock_resolution import (
        TreasuryLockResolutionError,
        manual_release_transfer_lock,
    )
    from app.treasury_transfer_locks import (
        get_transfer_lock_for_request,
    )

    request_id = (
        "treasury-release-noreconcile-"
        + uuid4().hex
    )

    _create_unresolved_treasury_request(
        request_id,
        confidence=None,
    )

    with pytest.raises(
        TreasuryLockResolutionError,
        match="Reconcile with Gate",
    ):
        manual_release_transfer_lock(
            request_id=request_id,
            username="rootadmin",
            reason=(
                "A reconciliation must exist before "
                "any unresolved lock is released."
            ),
            live_armed=False,
        )

    assert (
        get_transfer_lock_for_request(
            request_id
        )
        is not None
    )


def test_manual_release_refuses_while_armed() -> None:
    from uuid import uuid4

    import pytest

    from app.treasury_transfer_lock_resolution import (
        TreasuryLockResolutionError,
        manual_release_transfer_lock,
    )
    from app.treasury_transfer_locks import (
        get_transfer_lock_for_request,
    )

    request_id = (
        "treasury-release-armed-"
        + uuid4().hex
    )

    _create_unresolved_treasury_request(
        request_id
    )

    with pytest.raises(
        TreasuryLockResolutionError,
        match="must be disarmed",
    ):
        manual_release_transfer_lock(
            request_id=request_id,
            username="rootadmin",
            reason=(
                "Live Treasury must be disabled "
                "before manually releasing a lock."
            ),
            live_armed=True,
        )

    assert (
        get_transfer_lock_for_request(
            request_id
        )
        is not None
    )


def test_super_admin_can_release_inconclusive_lock() -> None:
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from app.main import app
    from app.treasury_transfer_audit import (
        get_transfer_request,
    )
    from app.treasury_transfer_lock_resolution import (
        list_lock_resolutions,
    )
    from app.treasury_transfer_locks import (
        get_transfer_lock_for_request,
    )

    request_id = (
        "treasury-release-success-"
        + uuid4().hex
    )

    _create_unresolved_treasury_request(
        request_id
    )

    with TestClient(app) as client:
        response = client.post(
            (
                "/api/treasury/transfers/"
                f"{request_id}/lock/release"
            ),
            headers=_auth(
                "rootadmin",
                "rootadmin-test-password",
            ),
            json={
                "confirmation": (
                    "RELEASE TREASURY LOCK "
                    + request_id
                ),
                "reason": (
                    "Synthetic test: Gate "
                    "reconciliation remained "
                    "inconclusive and Treasury is "
                    "confirmed disarmed."
                ),
            },
        )

    assert response.status_code == 200

    payload = response.json()

    assert payload["gate_write_performed"] is False
    assert payload["released"] is True

    assert (
        get_transfer_lock_for_request(
            request_id
        )
        is None
    )

    # Manual unlock must never rewrite the unresolved
    # financial history to "failed" or "success".
    record = get_transfer_request(request_id)

    assert record is not None
    assert record["status"] == "uncertain"
    assert record["write_performed"] is True

    resolutions = list_lock_resolutions(
        request_id
    )

    assert len(resolutions) == 1
    assert (
        resolutions[0]["decision"]
        == "released"
    )
    assert (
        resolutions[0][
            "prior_request_status"
        ]
        == "uncertain"
    )
    assert (
        resolutions[0][
            "reconciliation_outcome"
        ]
        == "inconclusive"
    )
