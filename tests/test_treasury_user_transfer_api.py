from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

import app.api.treasury as treasury_api
from app.config import Settings
from app.db import init_db, session_scope, utcnow
from app.models import TreasuryOwnershipLedgerEntry
from app.security import DashboardUser
from app.treasury_rate_limit import (
    policy_for_action,
)


@pytest.fixture(
    scope="module",
    autouse=True,
)
def _initialize_database():
    init_db()


def _dashboard_user(
    username: str,
    *account_ids: str,
    enabled: bool = True,
) -> DashboardUser:
    return DashboardUser(
        username=username,
        role="account_operator",
        account_ids=tuple(account_ids),
        enabled=enabled,
        password_hash="test",
    )


def _registered_users(
    source: str,
    destination: str,
):
    return (
        _dashboard_user("alice", source),
        _dashboard_user("bob", destination),
    )


def _seed(
    *,
    owner: str,
    amount: Decimal,
    suffix: str,
) -> None:
    with session_scope() as db:
        db.add(
            TreasuryOwnershipLedgerEntry(
                event_id=f"api-transfer-seed:{suffix}",
                owner_account_id=owner,
                custody_account_id="zolnode",
                currency="USDT",
                delta_amount=amount,
                entry_type="test_seed",
                source_request_id=(
                    f"api-transfer-seed:{suffix}"
                ),
                reason="API user-transfer test seed.",
                metadata_json=json.dumps(
                    {"test": True}
                ),
                created_at=utcnow(),
            )
        )


def test_user_transfer_rate_limit_policy():
    settings = Settings(_env_file=None)

    policy = policy_for_action(
        settings,
        "user_transfer",
    )

    assert policy is not None
    assert policy.user_limit == 10
    assert policy.user_window_seconds == 600
    assert policy.account_limit == 20
    assert policy.account_window_seconds == 600


def test_participants_are_registered_enabled_accounts(
    monkeypatch,
):
    source = "alice-account"
    destination = "bob-account"

    users = (
        *_registered_users(
            source,
            destination,
        ),
        _dashboard_user(
            "disabled",
            "disabled-account",
            enabled=False,
        ),
    )

    monkeypatch.setattr(
        treasury_api,
        "load_dashboard_users",
        lambda _settings=None: users,
    )

    monkeypatch.setattr(
        treasury_api,
        "settings",
        Settings(
            _env_file=None,
            treasury_user_transfers_enabled=False,
        ),
    )

    payload = (
        treasury_api
        .treasury_user_transfer_participants(
            users[0]
        )
    )

    ids = {
        item["account_id"]
        for item in payload["items"]
    }

    assert source in ids
    assert destination in ids
    assert "disabled-account" not in ids

    source_row = next(
        item
        for item in payload["items"]
        if item["account_id"] == source
    )

    destination_row = next(
        item
        for item in payload["items"]
        if item["account_id"] == destination
    )

    assert source_row["can_source"] is True
    assert destination_row["can_source"] is False
    assert payload["user_transfers_enabled"] is False
    assert payload["gate_write_performed"] is False


def test_preview_returns_exact_confirmation(
    monkeypatch,
):
    suffix = uuid4().hex
    source = f"alice-{suffix}"
    destination = f"bob-{suffix}"
    users = _registered_users(
        source,
        destination,
    )

    _seed(
        owner=source,
        amount=Decimal("5"),
        suffix=suffix,
    )

    monkeypatch.setattr(
        treasury_api,
        "load_dashboard_users",
        lambda _settings=None: users,
    )

    monkeypatch.setattr(
        treasury_api,
        "settings",
        Settings(
            _env_file=None,
            treasury_user_transfers_enabled=False,
        ),
    )

    request = (
        treasury_api
        .TreasuryUserTransferPreviewRequest(
            source_account_id=source,
            destination_account_id=destination,
            currency="USDT",
            amount=Decimal("2"),
        )
    )

    result = (
        treasury_api
        .preview_treasury_user_transfer(
            request,
            users[0],
        )
    )

    assert result["status"] == "ready"
    assert result["can_execute"] is False
    assert (
        result["required_confirmation"]
        == f"TRANSFER {source} 2 USDT TO {destination}"
    )
    assert result["preview"]["source_after"] == "3"
    assert (
        result["preview"]["destination_after"]
        == "2"
    )
    assert result["gate_write_performed"] is False


