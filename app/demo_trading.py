from __future__ import annotations

import re
import sqlite3

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_DOWN,
    ROUND_UP,
)
from pathlib import Path
from typing import Any, Iterator

from .demo_auth import DEMO_ACCOUNT_IDS
from .demo_wallet import (
    DemoWalletStateError,
    DemoWalletStore,
)


DEMO_TRADING_SCHEMA_VERSION = "1"
DEMO_TRADING_SEED_VERSION = "1"

DEMO_TRADING_SEED_TIMESTAMP = (
    "2026-10-17T14:00:00+00:00"
)

DEMO_TRADING_REQUIRED_CONFIRMATION = (
    "SIMULATE DEMO LIMIT ORDER"
)

_PAIR_RE = re.compile(
    r"^[A-Z0-9]+_[A-Z0-9]+$"
)


class DemoTradingError(
    DemoWalletStateError
):
    """Isolated Demo Trading validation failed."""


_MARKETS = (
    {
        "pair": "EQTY_USDT",
        "base": "EQTY",
        "quote": "USDT",
        "price_precision": 6,
        "amount_precision": 2,
        "minimum_base_amount": "100",
        "minimum_quote_amount": "5",
        "reference_price": "0.0042",
        "spread_bps": "20",
        "trade_enabled": 1,
        "sort_order": 1,
    },
    {
        "pair": "BTC_USDT",
        "base": "BTC",
        "quote": "USDT",
        "price_precision": 2,
        "amount_precision": 6,
        "minimum_base_amount": "0.0001",
        "minimum_quote_amount": "5",
        "reference_price": "65000",
        "spread_bps": "10",
        "trade_enabled": 1,
        "sort_order": 2,
    },
    {
        "pair": "ETH_USDT",
        "base": "ETH",
        "quote": "USDT",
        "price_precision": 2,
        "amount_precision": 5,
        "minimum_base_amount": "0.001",
        "minimum_quote_amount": "5",
        "reference_price": "3500",
        "spread_bps": "10",
        "trade_enabled": 1,
        "sort_order": 3,
    },
)

_INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


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


def _normalize_pair(
    value: str,
) -> str:
    pair = str(
        value or ""
    ).strip().upper().replace(
        "-",
        "_",
    )

    if not _PAIR_RE.fullmatch(
        pair
    ):
        raise ValueError(
            "Invalid Demo Trading pair"
        )

    return pair


def _normalize_side(
    value: str,
) -> str:
    side = str(
        value or ""
    ).strip().lower()

    if side not in {
        "buy",
        "sell",
    }:
        raise ValueError(
            "Demo Trading side must be buy or sell"
        )

    return side


def _normalize_tif(
    value: str,
) -> str:
    tif = str(
        value or ""
    ).strip().lower()

    if tif not in {
        "gtc",
        "poc",
    }:
        raise ValueError(
            "Demo Trading time in force must be gtc or poc"
        )

    return tif


