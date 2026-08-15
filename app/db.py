from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


SQLITE_BUSY_TIMEOUT_MS = 30_000
SQLITE_CONNECT_TIMEOUT_SECONDS = 30.0


class Base(DeclarativeBase):
    pass


settings = get_settings()

is_sqlite = settings.database_url.startswith(
    "sqlite"
)

connect_args = (
    {
        "check_same_thread": False,
        "timeout": SQLITE_CONNECT_TIMEOUT_SECONDS,
    }
    if is_sqlite
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)


if is_sqlite:

    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(
        dbapi_connection,
        connection_record,
    ):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()

        try:
            cursor.execute(
                "PRAGMA foreign_keys=ON"
            )

            cursor.execute(
                "PRAGMA busy_timeout="
                f"{SQLITE_BUSY_TIMEOUT_MS}"
            )

            # Keep FULL durability for Treasury/security
            # state. WAL is configured once in init_db().
            cursor.execute(
                "PRAGMA synchronous=FULL"
            )

        finally:
            cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _enable_sqlite_wal() -> None:
    if not is_sqlite:
        return

    # journal_mode is database-persistent, unlike
    # connection-local PRAGMAs such as busy_timeout.
    # Configure it during startup, before normal request
    # concurrency begins.
    with engine.connect() as conn:
        mode = conn.exec_driver_sql(
            "PRAGMA journal_mode=WAL"
        ).scalar()

        normalized = str(
            mode or ""
        ).strip().lower()

        if normalized != "wal":
            raise RuntimeError(
                "SQLite WAL mode could not be enabled; "
                f"journal_mode returned {mode!r}"
            )


def init_db() -> None:
    from . import models  # noqa: F401
    from .migrations import migrate_database

    # Migrations run during single-threaded application
    # startup. Configure WAL after schema work and before
    # normal runtime concurrency begins.
    migrate_database(engine)
    Base.metadata.create_all(bind=engine)

    _enable_sqlite_wal()


@contextmanager
def session_scope() -> Generator[
    Session,
    None,
    None,
]:
    session = SessionLocal()

    try:
        yield session
        session.commit()

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


def get_db() -> Generator[
    Session,
    None,
    None,
]:
    session = SessionLocal()

    try:
        yield session

    finally:
        session.close()
