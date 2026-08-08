from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


def _decimal(
    value: Any,
) -> Decimal | None:
    if value is None or value == "":
        return None

    try:
        result = Decimal(str(value))
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return None

    if (
        not result.is_finite()
        or result < 0
    ):
        return None

    return result


def _decimal_text(
    value: Decimal | None,
) -> str | None:
    if value is None:
        return None

    text = format(value, "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


def _market_assets(
    market: str,
) -> tuple[str, str]:
    normalized = (
        str(market or "")
        .strip()
        .upper()
        .replace("/", "_")
        .replace("-", "_")
    )

    if "_" not in normalized:
        return (
            normalized,
            "",
        )

    return tuple(
        normalized.split("_", 1)
    )


def estimate_stop_return(
    *,
    market: str,
    base_amount: Any,
    quote_amount: Any,
    current_value: Any,
    market_price: Any,
    source: str = "fresh_gate_detail",
) -> dict[str, Any]:
    base_currency, quote_currency = (
        _market_assets(market)
    )

    base = _decimal(base_amount)
    quote = _decimal(quote_amount)
    total = _decimal(current_value)
    price = _decimal(market_price)

    if price == Decimal("0"):
        price = None

    quote_was_derived = False

    if (
        quote is None
        and base is not None
        and total is not None
        and price is not None
    ):
        derived_quote = (
            total
            - (
                base
                * price
            )
        )

        if derived_quote >= 0:
            quote = derived_quote
            quote_was_derived = True

    available = (
        base is not None
        or quote is not None
    )

    source_is_fresh = source in {
        "fresh_gate_detail",
        "fresh_gate_detail_derived",
    }

    if (
        base is not None
        and quote is not None
    ):
        if quote_was_derived:
            method = (
                "gate_position_plus_current_value"
            )

            confidence = (
                "medium"
                if source_is_fresh
                else "low"
            )
        else:
            method = "gate_position"

            confidence = (
                "high"
                if source_is_fresh
                else "medium"
            )

    elif available:
        method = "gate_position_partial"
        confidence = "low"

    else:
        method = "unavailable"
        confidence = "unavailable"

    estimated_total = None

    if (
        base is not None
        and quote is not None
        and price is not None
    ):
        estimated_total = (
            quote
            + (
                base
                * price
            )
        )

    elif total is not None:
        estimated_total = total

    return {
        "available": available,
        "estimate_only": True,
        "base": {
            "currency": base_currency or None,
            "amount": _decimal_text(base),
        },
        "quote": {
            "currency": quote_currency or None,
            "amount": _decimal_text(quote),
            "derived": quote_was_derived,
        },
        "market_price": _decimal_text(price),
        "estimated_total_quote_value": (
            _decimal_text(
                estimated_total
            )
        ),
        "confidence": confidence,
        "method": method,
        "source": source,
        "as_of": datetime.now(
            timezone.utc
        ).isoformat(),
        "note": (
            "Estimated assets returned if the "
            "strategy is stopped now. Actual "
            "settlement can change if Gate fills "
            "or cancels orders before Stop "
            "processing completes."
        ),
    }
