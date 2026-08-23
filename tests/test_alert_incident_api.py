from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import init_db, session_scope
from app.main import app
from app.models import (
    AlertIncident,
    AlertRule,
    Bot,
    GateAccount,
)


init_db()


def auth(
    username: str,
    password: str,
) -> dict[str, str]:
    token = base64.b64encode(
        f"{username}:{password}".encode(
            "utf-8"
        )
    ).decode(
        "ascii"
    )

    return {
        "Authorization": f"Basic {token}"
    }


def _ensure_account(
    session,
    account_id: str,
) -> GateAccount:
    account = session.get(
        GateAccount,
        account_id,
    )

    if account is None:
        account = GateAccount(
            id=account_id,
            name=account_id,
        )

        session.add(
            account
        )

        session.flush()

    return account


def _make_incident(
    *,
    account_id: str,
    recovered: bool = False,
) -> int:
    suffix = uuid.uuid4().hex[:12]

    now = datetime.now(
        timezone.utc
    )

    with session_scope() as session:
        _ensure_account(
            session,
            account_id,
        )

        bot = Bot(
            account_id=account_id,
            strategy_id=(
                f"incident-api-{suffix}"
            ),
            strategy_type="spot_grid",
            strategy_name=(
                f"Incident API {suffix}"
            ),
            market="EQTY_USDT",
            status="running",
            total_profit=Decimal("-150"),
        )

        session.add(
            bot
        )

        session.flush()

        rule = AlertRule(
            name=(
                f"Incident API rule {suffix}"
            ),
            metric="pnl",
            operator="<=",
            threshold=Decimal("-100"),
            bot_id=bot.id,
            enabled=True,
            cooldown_seconds=3600,
        )

        session.add(
            rule
        )

        session.flush()

        recovered_at = (
            now
            + timedelta(minutes=20)
            if recovered
            else None
        )

        incident = AlertIncident(
            rule_id=rule.id,
            bot_id=bot.id,
            rule_name=rule.name,
            metric=rule.metric,
            operator=rule.operator,
            threshold_value=rule.threshold,
            trigger_value=Decimal("-120"),
            current_value=(
                Decimal("-80")
                if recovered
                else Decimal("-150")
            ),
            worst_value=Decimal("-175"),
            opened_at=now,
            last_observed_at=(
                recovered_at
                or now
            ),
            recovered_at=recovered_at,
            acknowledged_at=None,
            acknowledged_by="",
            last_notification_at=now,
            message=(
                f"[{account_id}] "
                "test incident"
            ),
        )

        session.add(
            incident
        )

        session.flush()

        return incident.id


def _make_botless_incident() -> int:
    suffix = uuid.uuid4().hex[:12]

    now = datetime.now(
        timezone.utc
    )

    with session_scope() as session:
        rule = AlertRule(
            name=(
                f"Botless incident {suffix}"
            ),
            metric="pnl",
            operator="<=",
            threshold=Decimal("-100"),
            bot_id=None,
            enabled=True,
            cooldown_seconds=3600,
        )

        session.add(
            rule
        )

        session.flush()

        incident = AlertIncident(
            rule_id=rule.id,
            bot_id=None,
            rule_name=rule.name,
            metric=rule.metric,
            operator=rule.operator,
            threshold_value=rule.threshold,
            trigger_value=Decimal("-120"),
            current_value=Decimal("-120"),
            worst_value=Decimal("-120"),
            opened_at=now,
            last_observed_at=now,
            recovered_at=None,
            acknowledged_at=None,
            acknowledged_by="",
            last_notification_at=now,
            message="Botless incident",
        )

        session.add(
            incident
        )

        session.flush()

        return incident.id


def _item(
    payload: dict,
    incident_id: int,
) -> dict:
    return next(
        item
        for item in payload["items"]
        if item["id"] == incident_id
    )


def test_incident_get_is_public_and_account_scoped() -> None:
    zolnode_id = _make_incident(
        account_id="zolnode",
    )

    arnold_id = _make_incident(
        account_id="arnold",
    )

    with TestClient(app) as client:
        response = client.get(
            (
                "/api/alerts/incidents"
                "?state=open"
                "&account_id=zolnode"
                "&limit=500"
            )
        )

        assert response.status_code == 200

        payload = response.json()

        assert payload["state"] == "open"
        assert payload["account_id"] == "zolnode"
        assert payload["limit"] == 500

        ids = {
            item["id"]
            for item in payload["items"]
        }

        assert zolnode_id in ids
        assert arnold_id not in ids

        item = _item(
            payload,
            zolnode_id,
        )

        assert item["state"] == "open"
        assert item["is_open"] is True
        assert item["is_acknowledged"] is False

        assert item["account_id"] == "zolnode"
        assert item["bot_id"] is not None
        assert item["bot"] is not None

        assert item["metric"] == "pnl"
        assert item["operator"] == "<="
        assert item["threshold"] == -100.0

        assert item["trigger_value"] == -120.0
        assert item["current_value"] == -150.0
        assert item["worst_value"] == -175.0

        assert item["recovered_at"] is None
        assert item["acknowledged_at"] is None
        assert item["acknowledged_by"] == ""


