from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .accounts import GateAccountConfig
from .config import Settings
from .db import session_scope, utcnow
from .gate_client import GateClient
from .models import DepositRecord, DepositSyncState


FINAL_DEPOSIT_STATUSES = {"DONE", "INVALID", "BLOCKED"}


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _timestamp(value: Any) -> datetime:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return utcnow()
    return datetime.fromtimestamp(number, tz=timezone.utc)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize SQLite-loaded datetimes to timezone-aware UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fallback_gate_id(account_id: str, raw: dict[str, Any]) -> str:
    material = "|".join(
        [
            account_id,
            _text(raw.get("txid")),
            _text(raw.get("currency")).upper(),
            _text(raw.get("chain")),
            _text(raw.get("amount")),
            _text(raw.get("timestamp")),
            _text(raw.get("address")),
            _text(raw.get("memo")),
        ]
    )
    return "fallback:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def normalize_deposit(account_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    gate_id = _text(raw.get("id")) or _fallback_gate_id(account_id, raw)
    return {
        "account_id": account_id,
        "gate_deposit_id": gate_id,
        "txid": _text(raw.get("txid")),
        "reference_id": _text(raw.get("withdraw_order_id")),
        "currency": _text(raw.get("currency")).upper(),
        "chain": _text(raw.get("chain")),
        "amount": _decimal(raw.get("amount")),
        "address": _text(raw.get("address")),
        "memo": _text(raw.get("memo")),
        "status": _text(raw.get("status")).upper() or "UNKNOWN",
        "refund_status": _text(raw.get("refund_status")).upper(),
        "deposited_at": _timestamp(raw.get("timestamp")),
        "raw_json": json.dumps(raw, separators=(",", ":"), sort_keys=True, default=str),
    }


def persist_deposit_address(
    session: Session,
    *,
    account_id: str,
    currency: str,
    network: dict[str, Any],
    minimum_deposit_amount: str | None,
    verified_at: datetime | None = None,
) -> None:
    from .models import DepositAddress

    verified_at = verified_at or utcnow()
    address = _text(network.get("address"))
    if not address:
        return
    memo = _text(network.get("payment_id"))
    chain = _text(network.get("chain")) or _text(network.get("name"))
    row = session.scalar(
        select(DepositAddress).where(
            DepositAddress.account_id == account_id,
            DepositAddress.currency == currency.upper(),
            DepositAddress.chain == chain,
            DepositAddress.address == address,
            DepositAddress.memo == memo,
        )
    )
    if row is None:
        row = DepositAddress(
            account_id=account_id,
            currency=currency.upper(),
            chain=chain,
            address=address,
            memo=memo,
            first_seen_at=verified_at,
        )
        session.add(row)
    row.payment_name = _text(network.get("payment_name"))
    row.contract_address = _text(network.get("contract_address"))
    row.minimum_deposit_amount = _text(minimum_deposit_amount)
    confirms = network.get("min_confirmations")
    try:
        row.minimum_confirmations = int(confirms) if confirms is not None else None
    except (TypeError, ValueError):
        row.minimum_confirmations = None
    row.deposit_enabled = bool(network.get("deposit_enabled", True))
    row.is_active = True
    row.last_verified_at = verified_at
    row.raw_json = json.dumps(
        {key: value for key, value in network.items() if key != "qr_svg_data_uri"},
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )


def deposit_to_dict(row: DepositRecord, *, include_raw: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": row.id,
        "account_id": row.account_id,
        "gate_deposit_id": row.gate_deposit_id,
        "txid": row.txid,
        "reference_id": row.reference_id,
        "currency": row.currency,
        "chain": row.chain,
        "amount": str(row.amount),
        "address": row.address,
        "memo": row.memo,
        "status": row.status,
        "refund_status": row.refund_status,
        "deposited_at": row.deposited_at.isoformat() if row.deposited_at else None,
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "final": row.status in FINAL_DEPOSIT_STATUSES,
    }
    if include_raw:
        try:
            result["raw"] = json.loads(row.raw_json or "{}")
        except json.JSONDecodeError:
            result["raw"] = {}
    return result


def sync_state_to_dict(row: DepositSyncState | None) -> dict[str, Any]:
    if row is None:
        return {
            "status": "never",
            "last_sync_at": None,
            "last_success_at": None,
            "last_reconciliation_at": None,
            "last_error": "",
            "record_count": 0,
        }
    return {
        "status": row.status,
        "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
        "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
        "last_reconciliation_at": row.last_reconciliation_at.isoformat()
        if row.last_reconciliation_at
        else None,
        "window_from": row.window_from.isoformat() if row.window_from else None,
        "window_to": row.window_to.isoformat() if row.window_to else None,
        "last_error": row.last_error,
        "record_count": row.record_count,
        "created_count": row.created_count,
        "updated_count": row.updated_count,
    }