def _positive_decimal(
    value: Decimal | str | int,
    label: str,
) -> Decimal:
    try:
        result = Decimal(
            str(value)
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ) as exc:
        raise ValueError(
            f"Invalid Demo Trading {label}"
        ) from exc

    if (
        not result.is_finite()
        or result <= 0
    ):
        raise ValueError(
            f"Demo Trading {label} must be positive"
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


def _decimal_places(
    value: Decimal,
) -> int:
    normalized = value.normalize()

    return max(
        0,
        -normalized.as_tuple().exponent,
    )


def _quantum(
    precision: int,
) -> Decimal:
    return Decimal("1").scaleb(
        -int(precision)
    )


def _timestamp_epoch() -> int:
    return int(
        datetime(
            2026,
            10,
            17,
            14,
            0,
            0,
            tzinfo=timezone.utc,
        ).timestamp()
    )


class DemoTradingStore:
    """
    Isolated Demo Trading market and preview repository.

    It uses only the dedicated Demo SQLite database and the
    synthetic Demo Wallet balances.

    It has no dependency on Gate transports, Gate credentials,
    production SQLAlchemy sessions, live trading audit stores,
    live trading locks, account-action execution policy, or
    application settings.
    """

    def __init__(
        self,
        database_path: Path,
    ) -> None:
        self.database_path = Path(
            database_path
        )

        self.wallet_store = (
            DemoWalletStore(
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

    def _initialize_schema(
        self,
        db: sqlite3.Connection,
    ) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS
                demo_trading_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

            CREATE TABLE IF NOT EXISTS
                demo_trading_markets (
                    pair TEXT PRIMARY KEY,
                    base TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    price_precision INTEGER NOT NULL,
                    amount_precision INTEGER NOT NULL,
                    minimum_base_amount TEXT NOT NULL,
                    minimum_quote_amount TEXT NOT NULL,
                    reference_price TEXT NOT NULL,
                    spread_bps TEXT NOT NULL,
                    trade_enabled INTEGER NOT NULL,
                    sort_order INTEGER NOT NULL,
                    seeded_at TEXT NOT NULL,

                    FOREIGN KEY (
                        base
                    )
                    REFERENCES demo_wallet_currencies (
                        currency
                    ),

                    FOREIGN KEY (
                        quote
                    )
                    REFERENCES demo_wallet_currencies (
                        currency
                    )
                );
            """
        )

    def _meta(
        self,
        db: sqlite3.Connection,
        key: str,
    ) -> str | None:
        row = db.execute(
            """
            SELECT value
            FROM demo_trading_meta
            WHERE key = ?
            """,
            (
                key,
            ),
        ).fetchone()

        if row is None:
            return None

        return str(
            row["value"]
        )

    def ensure_ready(
        self,
    ) -> None:
        self.wallet_store.ensure_seeded()

        db = self._connect()

        try:
            db.execute(
                "BEGIN IMMEDIATE"
            )

            self._initialize_schema(
                db
            )

            market_count = int(
                db.execute(
                    """
                    SELECT COUNT(*)
                    FROM demo_trading_markets
                    """
                ).fetchone()[0]
            )

            schema_version = self._meta(
                db,
                "schema_version",
            )

            if schema_version is None:
                if market_count:
                    raise DemoTradingError(
                        "Demo Trading schema marker is missing "
                        "for non-empty state"
                    )

                db.execute(
                    """
                    INSERT INTO demo_trading_meta (
                        key,
                        value
                    )
                    VALUES (
                        'schema_version',
                        ?
                    )
                    """,
                    (
                        DEMO_TRADING_SCHEMA_VERSION,
                    ),
                )

            elif (
                schema_version
                != DEMO_TRADING_SCHEMA_VERSION
            ):
                raise DemoTradingError(
                    "Unsupported Demo Trading schema version"
                )

            seed_version = self._meta(
                db,
                "seed_version",
            )

            if seed_version is None:
                if market_count:
                    raise DemoTradingError(
                        "Demo Trading seed marker is missing "
                        "for non-empty market state"
                    )

                for market in _MARKETS:
                    db.execute(
                        """
                        INSERT INTO demo_trading_markets (
                            pair,
                            base,
                            quote,
                            price_precision,
                            amount_precision,
                            minimum_base_amount,
                            minimum_quote_amount,
                            reference_price,
                            spread_bps,
                            trade_enabled,
                            sort_order,
                            seeded_at
                        )
                        VALUES (
                            ?,
                            ?,
                            ?,
                            ?,
                            ?,
                            ?,
                            ?,
                            ?,
                            ?,
                            ?,
                            ?,
                            ?
                        )
                        """,
                        (
                            market["pair"],
                            market["base"],
                            market["quote"],
                            market[
                                "price_precision"
                            ],
                            market[
                                "amount_precision"
                            ],
                            market[
                                "minimum_base_amount"
                            ],
                            market[
                                "minimum_quote_amount"
                            ],
                            market[
                                "reference_price"
                            ],
                            market[
                                "spread_bps"
                            ],
                            market[
                                "trade_enabled"
                            ],
                            market[
                                "sort_order"
                            ],
                            DEMO_TRADING_SEED_TIMESTAMP,
                        ),
                    )

                db.execute(
                    """
                    INSERT INTO demo_trading_meta (
                        key,
                        value
                    )
                    VALUES (
                        'seed_version',
                        ?
                    )
                    """,
                    (
                        DEMO_TRADING_SEED_VERSION,
                    ),
                )

            elif (
                seed_version
                != DEMO_TRADING_SEED_VERSION
            ):
                raise DemoTradingError(
                    "Unsupported Demo Trading seed version"
                )

            final_count = int(
                db.execute(
                    """
                    SELECT COUNT(*)
                    FROM demo_trading_markets
                    """
                ).fetchone()[0]
            )

            if final_count != len(
                _MARKETS
            ):
                raise DemoTradingError(
                    "Unexpected Demo Trading market count"
                )

            actual_pairs = {
                str(row["pair"])
                for row in db.execute(
                    """
                    SELECT pair
                    FROM demo_trading_markets
                    """
                ).fetchall()
            }

            expected_pairs = {
                str(
                    market["pair"]
                )
                for market in _MARKETS
            }

            if (
                actual_pairs
                != expected_pairs
            ):
                raise DemoTradingError(
                    "Unexpected Demo Trading market identity"
                )

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

    def _account_rows(
        self,
        db: sqlite3.Connection,
        account_ids: set[str] | None,
    ) -> list[dict[str, Any]]:
        if account_ids is None:
            scope = set(
                DEMO_ACCOUNT_IDS
            )

        else:
            scope = {
                _normalize_account_id(
                    item
                )
                for item in account_ids
            }

        rows = db.execute(
            """
            SELECT
                account_id,
                display_name,
                sort_order
            FROM demo_wallet_accounts
            ORDER BY
                sort_order ASC,
                account_id ASC
            """
        ).fetchall()

        return [
            {
                "id": str(
                    row["account_id"]
                ),
                "name": str(
                    row["display_name"]
                ),
                "execution_mode": "demo",
            }
            for row in rows
            if str(
                row["account_id"]
            ) in scope
        ]

    @staticmethod
    def _market_dict(
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        return {
            "id": str(
                row["pair"]
            ),
            "base": str(
                row["base"]
            ),
            "quote": str(
                row["quote"]
            ),
            "precision": int(
                row["price_precision"]
            ),
            "amount_precision": int(
                row["amount_precision"]
            ),
            "minimum_base_amount": str(
                row[
                    "minimum_base_amount"
                ]
            ),
            "minimum_quote_amount": str(
                row[
                    "minimum_quote_amount"
                ]
            ),
            "reference_price": str(
                row["reference_price"]
            ),
            "spread_bps": str(
                row["spread_bps"]
            ),
            "trade_enabled": bool(
                row["trade_enabled"]
            ),
        }

    def catalog(
        self,
        *,
        account_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        with self._reader() as db:
            accounts = self._account_rows(
                db,
                account_ids,
            )

            markets = [
                self._market_dict(
                    row
                )
                for row in db.execute(
                    """
                    SELECT *
                    FROM demo_trading_markets
                    ORDER BY
                        sort_order ASC,
                        pair ASC
                    """
                ).fetchall()
            ]

        return {
            "source": "demo",
            "simulation": True,
            "gate_read_performed": False,
            "gate_write_performed": False,
            "write_performed": False,
            "accounts": accounts,
            "pairs": markets,
            "default_pair": "EQTY_USDT",
        }

    def market(
        self,
        pair: str,
    ) -> dict[str, Any]:
        normalized_pair = (
            _normalize_pair(
                pair
            )
        )

        with self._reader() as db:
            row = db.execute(
                """
                SELECT *
                FROM demo_trading_markets
                WHERE pair = ?
                """,
                (
                    normalized_pair,
                ),
            ).fetchone()

        if row is None:
            raise KeyError(
                "Unknown Demo Trading market"
            )

        return self._market_dict(
            row
        )

    def _asset_balance(
        self,
        db: sqlite3.Connection,
        *,
        account_id: str,
        currency: str,
    ) -> dict[str, str]:
        row = db.execute(
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
                account_id,
                currency,
            ),
        ).fetchone()

        if row is None:
            raise DemoTradingError(
                "Demo Wallet asset is unavailable"
            )

        return {
            "available": str(
                row["available"]
            ),
            "locked": str(
                row["locked"]
            ),
        }

    def _market_prices(
        self,
        market: dict[str, Any],
    ) -> dict[str, Decimal]:
        reference = Decimal(
            market["reference_price"]
        )

        spread_bps = Decimal(
            market["spread_bps"]
        )

        half_spread = (
            spread_bps
            / Decimal("20000")
        )

        quantum = _quantum(
            int(
                market["precision"]
            )
        )

        best_bid = (
            reference
            * (
                Decimal("1")
                - half_spread
            )
        ).quantize(
            quantum,
            rounding=ROUND_DOWN,
        )

        best_ask = (
            reference
            * (
                Decimal("1")
                + half_spread
            )
        ).quantize(
            quantum,
            rounding=ROUND_UP,
        )

        return {
            "reference": reference,
            "best_bid": best_bid,
            "best_ask": best_ask,
        }

    def snapshot(
        self,
        *,
        account_id: str,
        pair: str,
        depth: int = 50,
    ) -> dict[str, Any]:
        normalized_account = (
            _normalize_account_id(
                account_id
            )
        )

        market = self.market(
            pair
        )

        prices = self._market_prices(
            market
        )

        depth = max(
            1,
            min(
                int(depth),
                100,
            ),
        )

        price_precision = int(
            market["precision"]
        )

        quantum = _quantum(
            price_precision
        )

        step = max(
            quantum,
            prices["reference"]
            * Decimal("0.001"),
        )

        bids = []
        asks = []

        for index in range(
            1,
            depth + 1,
        ):
            bid = (
                prices["best_bid"]
                - step
                * Decimal(
                    index - 1
                )
            ).quantize(
                quantum,
                rounding=ROUND_DOWN,
            )

            ask = (
                prices["best_ask"]
                + step
                * Decimal(
                    index - 1
                )
            ).quantize(
                quantum,
                rounding=ROUND_UP,
            )

            amount = (
                Decimal("1000")
                * Decimal(index)
                if market["base"]
                == "EQTY"
                else (
                    Decimal("0.001")
                    * Decimal(index)
                    if market["base"]
                    == "BTC"
                    else (
                        Decimal("0.01")
                        * Decimal(index)
                    )
                )
            )

            bids.append(
                {
                    "price":
                        _decimal_text(
                            bid
                        ),
                    "amount":
                        _decimal_text(
                            amount
                        ),
                }
            )

            asks.append(
                {
                    "price":
                        _decimal_text(
                            ask
                        ),
                    "amount":
                        _decimal_text(
                            amount
                            * Decimal(
                                "1.1"
                            )
                        ),
                }
            )

        with self._reader() as db:
            base_balance = (
                self._asset_balance(
                    db,
                    account_id=
                        normalized_account,
                    currency=
                        market["base"],
                )
            )

            quote_balance = (
                self._asset_balance(
                    db,
                    account_id=
                        normalized_account,
                    currency=
                        market["quote"],
                )
            )

        best_bid = prices[
            "best_bid"
        ]

        best_ask = prices[
            "best_ask"
        ]

        spread = (
            best_ask
            - best_bid
        )

        spread_percent = (
            spread
            / prices["reference"]
            * Decimal("100")
        )

        return {
            "source": "demo",
            "simulation": True,
            "gate_read_performed": False,
            "gate_write_performed": False,
            "write_performed": False,
            "account_id":
                normalized_account,
            "pair": market,
            "ticker": {
                "last":
                    _decimal_text(
                        prices["reference"]
                    ),
                "highest_bid":
                    _decimal_text(
                        best_bid
                    ),
                "lowest_ask":
                    _decimal_text(
                        best_ask
                    ),
                "high_24h":
                    _decimal_text(
                        prices["reference"]
                        * Decimal(
                            "1.035"
                        )
                    ),
                "low_24h":
                    _decimal_text(
                        prices["reference"]
                        * Decimal(
                            "0.965"
                        )
                    ),
                "change_percentage":
                    "1.25",
                "base_volume":
                    "1250000",
                "quote_volume":
                    _decimal_text(
                        prices["reference"]
                        * Decimal(
                            "1250000"
                        )
                    ),
            },
            "order_book": {
                "bids": bids,
                "asks": asks,
                "best_bid":
                    _decimal_text(
                        best_bid
                    ),
                "best_ask":
                    _decimal_text(
                        best_ask
                    ),
                "spread":
                    _decimal_text(
                        spread
                    ),
                "spread_percent":
                    _decimal_text(
                        spread_percent
                    ),
                "buy_percent": "52.5",
                "sell_percent": "47.5",
            },
            "balances": {
                "base": base_balance,
                "quote": quote_balance,
            },
        }

    def candles(
        self,
        *,
        pair: str,
        interval: str,
        limit: int = 300,
    ) -> dict[str, Any]:
        market = self.market(
            pair
        )

        normalized_interval = str(
            interval or ""
        ).strip()

        if (
            normalized_interval
            not in _INTERVAL_SECONDS
        ):
            raise ValueError(
                "Unsupported Demo Trading candle interval"
            )

        limit = max(
            1,
            min(
                int(limit),
                300,
            ),
        )

        seconds = _INTERVAL_SECONDS[
            normalized_interval
        ]

        reference = Decimal(
            market["reference_price"]
        )

        end = _timestamp_epoch()

        rows = []

        pattern = (
            Decimal("-0.006"),
            Decimal("-0.002"),
            Decimal("0.001"),
            Decimal("0.004"),
            Decimal("0.002"),
            Decimal("-0.001"),
        )

        for offset in range(
            limit
        ):
            index = (
                limit
                - offset
                - 1
            )

            move = pattern[
                offset
                % len(pattern)
            ]

            close = (
                reference
                * (
                    Decimal("1")
                    + move
                )
            )

            open_price = (
                close
                * (
                    Decimal("1")
                    - Decimal(
                        "0.001"
                    )
                )
            )

            high = max(
                open_price,
                close,
            ) * Decimal(
                "1.0015"
            )

            low = min(
                open_price,
                close,
            ) * Decimal(
                "0.9985"
            )

            rows.append(
                {
                    "time":
                        end
                        - seconds
                        * index,
                    "open":
                        _decimal_text(
                            open_price
                        ),
                    "high":
                        _decimal_text(
                            high
                        ),
                    "low":
                        _decimal_text(
                            low
                        ),
                    "close":
                        _decimal_text(
                            close
                        ),
                    "base_volume":
                        str(
                            1000
                            + offset
                            * 25
                        ),
                }
            )

        return {
            "source": "demo",
            "simulation": True,
            "gate_read_performed": False,
            "gate_write_performed": False,
            "write_performed": False,
            "pair": market["id"],
            "interval":
                normalized_interval,
            "candles": rows,
        }

    def trades(
        self,
        *,
        pair: str,
        limit: int = 40,
    ) -> dict[str, Any]:
        market = self.market(
            pair
        )

        limit = max(
            1,
            min(
                int(limit),
                100,
            ),
        )

        reference = Decimal(
            market["reference_price"]
        )

        epoch_ms = (
            _timestamp_epoch()
            * 1000
        )

        rows = []

        for index in range(
            limit
        ):
            side = (
                "buy"
                if index % 2 == 0
                else "sell"
            )

            move = (
                Decimal(index % 5)
                * Decimal(
                    "0.0005"
                )
            )

            price = (
                reference
                * (
                    Decimal("1")
                    + (
                        move
                        if side == "buy"
                        else -move
                    )
                )
            )

            amount = (
                Decimal("2500")
                + Decimal(index)
                * Decimal("125")
                if market["base"]
                == "EQTY"
                else (
                    Decimal("0.001")
                    + Decimal(index)
                    * Decimal(
                        "0.0001"
                    )
                    if market["base"]
                    == "BTC"
                    else (
                        Decimal("0.02")
                        + Decimal(index)
                        * Decimal(
                            "0.002"
                        )
                    )
                )
            )

            rows.append(
                {
                    "id":
                        f"demo-trade-"
                        f"{market['id'].lower()}-"
                        f"{index + 1}",
                    "side": side,
                    "price":
                        _decimal_text(
                            price
                        ),
                    "amount":
                        _decimal_text(
                            amount
                        ),
                    "time":
                        epoch_ms
                        - index
                        * 45000,
                }
            )

        return {
            "source": "demo",
            "simulation": True,
            "gate_read_performed": False,
            "gate_write_performed": False,
            "write_performed": False,
            "pair": market["id"],
            "count": len(rows),
            "trades": rows,
        }

    def preview_limit_order(
        self,
        *,
        account_id: str,
        pair: str,
        side: str,
        price: Decimal | str | int,
        amount: Decimal | str | int,
        time_in_force: str = "gtc",
    ) -> dict[str, Any]:
        normalized_account = (
            _normalize_account_id(
                account_id
            )
        )

        market = self.market(
            pair
        )

        normalized_side = (
            _normalize_side(
                side
            )
        )

        normalized_tif = (
            _normalize_tif(
                time_in_force
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

        total = (
            normalized_price
            * normalized_amount
        )

        blockers: list[str] = []
        warnings: list[str] = []

        if not market[
            "trade_enabled"
        ]:
            blockers.append(
                "Trading is disabled for this Demo market."
            )

        if (
            _decimal_places(
                normalized_price
            )
            > int(
                market[
                    "precision"
                ]
            )
        ):
            blockers.append(
                "Price exceeds Demo market precision."
            )

        if (
            _decimal_places(
                normalized_amount
            )
            > int(
                market[
                    "amount_precision"
                ]
            )
        ):
            blockers.append(
                "Amount exceeds Demo market precision."
            )

        minimum_base = Decimal(
            market[
                "minimum_base_amount"
            ]
        )

        minimum_quote = Decimal(
            market[
                "minimum_quote_amount"
            ]
        )

        if (
            normalized_amount
            < minimum_base
        ):
            blockers.append(
                "Amount is below the Demo market minimum."
            )

        if total < minimum_quote:
            blockers.append(
                "Order total is below the Demo market minimum."
            )

        funding_asset = (
            market["quote"]
            if normalized_side
            == "buy"
            else market["base"]
        )

        required = (
            total
            if normalized_side
            == "buy"
            else normalized_amount
        )

        with self._reader() as db:
            balance = self._asset_balance(
                db,
                account_id=
                    normalized_account,
                currency=
                    funding_asset,
            )

        available = Decimal(
            balance["available"]
        )

        if required > available:
            blockers.append(
                "Insufficient Demo Wallet available balance."
            )

        prices = self._market_prices(
            market
        )

        marketable = (
            (
                normalized_side
                == "buy"
                and normalized_price
                >= prices[
                    "best_ask"
                ]
            )
            or (
                normalized_side
                == "sell"
                and normalized_price
                <= prices[
                    "best_bid"
                ]
            )
        )

        if (
            normalized_tif == "poc"
            and marketable
        ):
            blockers.append(
                "Post-only order would cross the synthetic Demo book."
            )

        elif marketable:
            warnings.append(
                "This limit price is marketable against the synthetic Demo book."
            )

        remaining = (
            available
            - required
        )

        return {
            "source": "demo",
            "simulation": True,
            "gate_read_performed": False,
            "gate_write_performed": False,
            "write_performed": False,
            "account_id":
                normalized_account,
            "status":
                (
                    "ready"
                    if not blockers
                    else "blocked"
                ),
            "can_execute": False,
            "demo_execution_ready":
                not blockers,
            "required_confirmation":
                DEMO_TRADING_REQUIRED_CONFIRMATION,
            "pair": market,
            "order": {
                "type": "limit",
                "account": "spot",
                "side":
                    normalized_side,
                "price":
                    _decimal_text(
                        normalized_price
                    ),
                "amount":
                    _decimal_text(
                        normalized_amount
                    ),
                "total":
                    _decimal_text(
                        total
                    ),
                "time_in_force":
                    normalized_tif,
            },
            "market": {
                "best_bid":
                    _decimal_text(
                        prices[
                            "best_bid"
                        ]
                    ),
                "best_ask":
                    _decimal_text(
                        prices[
                            "best_ask"
                        ]
                    ),
                "marketable":
                    marketable,
            },
            "funds": {
                "asset":
                    funding_asset,
                "available":
                    _decimal_text(
                        available
                    ),
                "required":
                    _decimal_text(
                        required
                    ),
                "remaining":
                    _decimal_text(
                        remaining
                    ),
            },
            "blockers": blockers,
            "warnings": warnings,
        }