def test_execute_fails_closed_when_feature_disabled(
    monkeypatch,
):
    suffix = uuid4().hex
    source = f"alice-{suffix}"
    destination = f"bob-{suffix}"
    users = _registered_users(
        source,
        destination,
    )

    _seed(
        owner=source,
        amount=Decimal("5"),
        suffix=suffix,
    )

    monkeypatch.setattr(
        treasury_api,
        "load_dashboard_users",
        lambda _settings=None: users,
    )

    monkeypatch.setattr(
        treasury_api,
        "settings",
        Settings(
            _env_file=None,
            treasury_user_transfers_enabled=False,
            treasury_rate_limit_enabled=False,
        ),
    )

    confirmation = (
        f"TRANSFER {source} 2 USDT TO {destination}"
    )

    request = (
        treasury_api
        .TreasuryUserTransferExecutionRequest(
            request_id=f"user-transfer-{suffix}",
            source_account_id=source,
            destination_account_id=destination,
            currency="USDT",
            amount=Decimal("2"),
            confirmation=confirmation,
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        treasury_api.execute_treasury_user_transfer(
            request,
            users[0],
        )

    assert exc_info.value.status_code == 403
    assert (
        exc_info.value.detail["reason"]
        == "user_transfers_not_enabled"
    )


def test_execute_and_replay_without_gate_write(
    monkeypatch,
):
    suffix = uuid4().hex
    source = f"alice-{suffix}"
    destination = f"bob-{suffix}"
    users = _registered_users(
        source,
        destination,
    )

    _seed(
        owner=source,
        amount=Decimal("5"),
        suffix=suffix,
    )

    monkeypatch.setattr(
        treasury_api,
        "load_dashboard_users",
        lambda _settings=None: users,
    )

    monkeypatch.setattr(
        treasury_api,
        "settings",
        Settings(
            _env_file=None,
            treasury_user_transfers_enabled=True,
            treasury_rate_limit_enabled=False,
        ),
    )

    request_id = f"user-transfer-{suffix}"

    confirmation = (
        f"TRANSFER {source} 2 USDT TO {destination}"
    )

    request = (
        treasury_api
        .TreasuryUserTransferExecutionRequest(
            request_id=request_id,
            source_account_id=source,
            destination_account_id=destination,
            currency="USDT",
            amount=Decimal("2"),
            confirmation=confirmation,
        )
    )

    first = (
        treasury_api
        .execute_treasury_user_transfer(
            request,
            users[0],
        )
    )

    replay = (
        treasury_api
        .execute_treasury_user_transfer(
            request,
            users[0],
        )
    )

    assert first["status"] == "success"
    assert first["state_changed"] is True
    assert first["gate_write_performed"] is False

    assert replay["status"] == "success"
    assert replay["state_changed"] is False
    assert replay["idempotent_replay"] is True
    assert replay["gate_write_performed"] is False


def test_disabled_user_transfer_attempt_is_audited(
    monkeypatch,
):
    from app.treasury_transfer_audit import (
        get_transfer_request,
    )

    suffix = uuid4().hex
    source = f"alice-{suffix}"
    destination = f"bob-{suffix}"
    users = _registered_users(
        source,
        destination,
    )

    _seed(
        owner=source,
        amount=Decimal("5"),
        suffix=suffix,
    )

    monkeypatch.setattr(
        treasury_api,
        "load_dashboard_users",
        lambda _settings=None: users,
    )

    monkeypatch.setattr(
        treasury_api,
        "settings",
        Settings(
            _env_file=None,
            treasury_user_transfers_enabled=False,
            treasury_rate_limit_enabled=False,
        ),
    )

    request_id = f"user-transfer-{suffix}"

    request = (
        treasury_api
        .TreasuryUserTransferExecutionRequest(
            request_id=request_id,
            source_account_id=source,
            destination_account_id=destination,
            currency="USDT",
            amount=Decimal("1"),
            confirmation=(
                f"TRANSFER {source} 1 USDT "
                f"TO {destination}"
            ),
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        treasury_api.execute_treasury_user_transfer(
            request,
            users[0],
        )

    assert exc_info.value.status_code == 403

    audit = get_transfer_request(request_id)

    assert audit is not None
    assert audit["status"] == "blocked"
    assert audit["direction"] == "ownership"
    assert audit["write_performed"] is False
    assert (
        audit["request"]["operation"]
        == "user_ownership_transfer"
    )


def test_bad_confirmation_is_persistently_rejected(
    monkeypatch,
):
    from app.treasury_transfer_audit import (
        get_transfer_request,
    )

    suffix = uuid4().hex
    source = f"alice-{suffix}"
    destination = f"bob-{suffix}"
    users = _registered_users(
        source,
        destination,
    )

    _seed(
        owner=source,
        amount=Decimal("5"),
        suffix=suffix,
    )

    monkeypatch.setattr(
        treasury_api,
        "load_dashboard_users",
        lambda _settings=None: users,
    )

    monkeypatch.setattr(
        treasury_api,
        "settings",
        Settings(
            _env_file=None,
            treasury_user_transfers_enabled=True,
            treasury_rate_limit_enabled=False,
        ),
    )

    request_id = f"user-transfer-{suffix}"

    request = (
        treasury_api
        .TreasuryUserTransferExecutionRequest(
            request_id=request_id,
            source_account_id=source,
            destination_account_id=destination,
            currency="USDT",
            amount=Decimal("1"),
            confirmation="WRONG",
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        treasury_api.execute_treasury_user_transfer(
            request,
            users[0],
        )

    assert exc_info.value.status_code == 400

    audit = get_transfer_request(request_id)

    assert audit is not None
    assert audit["status"] == "rejected"
    assert audit["write_performed"] is False


def test_successful_user_transfer_has_persistent_audit(
    monkeypatch,
):
    from app.treasury_transfer_audit import (
        get_transfer_request,
        list_transfer_requests,
    )

    suffix = uuid4().hex
    source = f"alice-{suffix}"
    destination = f"bob-{suffix}"
    users = _registered_users(
        source,
        destination,
    )

    _seed(
        owner=source,
        amount=Decimal("5"),
        suffix=suffix,
    )

    monkeypatch.setattr(
        treasury_api,
        "load_dashboard_users",
        lambda _settings=None: users,
    )

    monkeypatch.setattr(
        treasury_api,
        "settings",
        Settings(
            _env_file=None,
            treasury_user_transfers_enabled=True,
            treasury_rate_limit_enabled=False,
        ),
    )

    request_id = f"user-transfer-{suffix}"

    confirmation = (
        f"TRANSFER {source} 2 USDT TO {destination}"
    )

    request = (
        treasury_api
        .TreasuryUserTransferExecutionRequest(
            request_id=request_id,
            source_account_id=source,
            destination_account_id=destination,
            currency="USDT",
            amount=Decimal("2"),
            confirmation=confirmation,
        )
    )

    result = (
        treasury_api
        .execute_treasury_user_transfer(
            request,
            users[0],
        )
    )

    assert result["status"] == "success"
    assert result["gate_write_performed"] is False

    audit = get_transfer_request(request_id)

    assert audit is not None
    assert audit["status"] == "success"
    assert audit["direction"] == "ownership"
    assert audit["write_performed"] is False
    assert audit["client_order_id"] is None

    incoming = list_transfer_requests(
        account_ids={destination},
        limit=200,
    )

    assert any(
        row["request_id"] == request_id
        for row in incoming
    )


def test_terminal_user_transfer_request_never_reexecutes(
    monkeypatch,
):
    suffix = uuid4().hex
    source = f"alice-{suffix}"
    destination = f"bob-{suffix}"
    users = _registered_users(
        source,
        destination,
    )

    _seed(
        owner=source,
        amount=Decimal("5"),
        suffix=suffix,
    )

    monkeypatch.setattr(
        treasury_api,
        "load_dashboard_users",
        lambda _settings=None: users,
    )

    monkeypatch.setattr(
        treasury_api,
        "settings",
        Settings(
            _env_file=None,
            treasury_user_transfers_enabled=True,
            treasury_rate_limit_enabled=False,
        ),
    )

    request_id = f"user-transfer-{suffix}"

    request = (
        treasury_api
        .TreasuryUserTransferExecutionRequest(
            request_id=request_id,
            source_account_id=source,
            destination_account_id=destination,
            currency="USDT",
            amount=Decimal("2"),
            confirmation=(
                f"TRANSFER {source} 2 USDT "
                f"TO {destination}"
            ),
        )
    )

    first = (
        treasury_api
        .execute_treasury_user_transfer(
            request,
            users[0],
        )
    )

    assert first["status"] == "success"

    monkeypatch.setattr(
        treasury_api,
        "execute_user_transfer",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "terminal replay attempted mutation"
            )
        ),
    )

    replay = (
        treasury_api
        .execute_treasury_user_transfer(
            request,
            users[0],
        )
    )

    assert replay["status"] == "success"
    assert replay["idempotent_replay"] is True
    assert replay["state_changed"] is False
    assert replay["gate_write_performed"] is False
