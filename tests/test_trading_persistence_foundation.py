from sqlalchemy import create_engine, inspect

from app.db import Base
from app.models import (
    TradingOrderOperationLock,
    TradingOrderReconciliation,
    TradingOrderRequest,
)


def test_trading_persistence_tables_create():
    engine = create_engine(
        "sqlite:///:memory:"
    )

    Base.metadata.create_all(
        bind=engine
    )

    names = set(
        inspect(engine).get_table_names()
    )

    assert (
        TradingOrderRequest.__tablename__
        in names
    )

    assert (
        TradingOrderReconciliation.__tablename__
        in names
    )

    assert (
        TradingOrderOperationLock.__tablename__
        in names
    )


def test_trading_lock_is_funding_asset_scoped():
    columns = {
        column.name
        for column
        in TradingOrderOperationLock
        .__table__
        .columns
    }

    assert "account_id" in columns
    assert "funding_asset" in columns
    assert "pair" in columns
    assert "side" in columns
    assert "owner_request_id" in columns
