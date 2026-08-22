from datetime import datetime, timezone
from decimal import Decimal
import inspect as python_inspect

import pytest
from fastapi import HTTPException
from sqlalchemy import (
    create_engine,
    inspect,
    select,
)
from sqlalchemy.orm import sessionmaker

from app.api.bots import (
    archive_bot,
    restore_bot,
)
from app.collector import BotCollector
from app.db import Base
from app.metrics import bot_to_dict
from app.migrations import migrate_database
from app.models import (
    Bot,
    BotArchive,
    GateAccount,
)
from app.security import DashboardUser


def _user(*account_ids: str) -> DashboardUser:
    return DashboardUser(
        username="archive-operator",
        role="account_operator",
        account_ids=tuple(account_ids),
    )


def _db():
    engine = create_engine(
        "sqlite:///:memory:"
    )

    Base.metadata.create_all(
        engine
    )

    session_factory = sessionmaker(
        bind=engine
    )

    return engine, session_factory()


def _add_account_and_bot(
    db,
    *,
    account_id="zolnode",
    status="stopped",
    strategy_id="5268809",
):
    account = GateAccount(
        id=account_id,
        name=account_id,
        enabled=True,
        configured=True,
    )

    db.add(account)
    db.flush()

    bot = Bot(
        account_id=account_id,
        strategy_id=strategy_id,
        strategy_type="spot_grid",
        strategy_name="Archive test bot",
        market="EQTY_USDT",
        status=status,
        source_status=status,
        invest_amount=Decimal("100"),
        current_value=Decimal("110"),
        total_profit=Decimal("10"),
        profit_rate=Decimal("0.10"),
        stop_supported=True,
    )

    db.add(bot)
    db.flush()

    return bot


def test_archive_stopped_bot_is_local_and_durable():
    engine, db = _db()

    try:
        bot = _add_account_and_bot(
            db
        )

        result = archive_bot(
            bot.id,
            user=_user("zolnode"),
            db=db,
        )

        assert result["status"] == "archived"

        assert (
            result["gate_write_performed"]
            is False
        )

        assert (
            result["bot"]["status"]
            == "stopped"
        )

        assert (
            result["bot"]["archived"]
            is True
        )

        assert result["bot"]["archived_at"]

        assert (
            "archived_by"
            not in result["bot"]
        )

        row = db.scalar(
            select(BotArchive)
            .where(
                BotArchive.bot_id
                == bot.id
            )
        )

        assert row is not None

        assert (
            row.account_id
            == "zolnode"
        )

        assert (
            row.archived_by
            == "archive-operator"
        )

        #
        # Local archive must not falsify the Gate state.
        #
        assert bot.status == "stopped"

    finally:
        db.close()
        engine.dispose()


def test_archive_is_idempotent():
    engine, db = _db()

    try:
        bot = _add_account_and_bot(
            db
        )

        first = archive_bot(
            bot.id,
            user=_user("zolnode"),
            db=db,
        )

        second = archive_bot(
            bot.id,
            user=_user("zolnode"),
            db=db,
        )

        assert first["status"] == "archived"
        assert second["status"] == "archived"

        rows = db.scalars(
            select(BotArchive)
        ).all()

        assert len(rows) == 1

    finally:
        db.close()
        engine.dispose()


def test_running_bot_cannot_be_archived():
    engine, db = _db()

    try:
        bot = _add_account_and_bot(
            db,
            status="running",
        )

        with pytest.raises(
            HTTPException
        ) as exc:
            archive_bot(
                bot.id,
                user=_user("zolnode"),
                db=db,
            )

        assert exc.value.status_code == 409

        assert (
            "Only stopped bots"
            in str(exc.value.detail)
        )

        assert db.scalar(
            select(BotArchive)
        ) is None

    finally:
        db.close()
        engine.dispose()


def test_other_account_cannot_archive_bot():
    engine, db = _db()

    try:
        bot = _add_account_and_bot(
            db
        )

        with pytest.raises(
            HTTPException
        ) as exc:
            archive_bot(
                bot.id,
                user=_user("reserves"),
                db=db,
            )

        assert exc.value.status_code == 403

        assert db.scalar(
            select(BotArchive)
        ) is None

    finally:
        db.close()
        engine.dispose()


def test_owner_can_restore_archived_bot():
    engine, db = _db()

    try:
        bot = _add_account_and_bot(
            db
        )

        archive_bot(
            bot.id,
            user=_user("zolnode"),
            db=db,
        )

        result = restore_bot(
            bot.id,
            user=_user("zolnode"),
            db=db,
        )

        assert result == {
            "status": "restored",
            "bot_id": bot.id,
            "account_id": "zolnode",
            "gate_write_performed": False,
        }

        assert db.scalar(
            select(BotArchive)
        ) is None

        assert bot.status == "stopped"

    finally:
        db.close()
        engine.dispose()


