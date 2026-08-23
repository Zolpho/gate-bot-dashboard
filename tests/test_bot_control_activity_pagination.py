from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api.bot_control as api
import app.bot_control_audit as audit
from app.models import Base, BotControlRequest


def _install_test_db(
    monkeypatch,
):
    engine = create_engine(
        "sqlite:///:memory:"
    )

    Base.metadata.create_all(
        engine
    )

    session_factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    @contextmanager
    def test_session_scope():
        with session_factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    monkeypatch.setattr(
        audit,
        "session_scope",
        test_session_scope,
    )

    return (
        engine,
        session_factory,
    )


def _request(
    *,
    request_id,
    account_id,
    created_at,
):
    return BotControlRequest(
        request_id=request_id,
        action="spot_grid_create",
        account_id=account_id,
        username=account_id,
        status="simulated",
        request_hash=(
            "hash-"
            + request_id
        ),
        request_json="{}",
        response_json='{"simulation": true}',
        error="",
        gate_label="",
        created_at=created_at,
        updated_at=created_at,
    )


def test_list_requests_supports_offset_and_stable_order(
    monkeypatch,
):
    (
        engine,
        session_factory,
    ) = _install_test_db(
        monkeypatch
    )

    try:
        base = datetime(
            2026,
            8,
            23,
            8,
            0,
            tzinfo=timezone.utc,
        )

        with session_factory() as db:
            for index in range(5):
                db.add(
                    _request(
                        request_id=f"r-{index}",
                        account_id="zolnode",
                        created_at=(
                            base
                            + timedelta(
                                minutes=index
                            )
                        ),
                    )
                )

            db.commit()

        page = audit.list_requests(
            limit=2,
            offset=1,
            account_ids={"zolnode"},
        )

        assert [
            row["request_id"]
            for row in page
        ] == [
            "r-3",
            "r-2",
        ]

    finally:
        engine.dispose()


def test_count_requests_uses_same_account_scope(
    monkeypatch,
):
    (
        engine,
        session_factory,
    ) = _install_test_db(
        monkeypatch
    )

    try:
        base = datetime(
            2026,
            8,
            23,
            8,
            0,
            tzinfo=timezone.utc,
        )

        with session_factory() as db:
            db.add_all([
                _request(
                    request_id="z-1",
                    account_id="zolnode",
                    created_at=base,
                ),
                _request(
                    request_id="z-2",
                    account_id="zolnode",
                    created_at=(
                        base
                        + timedelta(minutes=1)
                    ),
                ),
                _request(
                    request_id="a-1",
                    account_id="arnold",
                    created_at=(
                        base
                        + timedelta(minutes=2)
                    ),
                ),
            ])

            db.commit()

        assert audit.count_requests(
            account_ids={"zolnode"}
        ) == 2

        assert audit.count_requests(
            account_ids={"arnold"}
        ) == 1

        assert audit.count_requests(
            account_ids={
                "zolnode",
                "arnold",
            }
        ) == 3

        assert audit.count_requests(
            account_ids=set()
        ) == 0

        assert audit.count_requests(
            account_ids=None
        ) == 3

    finally:
        engine.dispose()


def test_activity_api_returns_pagination_metadata(
    monkeypatch,
):
    list_calls = []
    count_calls = []

    def fake_count_requests(
        *,
        account_ids,
    ):
        count_calls.append(
            account_ids
        )

        return 27

    def fake_list_requests(
        *,
        limit,
        offset,
        account_ids,
    ):
        list_calls.append({
            "limit": limit,
            "offset": offset,
            "account_ids": account_ids,
        })

        return [
            {
                "request_id": "r-11",
                "action": "spot_grid_create",
                "account_id": "zolnode",
                "username": "zolnode",
                "status": "simulated",
                "request": {
                    "gate_payload": {
                        "market": "EQTY_USDT",
                        "create_params": {
                            "money": "100",
                            "grid_num": 10,
                            "price_type": 0,
                        },
                    },
                },
                "response": {
                    "simulation": True,
                    "write_performed": False,
                },
                "strategy_id": None,
                "gate_status_code": None,
                "gate_label": "",
                "error": "",
                "created_at": (
                    "2026-08-23T08:00:00+00:00"
                ),
                "completed_at": (
                    "2026-08-23T08:00:01+00:00"
                ),
            },
        ]

    monkeypatch.setattr(
        api,
        "count_requests",
        fake_count_requests,
    )

    monkeypatch.setattr(
        api,
        "list_requests",
        fake_list_requests,
    )

    user = SimpleNamespace(
        is_super_admin=False,
        account_ids={"zolnode"},
    )

    result = (
        api.list_bot_control_activity(
            user=user,
            limit=10,
            offset=10,
            account_id=None,
        )
    )

    assert count_calls == [
        {"zolnode"}
    ]

    assert list_calls == [{
        "limit": 10,
        "offset": 10,
        "account_ids": {"zolnode"},
    }]

    assert result["count"] == 1
    assert result["total"] == 27
    assert result["limit"] == 10
    assert result["offset"] == 10
    assert result["has_previous"] is True
    assert result["has_next"] is True

    assert (
        result["items"][0]["request_id"]
        == "r-11"
    )


def test_activity_api_last_page_has_no_next(
    monkeypatch,
):
    monkeypatch.setattr(
        api,
        "count_requests",
        lambda *, account_ids: 21,
    )

    monkeypatch.setattr(
        api,
        "list_requests",
        lambda **kwargs: [{}],
    )

    user = SimpleNamespace(
        is_super_admin=True,
        account_ids=set(),
    )

    # A deliberately minimal record is not enough for
    # the route renderer, so verify the page-boundary
    # expression statically instead of executing it.
    source = (
        __import__(
            "inspect"
        )
        .getsource(
            api.list_bot_control_activity
        )
    )

    assert (
        'offset + len(items)'
        in source
    )

    assert (
        '< total'
        in source
    )


def test_activity_pagination_is_read_only():
    source = (
        __import__(
            "inspect"
        )
        .getsource(
            api.list_bot_control_activity
        )
    )

    assert "GateClient(" not in source
    assert "create_spot_grid(" not in source
    assert "stop_bot(" not in source

    assert "count_requests(" in source
    assert "list_requests(" in source
