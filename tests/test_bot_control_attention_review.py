from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import init_db, session_scope
from app.main import app
from app.models import (
    BotControlReconciliation,
    BotControlRequest,
)


init_db()


def auth(
    username: str,
    password: str,
) -> dict[str, str]:
    token = base64.b64encode(
        f"{username}:{password}".encode()
    ).decode()

    return {
        "Authorization": f"Basic {token}"
    }


def create_rejected_request() -> str:
    suffix = uuid.uuid4().hex[:12]
    request_id = f"review-test-{suffix}"
    now = datetime.now(timezone.utc)

    with session_scope() as db:
        db.add(
            BotControlRequest(
                request_id=request_id,
                action="spot_grid_create",
                account_id="zolnode",
                username="zolnode",
                status="rejected",
                request_hash=suffix,
                request_json=(
                    '{"gate_payload":{"market":"EQTY_USDT"}}'
                ),
                response_json="{}",
                error="Synthetic rejected review test",
                created_at=now,
                updated_at=now,
                completed_at=now,
            )
        )

    return request_id


def test_attention_item_can_be_marked_reviewed() -> None:
    request_id = create_rejected_request()
    headers = auth(
        "zolnode",
        "zolnode-test-password",
    )

    with TestClient(app) as client:
        before = client.get(
            "/api/bot-control/attention?limit=200",
            headers=headers,
        )
        assert before.status_code == 200
        assert request_id in {
            row["request_id"]
            for row in before.json()["items"]
        }

        reviewed = client.post(
            (
                "/api/bot-control/attention/"
                f"{request_id}/review"
            ),
            headers=headers,
        )

        assert reviewed.status_code == 200
        assert (
            reviewed.json()["status"]
            == "reviewed"
        )

        after = client.get(
            "/api/bot-control/attention?limit=200",
            headers=headers,
        )
        assert after.status_code == 200
        assert request_id not in {
            row["request_id"]
            for row in after.json()["items"]
        }


def test_new_reconciliation_reopens_reviewed_attention() -> None:
    request_id = create_rejected_request()
    headers = auth(
        "zolnode",
        "zolnode-test-password",
    )

    with TestClient(app) as client:
        reviewed = client.post(
            (
                "/api/bot-control/attention/"
                f"{request_id}/review"
            ),
            headers=headers,
        )
        assert reviewed.status_code == 200

        reviewed_at = datetime.fromisoformat(
            reviewed.json()["reviewed_at"]
        )

        with session_scope() as db:
            db.add(
                BotControlReconciliation(
                    request_id=request_id,
                    account_id="zolnode",
                    username="zolnode",
                    action="spot_grid_create",
                    outcome="inconclusive",
                    confidence="inconclusive",
                    strategy_id="",
                    gate_status="",
                    summary=(
                        "Synthetic newer reconciliation"
                    ),
                    details_json="{}",
                    created_at=(
                        reviewed_at
                        + timedelta(seconds=1)
                    ),
                )
            )

        reopened = client.get(
            "/api/bot-control/attention?limit=200",
            headers=headers,
        )
        assert reopened.status_code == 200
        assert request_id in {
            row["request_id"]
            for row in reopened.json()["items"]
        }