def test_other_account_cannot_restore_bot():
    engine, db = _db()

    try:
        bot = _add_account_and_bot(
            db
        )

        archive_bot(
            bot.id,
            user=_user("zolnode"),
            db=db,
        )

        with pytest.raises(
            HTTPException
        ) as exc:
            restore_bot(
                bot.id,
                user=_user("reserves"),
                db=db,
            )

        assert exc.value.status_code == 403

        assert db.scalar(
            select(BotArchive)
        ) is not None

    finally:
        db.close()
        engine.dispose()


def test_non_stopped_bot_never_serializes_as_archived():
    engine, db = _db()

    try:
        bot = _add_account_and_bot(
            db,
            status="running",
        )

        bot.archive = BotArchive(
            bot_id=bot.id,
            account_id=bot.account_id,
            archived_by="legacy-state",
        )

        db.add(
            bot.archive
        )

        db.flush()

        payload = bot_to_dict(
            bot
        )

        assert payload["status"] == "running"
        assert payload["archived"] is False
        assert payload["archived_at"] is None

    finally:
        db.close()
        engine.dispose()


def _running_bot(
    strategy_id: str,
):
    return type(
        "NormalizedBotLike",
        (),
        {
            "strategy_id": strategy_id,
            "strategy_type": "spot_grid",
            "strategy_name": "Reactivated bot",
            "market": "EQTY_USDT",
            "status": "running",
            "source_status": "running",
            "invest_amount": Decimal("100"),
            "pnl": Decimal("0"),
            "pnl_rate": Decimal("0"),
            "total_profit": Decimal("0"),
            "profit_rate": Decimal("0"),
            "grid_profit": Decimal("0"),
            "floating_pnl": Decimal("0"),
            "realized_pnl": Decimal("0"),
            "current_value": Decimal("100"),
            "arbitrage_count": 0,
            "grid_count": 10,
            "finished_rounds": 0,
            "runtime_seconds": 60,
            "price_range": "",
            "price_floor": None,
            "avg_cost": None,
            "take_profit_price": None,
            "estimated_liquidation_price": None,
            "maintenance_margin_ratio": None,
            "position_side": "",
            "position_amount": None,
            "quote_amount": None,
            "entry_price": None,
            "position_value": None,
            "margin": None,
            "stop_supported": True,
            "created_at_gate": None,
            "raw_list": {},
            "raw_detail": {},
            "metrics": {},
        },
    )()


def test_collector_reactivation_clears_archive_marker():
    engine, db = _db()

    try:
        bot = _add_account_and_bot(
            db,
            status="stopped",
            strategy_id="reactivation-test",
        )

        archive_bot(
            bot.id,
            user=_user("zolnode"),
            db=db,
        )

        assert db.scalar(
            select(BotArchive)
            .where(
                BotArchive.bot_id
                == bot.id
            )
        ) is not None

        BotCollector._upsert_bot(
            db,
            bot.account_id,
            _running_bot(
                bot.strategy_id
            ),
            datetime.now(
                timezone.utc
            ),
        )

        db.flush()

        assert db.scalar(
            select(BotArchive)
            .where(
                BotArchive.bot_id
                == bot.id
            )
        ) is None

        assert bot.status == "running"

    finally:
        db.close()
        engine.dispose()


def test_migration_creates_archive_table_for_existing_db(
    tmp_path,
):
    path = tmp_path / "bot-archive.db"

    engine = create_engine(
        f"sqlite:///{path}"
    )

    try:
        Base.metadata.create_all(
            engine,
            tables=[
                GateAccount.__table__,
                Bot.__table__,
            ],
        )

        assert (
            "bot_archives"
            not in inspect(
                engine
            ).get_table_names()
        )

        migrate_database(
            engine
        )

        inspector = inspect(
            engine
        )

        assert (
            "bot_archives"
            in inspector.get_table_names()
        )

        columns = {
            item["name"]
            for item
            in inspector.get_columns(
                "bot_archives"
            )
        }

        assert columns == {
            "id",
            "bot_id",
            "account_id",
            "archived_at",
            "archived_by",
        }

        unique_sets = {
            tuple(
                item.get(
                    "column_names"
                ) or []
            )
            for item
            in inspector.get_unique_constraints(
                "bot_archives"
            )
        }

        assert (
            ("bot_id",)
            in unique_sets
        )

    finally:
        engine.dispose()


def test_archive_routes_contain_no_gate_logic():
    source = (
        python_inspect.getsource(
            archive_bot
        )
        + python_inspect.getsource(
            restore_bot
        )
    )

    assert "GateClient" not in source
    assert "get_bot_control_account" not in source
    assert "create_spot_grid" not in source
    assert "stop_bot" not in source

    assert (
        '"gate_write_performed": False'
        in source
    )


def test_public_serializer_hides_archived_by():
    source = python_inspect.getsource(
        bot_to_dict
    )

    assert '"archived"' in source
    assert '"archived_at"' in source
    assert '"archived_by"' not in source
