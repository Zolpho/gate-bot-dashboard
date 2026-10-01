from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .bot_control_actions import (
    INFINITE_GRID_CREATE_ACTION,
)
from .models import (
    Bot,
    BotControlRequest,
)


CONFIGURATION_SOURCE = (
    "bot_control_create_audit"
)


def _dict_or_empty(
    value: Any,
) -> dict[str, Any]:
    return (
        value
        if isinstance(
            value,
            dict,
        )
        else {}
    )


def _load_dict(
    value: str,
) -> dict[str, Any]:
    try:
        parsed = json.loads(
            value
            or "{}"
        )
    except Exception:
        return {}

    return _dict_or_empty(
        parsed
    )


def _positive_int_or_none(
    value: Any,
) -> int | None:
    if isinstance(
        value,
        bool,
    ):
        return None

    try:
        result = int(
            value
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    return (
        result
        if result > 0
        else None
    )


def _ratio_or_none(
    value: Any,
) -> float | None:
    try:
        result = Decimal(
            str(
                value
            )
        )
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return None

    if (
        not result.is_finite()
        or result <= 0
    ):
        return None

    return float(
        result
    )


def _price_type_or_none(
    value: Any,
) -> int | None:
    if isinstance(
        value,
        bool,
    ):
        return None

    try:
        result = int(
            value
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    return (
        result
        if result in (
            0,
            1,
        )
        else None
    )


def bot_create_configuration(
    db: Session,
    bot: Bot,
) -> dict[str, Any] | None:
    """
    Return creation-time configuration provenance for a
    dashboard-created Infinite Grid strategy.

    Gate-observed Bot fields remain authoritative runtime
    telemetry. This helper never writes to the database and
    never calls Gate.

    Provenance intentionally fails closed:
    - only Infinite Grid is supported here;
    - the strategy must have exactly one successful matching
      Bot Control Create audit;
    - the audit payload must match the Bot account strategy
      type and market;
    - ambiguous or malformed audit history returns None.
    """

    strategy_type = str(
        bot.strategy_type
        or ""
    ).strip().lower()

    strategy_id = str(
        bot.strategy_id
        or ""
    ).strip()

    market = str(
        bot.market
        or ""
    ).strip().upper()

    account_id = str(
        bot.account_id
        or ""
    ).strip().lower()

    if (
        strategy_type
        != "infinite_grid"
        or not strategy_id
        or not market
        or not account_id
    ):
        return None

    rows = list(
        db.scalars(
            select(
                BotControlRequest
            ).where(
                BotControlRequest.account_id
                == account_id,
                BotControlRequest.strategy_id
                == strategy_id,
                BotControlRequest.action
                == INFINITE_GRID_CREATE_ACTION,
                BotControlRequest.status
                == "succeeded",
            )
        )
    )

    if len(rows) != 1:
        return None

    payload = _load_dict(
        rows[0].request_json
    )

    gate_payload = _dict_or_empty(
        payload.get(
            "gate_payload"
        )
    )

    if (
        str(
            gate_payload.get(
                "strategy_type",
                "",
            )
        ).strip().lower()
        != strategy_type
    ):
        return None

    if (
        str(
            gate_payload.get(
                "market",
                "",
            )
        ).strip().upper()
        != market
    ):
        return None

    params = _dict_or_empty(
        gate_payload.get(
            "create_params"
        )
    )

    return {
        "source":
            CONFIGURATION_SOURCE,
        "grid_count":
            _positive_int_or_none(
                params.get(
                    "grid_num"
                )
            ),
        "profit_per_grid":
            _ratio_or_none(
                params.get(
                    "profit_per_grid"
                )
            ),
        "price_type":
            _price_type_or_none(
                params.get(
                    "price_type"
                )
            ),
    }
