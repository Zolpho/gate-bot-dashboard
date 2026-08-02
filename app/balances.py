from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

_STABLE_USDT_EQUIVALENTS = {"USDT"}
_BRIDGE_CURRENCIES = ("BTC", "ETH", "USDC")


def as_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def decimal_to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _ticker_prices(raw_tickers: Any) -> dict[str, Decimal]:
    if not isinstance(raw_tickers, list):
        return {}
    prices: dict[str, Decimal] = {}
    for item in raw_tickers:
        if not isinstance(item, Mapping):
            continue
        pair = str(item.get("currency_pair") or "").strip().upper()
        price = as_decimal(item.get("last"))
        if pair and price > 0:
            prices[pair] = price
    return prices


def price_in_usdt(currency: str, prices: Mapping[str, Decimal]) -> tuple[Decimal | None, str | None]:
    currency = currency.strip().upper()
    if currency in _STABLE_USDT_EQUIVALENTS:
        return Decimal("1"), "fixed:USDT"

    direct = prices.get(f"{currency}_USDT")
    if direct and direct > 0:
        return direct, f"{currency}_USDT"

    inverse = prices.get(f"USDT_{currency}")
    if inverse and inverse > 0:
        return Decimal("1") / inverse, f"USDT_{currency}:inverse"

    for bridge in _BRIDGE_CURRENCIES:
        if currency == bridge:
            continue
        bridge_to_usdt = prices.get(f"{bridge}_USDT")
        if not bridge_to_usdt or bridge_to_usdt <= 0:
            continue

        asset_to_bridge = prices.get(f"{currency}_{bridge}")
        if asset_to_bridge and asset_to_bridge > 0:
            return asset_to_bridge * bridge_to_usdt, f"{currency}_{bridge}>{bridge}_USDT"

        bridge_to_asset = prices.get(f"{bridge}_{currency}")
        if bridge_to_asset and bridge_to_asset > 0:
            return bridge_to_usdt / bridge_to_asset, f"{bridge}_{currency}:inverse>{bridge}_USDT"

    return None, None