def test_incident_state_filters_open_history_and_all() -> None:
    open_id = _make_incident(
        account_id="zolnode",
    )

    history_id = _make_incident(
        account_id="zolnode",
        recovered=True,
    )

    with TestClient(app) as client:
        opened = client.get(
            (
                "/api/alerts/incidents"
                "?state=open"
                "&account_id=zolnode"
                "&limit=500"
            )
        )

        assert opened.status_code == 200

        open_ids = {
            item["id"]
            for item in opened.json()["items"]
        }

        assert open_id in open_ids
        assert history_id not in open_ids

        history = client.get(
            (
                "/api/alerts/incidents"
                "?state=history"
                "&account_id=zolnode"
                "&limit=500"
            )
        )

        assert history.status_code == 200

        history_payload = history.json()

        history_ids = {
            item["id"]
            for item in history_payload["items"]
        }

        assert history_id in history_ids
        assert open_id not in history_ids

        history_item = _item(
            history_payload,
            history_id,
        )

        assert history_item["state"] == "recovered"
        assert history_item["is_open"] is False
        assert history_item["recovered_at"] is not None

        all_response = client.get(
            (
                "/api/alerts/incidents"
                "?state=all"
                "&account_id=zolnode"
                "&limit=500"
            )
        )

        assert all_response.status_code == 200

        all_ids = {
            item["id"]
            for item in all_response.json()["items"]
        }

        assert open_id in all_ids
        assert history_id in all_ids


def test_operator_can_acknowledge_own_incident() -> None:
    incident_id = _make_incident(
        account_id="zolnode",
    )

    headers = auth(
        "zolnode",
        "zolnode-test-password",
    )

    with TestClient(app) as client:
        response = client.post(
            (
                f"/api/alerts/incidents/"
                f"{incident_id}/acknowledge"
            ),
            headers=headers,
        )

        assert response.status_code == 200

        payload = response.json()

        assert payload["status"] == "acknowledged"
        assert payload["id"] == incident_id

        incident = payload["incident"]

        assert incident["id"] == incident_id
        assert incident["state"] == "open"

        # Ack is not recovery.
        assert incident["recovered_at"] is None
        assert incident["is_open"] is True

        assert incident["acknowledged_at"] is not None
        assert incident["acknowledged_by"] == "zolnode"
        assert incident["is_acknowledged"] is True


def test_incident_acknowledgement_is_idempotent() -> None:
    incident_id = _make_incident(
        account_id="zolnode",
    )

    operator_headers = auth(
        "zolnode",
        "zolnode-test-password",
    )

    super_headers = auth(
        "rootadmin",
        "rootadmin-test-password",
    )

    with TestClient(app) as client:
        first = client.post(
            (
                f"/api/alerts/incidents/"
                f"{incident_id}/acknowledge"
            ),
            headers=operator_headers,
        )

        assert first.status_code == 200

        first_incident = first.json()["incident"]

        first_at = first_incident[
            "acknowledged_at"
        ]

        assert first_at is not None
        assert (
            first_incident["acknowledged_by"]
            == "zolnode"
        )

        second = client.post(
            (
                f"/api/alerts/incidents/"
                f"{incident_id}/acknowledge"
            ),
            headers=super_headers,
        )

        assert second.status_code == 200

        second_incident = second.json()[
            "incident"
        ]

        assert (
            second_incident["acknowledged_at"]
            == first_at
        )

        # Preserve first operator identity.
        assert (
            second_incident["acknowledged_by"]
            == "zolnode"
        )


def test_operator_cannot_acknowledge_other_account_incident() -> None:
    incident_id = _make_incident(
        account_id="arnold",
    )

    headers = auth(
        "zolnode",
        "zolnode-test-password",
    )

    with TestClient(app) as client:
        response = client.post(
            (
                f"/api/alerts/incidents/"
                f"{incident_id}/acknowledge"
            ),
            headers=headers,
        )

        assert response.status_code == 403


def test_botless_incident_requires_super_admin() -> None:
    incident_id = _make_botless_incident()

    operator_headers = auth(
        "zolnode",
        "zolnode-test-password",
    )

    super_headers = auth(
        "rootadmin",
        "rootadmin-test-password",
    )

    with TestClient(app) as client:
        denied = client.post(
            (
                f"/api/alerts/incidents/"
                f"{incident_id}/acknowledge"
            ),
            headers=operator_headers,
        )

        assert denied.status_code == 403

        allowed = client.post(
            (
                f"/api/alerts/incidents/"
                f"{incident_id}/acknowledge"
            ),
            headers=super_headers,
        )

        assert allowed.status_code == 200

        incident = allowed.json()["incident"]

        assert incident["bot_id"] is None
        assert incident["account_id"] is None
        assert incident["bot"] is None

        assert (
            incident["acknowledged_by"]
            == "rootadmin"
        )


def test_unknown_incident_acknowledge_returns_404() -> None:
    headers = auth(
        "rootadmin",
        "rootadmin-test-password",
    )

    with TestClient(app) as client:
        response = client.post(
            (
                "/api/alerts/incidents/"
                "999999999/acknowledge"
            ),
            headers=headers,
        )

        assert response.status_code == 404


def test_incident_state_validation_is_strict() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/alerts/incidents?state=invalid"
        )

        assert response.status_code == 422
