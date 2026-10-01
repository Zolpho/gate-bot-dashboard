from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import (
    create_engine,
)
from sqlalchemy.orm import (
    sessionmaker,
)

from app.api.bots import (
    get_bot,
)
from app.bot_configuration import (
    bot_create_configuration,
)
from app.db import Base
from app.models import (
    Bot,
    BotControlRequest,
    GateAccount,
)


def _db():
    engine = create_engine(
        "sqlite:///:memory:"
    )

    Base.metadata.create_all(
        engine
    )

    factory = sessionmaker(
        bind=engine
    )

    return (
        engine,
        factory(),
    )


def _add_bot(
    db,
    *,
    strategy_id: str = "5453981",
):
    account = GateAccount(
        id="arnold",
        name="arnold",
        enabled=True,
        configured=True,
    )

    db.add(
        account
    )

    db.flush()

    bot = Bot(
        account_id="arnold",
        strategy_id=strategy_id,
        strategy_type="infinite_grid",
        strategy_name="GateQuant-grid-3",
        market="EQTY_USDT",
        status="running",
        source_status="running",
        invest_amount=Decimal("400"),
        current_value=Decimal(
            "400.0036821578"
        ),
        total_profit=Decimal(
            "0.0036821578"
        ),
        price_floor=Decimal(
            "0.0018"
        ),
        grid_count=None,
        stop_supported=True,
    )

    db.add(
        bot
    )

    db.flush()

    return bot


def _add_request(
    db,
    *,
    strategy_id: str = "5453981",
    request_id: str = "infinity-config-1",
    status: str = "succeeded",
    market: str = "EQTY_USDT",
):
    payload = {
        "account_id": "arnold",
        "operation":
            "infinite_grid_create",
        "gate_payload": {
            "strategy_type":
                "infinite_grid",
            "market":
                market,
            "create_params": {
                "money": "400",
                "price_floor": "0.0018",
                "profit_per_grid": "0.01",
                "grid_num": 10,
                "price_type": 1,
            },
        },
    }

    row = BotControlRequest(
        request_id=request_id,
        action="infinite_grid_create",
        account_id="arnold",
        username="arnold",
        status=status,
        request_hash=(
            "a"
            * 64
        ),
        request_json=json.dumps(
            payload
        ),
        response_json="{}",
        strategy_id=strategy_id,
        gate_status_code=200,
    )

    db.add(
        row
    )

    db.flush()

    return row


def test_bot_detail_exposes_separate_create_configuration():
    engine, db = _db()

    try:
        bot = _add_bot(
            db
        )

        _add_request(
            db
        )

        result = get_bot(
            bot.id,
            db=db,
        )

        payload = result[
            "bot"
        ]

        configuration = payload[
            "create_configuration"
        ]

        assert payload[
            "grid_count"
        ] is None

        assert configuration == {
            "source":
                "bot_control_create_audit",
            "grid_count":
                10,
            "profit_per_grid":
                0.01,
            "price_type":
                1,
        }

        #
        # Reading provenance must never rewrite Gate
        # telemetry on the canonical Bot row.
        #
        assert db.get(
            Bot,
            bot.id,
        ).grid_count is None

    finally:
        db.close()
        engine.dispose()


def test_gate_created_infinity_bot_has_no_invented_configuration():
    engine, db = _db()

    try:
        bot = _add_bot(
            db
        )

        result = get_bot(
            bot.id,
            db=db,
        )

        assert (
            result[
                "bot"
            ][
                "create_configuration"
            ]
            is None
        )

    finally:
        db.close()
        engine.dispose()


def test_non_successful_create_audit_is_not_configuration_provenance():
    engine, db = _db()

    try:
        bot = _add_bot(
            db
        )

        _add_request(
            db,
            status="rejected",
        )

        assert (
            bot_create_configuration(
                db,
                bot,
            )
            is None
        )

    finally:
        db.close()
        engine.dispose()


def test_ambiguous_successful_create_audits_fail_closed():
    engine, db = _db()

    try:
        bot = _add_bot(
            db
        )

        _add_request(
            db,
            request_id="infinity-config-1",
        )

        _add_request(
            db,
            request_id="infinity-config-2",
        )

        assert (
            bot_create_configuration(
                db,
                bot,
            )
            is None
        )

    finally:
        db.close()
        engine.dispose()