def _account_balance(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _account_breakdown(total_balance: Any) -> list[dict[str, Any]]:
    if not isinstance(total_balance, Mapping):
        return []
    details = total_balance.get("details")
    if not isinstance(details, Mapping):
        return []

    result: list[dict[str, Any]] = []
    for account_type, raw in details.items():
        balance = _account_balance(raw)
        amount = as_decimal(balance.get("amount"))
        unrealised_pnl = as_decimal(balance.get("unrealised_pnl"))
        borrowed = as_decimal(balance.get("borrowed"))
        if amount == 0 and unrealised_pnl == 0 and borrowed == 0:
            continue
        result.append(
            {
                "account_type": str(account_type),
                "amount": decimal_to_float(amount),
                "currency": str(balance.get("currency") or "USDT"),
                "unrealised_pnl": decimal_to_float(unrealised_pnl),
                "borrowed": decimal_to_float(borrowed),
            }
        )
    result.sort(key=lambda item: abs(float(item["amount"] or 0)), reverse=True)
    return result


def _detail_amount(total_balance: Any, account_type: str) -> Decimal | None:
    if not isinstance(total_balance, Mapping):
        return None
    details = total_balance.get("details")
    if not isinstance(details, Mapping):
        return None
    raw = details.get(account_type)
    if not isinstance(raw, Mapping):
        return None
    return as_decimal(raw.get("amount"))


def _spot_assets(raw_accounts: Any, raw_tickers: Any, dust_usdt: Decimal) -> list[dict[str, Any]]:
    if not isinstance(raw_accounts, list):
        return []

    prices = _ticker_prices(raw_tickers)
    assets: list[dict[str, Any]] = []
    for item in raw_accounts:
        if not isinstance(item, Mapping):
            continue
        currency = str(item.get("currency") or "").strip().upper()
        if not currency:
            continue
        available = as_decimal(item.get("available"))
        locked = as_decimal(item.get("locked"))
        total = available + locked
        if total == 0:
            continue

        price, source = price_in_usdt(currency, prices)
        value = total * price if price is not None else None
        assets.append(
            {
                "currency": currency,
                "available": decimal_to_float(available),
                "locked": decimal_to_float(locked),
                "total": decimal_to_float(total),
                "price_usdt": decimal_to_float(price),
                "value_usdt": decimal_to_float(value),
                "valuation_source": source,
                "valued": value is not None,
                "is_dust": bool(value is not None and abs(value) < dust_usdt),
            }
        )

    assets.sort(
        key=lambda item: (
            item["value_usdt"] is not None,
            float(item["value_usdt"] or 0),
            item["currency"],
        ),
        reverse=True,
    )
    return assets


def _asset_by_currency(assets: Iterable[dict[str, Any]], currency: str) -> dict[str, Any]:
    currency = currency.upper()
    for asset in assets:
        if asset.get("currency") == currency:
            return asset
    return {
        "currency": currency,
        "available": 0.0,
        "locked": 0.0,
        "total": 0.0,
        "price_usdt": 1.0 if currency == "USDT" else None,
        "value_usdt": 0.0,
        "valuation_source": "fixed:USDT" if currency == "USDT" else None,
        "valued": currency == "USDT",
        "is_dust": False,
    }


def build_account_balance_payload(
    *,
    account_id: str,
    display_name: str,
    total_balance: Any,
    spot_accounts: Any,
    spot_tickers: Any,
    bot_summary: Mapping[str, Any],
    dust_usdt: Decimal = Decimal("0.01"),
    as_of: datetime | None = None,
    source: str = "gate",
) -> dict[str, Any]:
    """Normalize private Gate balances into a stable frontend response.

    `wallet/total_balance` is used for the account-wide value and account-type
    breakdown. `spot/accounts` is used for per-currency available/locked values.
    Native Gate bot capital normally appears in the wallet's `quant` account;
    it must not be added to the total again.
    """

    assets = _spot_assets(spot_accounts, spot_tickers, dust_usdt)
    usdt = _asset_by_currency(assets, "USDT")
    eqty = _asset_by_currency(assets, "EQTY")

    other_assets = [asset for asset in assets if asset["currency"] not in {"USDT", "EQTY"}]
    other_value = sum(
        (as_decimal(asset.get("value_usdt")) for asset in other_assets if asset.get("value_usdt") is not None),
        Decimal("0"),
    )
    unvalued_assets = [asset["currency"] for asset in assets if not asset["valued"]]
    valued_spot_total = sum(
        (as_decimal(asset.get("value_usdt")) for asset in assets if asset.get("value_usdt") is not None),
        Decimal("0"),
    )

    total_raw = total_balance.get("total") if isinstance(total_balance, Mapping) else None
    total_info = _account_balance(total_raw)
    total_value = as_decimal(total_info.get("amount")) if total_info else Decimal("0")
    valuation_currency = str(total_info.get("currency") or "USDT") if total_info else "USDT"

    breakdown = _account_breakdown(total_balance)
    if total_value == 0 and breakdown:
        total_value = sum((as_decimal(item.get("amount")) for item in breakdown), Decimal("0"))

    quant_value = _detail_amount(total_balance, "quant")
    spot_value = _detail_amount(total_balance, "spot")

    return {
        "account_id": account_id,
        "display_name": display_name,
        "as_of": (as_of or datetime.now(timezone.utc)).isoformat(),
        "source": source,
        "valuation_currency": valuation_currency,
        "total_value": decimal_to_float(total_value),
        "spot_value": decimal_to_float(spot_value),
        "quant_value": decimal_to_float(quant_value),
        "valued_spot_total": decimal_to_float(valued_spot_total),
        "account_breakdown": breakdown,
        "bot_allocation": {
            "initial_capital": float(bot_summary.get("invest_amount") or 0),
            "current_value": float(bot_summary.get("current_value") or 0),
            "pnl": float(bot_summary.get("pnl") or 0),
            "running_bots": int(bot_summary.get("running_bots") or 0),
            "tracked_bots": int(bot_summary.get("tracked_bots") or 0),
        },
        "summary": {
            "usdt": usdt,
            "eqty": eqty,
            "other_value": decimal_to_float(other_value),
            "other_count": len(other_assets),
            "unvalued_count": len(unvalued_assets),
            "dust_count": sum(1 for asset in assets if asset["is_dust"]),
        },
        "assets": assets,
        "unvalued_assets": unvalued_assets,
        "notes": [
            "Total account value comes from Gate wallet total balance and may be cached by Gate for up to one minute.",
            "USDT, EQTY, and other token quantities are spot-account balances only.",
            "Gate bot funds are represented by the quant account value; tracked bot values are shown separately and are not added again.",
        ],
    }