def _window(
    state: DepositSyncState | None,
    settings: Settings,
    now: datetime,
    *,
    full: bool,
) -> tuple[datetime, datetime, bool]:
    normalized_now = _as_utc(now)
    if normalized_now is None:
        raise ValueError("Synchronization time is required")

    last_reconciliation = (
        _as_utc(state.last_reconciliation_at)
        if state is not None
        else None
    )
    last_success = (
        _as_utc(state.last_success_at)
        if state is not None
        else None
    )

    max_lookback = normalized_now - timedelta(
        days=min(settings.deposit_initial_lookback_days, 30)
    )

    reconciliation_due = (
        state is None
        or last_reconciliation is None
        or normalized_now - last_reconciliation
        >= timedelta(hours=settings.deposit_reconcile_hours)
    )

    use_full = (
        full
        or reconciliation_due
        or state is None
        or last_success is None
    )

    if use_full:
        start = max_lookback
    else:
        start = last_success - timedelta(
            seconds=settings.deposit_sync_overlap_seconds
        )
        if start < max_lookback:
            start = max_lookback

    return start, normalized_now, use_full


def upsert_deposit_rows(
    session: Session,
    account_id: str,
    records: Iterable[dict[str, Any]],
    *,
    seen_at: datetime,
) -> tuple[int, int]:
    created = 0
    updated = 0
    for raw in records:
        if not isinstance(raw, dict):
            continue
        data = normalize_deposit(account_id, raw)
        row = session.scalar(
            select(DepositRecord).where(
                DepositRecord.account_id == account_id,
                DepositRecord.gate_deposit_id == data["gate_deposit_id"],
            )
        )
        if row is None:
            row = DepositRecord(
                account_id=account_id,
                gate_deposit_id=data["gate_deposit_id"],
                first_seen_at=seen_at,
            )
            session.add(row)
            created += 1
        else:
            updated += 1
        row.txid = data["txid"]
        row.reference_id = data["reference_id"]
        row.currency = data["currency"]
        row.chain = data["chain"]
        row.amount = data["amount"]
        row.address = data["address"]
        row.memo = data["memo"]
        row.status = data["status"]
        row.refund_status = data["refund_status"]
        row.deposited_at = data["deposited_at"]
        row.last_seen_at = seen_at
        row.updated_at = seen_at
        row.raw_json = data["raw_json"]
    return created, updated


class DepositHistoryService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def sync_account(
        self,
        account: GateAccountConfig,
        *,
        trigger: str,
        full: bool = False,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with session_scope() as session:
            state = session.get(DepositSyncState, account.id)
            if state is None:
                state = DepositSyncState(account_id=account.id)
                session.add(state)
            start, end, full_reconciliation = _window(
                state,
                self.settings,
                now,
                full=full,
            )
            state.status = "running"
            state.last_sync_at = now
            state.last_error = ""
            state.window_from = start
            state.window_to = end

        try:
            async with GateClient(self.settings, account) as client:
                records, page_count = await client.list_all_deposits(
                    from_timestamp=int(start.timestamp()),
                    to_timestamp=int(end.timestamp()),
                    page_limit=self.settings.deposit_page_limit,
                    max_records=self.settings.deposit_max_records_per_sync,
                )

            with session_scope() as session:
                created, updated = upsert_deposit_rows(
                    session,
                    account.id,
                    records,
                    seen_at=now,
                )
                state = session.get(DepositSyncState, account.id)
                if state is None:
                    state = DepositSyncState(account_id=account.id)
                    session.add(state)
                state.status = "success"
                state.last_sync_at = now
                state.last_success_at = now
                if full_reconciliation:
                    state.last_reconciliation_at = now
                state.window_from = start
                state.window_to = end
                state.last_error = ""
                state.record_count = len(records)
                state.created_count = created
                state.updated_count = updated

            return {
                "status": "success",
                "account_id": account.id,
                "trigger": trigger,
                "full_reconciliation": full_reconciliation,
                "window_from": start.isoformat(),
                "window_to": end.isoformat(),
                "record_count": len(records),
                "created_count": created,
                "updated_count": updated,
                "page_count": page_count,
            }
        except Exception as exc:
            with session_scope() as session:
                state = session.get(DepositSyncState, account.id)
                if state is None:
                    state = DepositSyncState(account_id=account.id)
                    session.add(state)
                state.status = "error"
                state.last_sync_at = now
                state.window_from = start
                state.window_to = end
                state.last_error = str(exc)
            raise
