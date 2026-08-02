from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..accounts import AccountConfigError, get_gate_account
from ..config import Settings, get_settings
from ..db import get_db
from ..deposit_history import DepositHistoryService, deposit_to_dict, sync_state_to_dict
from ..models import DepositRecord, DepositSyncState, GateAccount
from ..security import DashboardUser, require_user, resolve_authorized_account


router = APIRouter(prefix="/api/me/deposits", tags=["private deposits"])


def _account_id(user: DashboardUser, requested: str | None) -> str:
    selected = resolve_authorized_account(user, requested)
    if selected is None:
        raise HTTPException(status_code=400, detail="Select one assigned account")
    return selected


@router.get("")
def list_deposits(
    user: Annotated[DashboardUser, Depends(require_user)],
    account_id: str | None = Query(default=None),
    currency: str | None = Query(default=None, max_length=32),
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    selected = _account_id(user, account_id)
    filters = [DepositRecord.account_id == selected]
    if currency:
        filters.append(DepositRecord.currency == currency.strip().upper())
    if status:
        filters.append(DepositRecord.status == status.strip().upper())

    total = int(
        db.scalar(select(func.count(DepositRecord.id)).where(*filters)) or 0
    )
    rows = db.scalars(
        select(DepositRecord)
        .where(*filters)
        .order_by(DepositRecord.deposited_at.desc(), DepositRecord.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    account = db.get(GateAccount, selected)
    sync_state = db.get(DepositSyncState, selected)
    return {
        "account_id": selected,
        "display_name": account.name if account else selected,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [deposit_to_dict(row) for row in rows],
        "sync": sync_state_to_dict(sync_state),
        "authorized_user": user.safe_dict(),
    }


@router.post("/sync")
async def sync_deposits(
    user: Annotated[DashboardUser, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    account_id: str | None = Query(default=None),
    full: bool = Query(default=False),
) -> dict[str, Any]:
    selected = _account_id(user, account_id)
    try:
        account = get_gate_account(selected)
    except AccountConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if account is None or not account.enabled or not account.configured:
        raise HTTPException(
            status_code=503,
            detail=f"Gate credentials are not configured for account {selected}",
        )
    if settings.demo_mode:
        return {
            "status": "success",
            "mode": "demo",
            "account_id": selected,
            "record_count": 0,
            "created_count": 0,
            "updated_count": 0,
            "authorized_user": user.safe_dict(),
        }
    try:
        result = await DepositHistoryService(settings).sync_account(
            account,
            trigger="manual",
            full=full,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    result["authorized_user"] = user.safe_dict()
    return result


@router.get("/{deposit_id}")
def get_deposit(
    deposit_id: int,
    user: Annotated[DashboardUser, Depends(require_user)],
    account_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    selected = _account_id(user, account_id)
    row = db.get(DepositRecord, deposit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Deposit record not found")
    if row.account_id != selected:
        raise HTTPException(status_code=403, detail="You are not allowed to view this deposit")
    return {
        "deposit": deposit_to_dict(row, include_raw=True),
        "authorized_user": user.safe_dict(),
    }
