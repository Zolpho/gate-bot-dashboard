from __future__ import annotations

import asyncio
import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import (
    bootstrap_public_donation_catalog
    as bulk_cli,
)


class FakeGateClient:
    calls: list[
        tuple[
            str,
            str,
        ]
    ] = []

    fail_abc_address = False

    def __init__(
        self,
        settings=None,
        account=None,
    ) -> None:
        self.account = account

    async def __aenter__(
        self,
    ):
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ) -> None:
        return None

    async def list_spot_currencies(
        self,
        name=None,
    ):
        type(self).calls.append(
            (
                "catalog",
                "",
            )
        )

        return SimpleNamespace(
            data=[
                {
                    "currency": "EQTY",
                    "name": "EQTY",
                    "delisted": False,
                    "deposit_disabled": False,
                    "chains": [
                        {
                            "chain": "BASEEVM",
                            "name_en": "Base",
                            "is_deposit_disabled": 0,
                        },
                    ],
                },
                {
                    "currency": "ABC",
                    "name": "ABC Token",
                    "delisted": False,
                    "deposit_disabled": False,
                    "chains": [
                        {
                            "chain": "ETH",
                            "name_en": "Ethereum",
                            "is_deposit_disabled": 0,
                        },
                        {
                            "chain": "ARBEVM",
                            "name_en": "Arbitrum One",
                            "is_deposit_disabled": 0,
                        },
                    ],
                },
                {
                    "currency": "OFF",
                    "name": "Disabled",
                    "delisted": False,
                    "deposit_disabled": True,
                    "chains": [
                        {
                            "chain": "ETH",
                            "name_en": "Ethereum",
                            "is_deposit_disabled": 1,
                        },
                    ],
                },
            ]
        )

    async def list_currency_chains(
        self,
        currency: str,
    ):
        type(self).calls.append(
            (
                "networks",
                currency,
            )
        )

        if currency == "EQTY":
            data = [
                {
                    "chain": "BASEEVM",
                    "name_en": "Base",
                    "is_deposit_disabled": 0,
                },
            ]

        elif currency == "ABC":
            data = [
                {
                    "chain": "ETH",
                    "name_en": "Ethereum",
                    "is_deposit_disabled": 0,
                },
                {
                    "chain": "ARBEVM",
                    "name_en": "Arbitrum One",
                    "is_deposit_disabled": 0,
                },
            ]

        else:
            data = []

        return SimpleNamespace(
            data=data
        )

    async def get_deposit_address(
        self,
        currency: str,
    ):
        type(self).calls.append(
            (
                "address",
                currency,
            )
        )

        if (
            currency == "ABC"
            and type(self).fail_abc_address
        ):
            raise bulk_cli.GateAPIError(
                "temporary ABC failure"
            )

        if currency == "EQTY":
            items = [
                {
                    "chain": "BASEEVM",
                    "address": "0xEQty",
                    "payment_id": None,
                    "obtain_failed": 0,
                },
            ]

        else:
            items = [
                {
                    "chain": "ETH",
                    "address": "0xABC",
                    "payment_id": None,
                    "obtain_failed": 0,
                },
                {
                    "chain": "ARBEVM",
                    "address": "0xABCArb",
                    "payment_id": "123",
                    "obtain_failed": 0,
                },
            ]

        return SimpleNamespace(
            data={
                "currency": currency,
                "multichain_addresses":
                    items,
            }
        )


class ForbiddenGateClient:
    def __init__(
        self,
        *args,
        **kwargs,
    ) -> None:
        raise AssertionError(
            "Apply mode must not construct GateClient"
        )


class FakeSession:
    def __init__(
        self,
    ) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def commit(
        self,
    ) -> None:
        self.commits += 1

    def rollback(
        self,
    ) -> None:
        self.rollbacks += 1

    def close(
        self,
    ) -> None:
        self.closed += 1


@pytest.fixture(autouse=True)
def reset_fake(
    monkeypatch,
) -> None:
    FakeGateClient.calls = []
    FakeGateClient.fail_abc_address = False

    monkeypatch.setattr(
        bulk_cli,
        "BULK_UNSIGNED_DELAY_SECONDS",
        0,
    )

    monkeypatch.setattr(
        bulk_cli,
        "BULK_SIGNED_DELAY_SECONDS",
        0,
    )

    monkeypatch.setattr(
        bulk_cli.os,
        "geteuid",
        lambda: 0,
    )


def configure_fake_gate(
    monkeypatch,
) -> None:
    fake_account = SimpleNamespace(
        id="eqtydao",
        enabled=True,
        configured=True,
    )

    monkeypatch.setattr(
        bulk_cli,
        "GateClient",
        FakeGateClient,
    )

    monkeypatch.setattr(
        bulk_cli,
        "get_settings",
        lambda: SimpleNamespace(
            deposit_favorite_list=[],
        ),
    )

    def fake_get_gate_account(
        account_id: str,
    ):
        assert account_id == "eqtydao"

        return fake_account

    monkeypatch.setattr(
        bulk_cli,
        "get_gate_account",
        fake_get_gate_account,
    )


def test_parser_exposes_no_wallet_account_override() -> None:
    parser = (
        bulk_cli.build_parser()
    )

    destinations = {
        action.dest
        for action in parser._actions
    }

    assert "plan_file" in destinations
    assert "apply_plan" in destinations
    assert "resume" in destinations
    assert "confirm_digest" in destinations

    assert "account" not in destinations
    assert "account_id" not in destinations
    assert "wallet_account" not in destinations


def test_bulk_plan_discovers_all_routes_with_one_signed_read_per_currency(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configure_fake_gate(
        monkeypatch
    )

    path = (
        tmp_path
        / "plan.json"
    )

    plan = asyncio.run(
        bulk_cli
        .generate_catalog_plan(
            path,
            resume=False,
        )
    )

    assert plan["complete"] is True

    assert (
        plan["catalog"]["candidate_count"]
        == 2
    )

    assert (
        plan["catalog"]["candidate_symbols"]
        == [
            "ABC",
            "EQTY",
        ]
    )

    assert (
        plan["summary"]["ready_routes"]
        == 3
    )

    assert (
        plan["summary"]["unavailable_routes"]
        == 0
    )

    ready = [
        route
        for route in plan["routes"]
        if route["status"]
        == "ready"
    ]

    assert {
        (
            route["currency"],
            route["chain"],
        )
        for route in ready
    } == {
        (
            "ABC",
            "ETH",
        ),
        (
            "ABC",
            "ARBEVM",
        ),
        (
            "EQTY",
            "BASEEVM",
        ),
    }

    assert (
        FakeGateClient.calls.count(
            (
                "address",
                "ABC",
            )
        )
        == 1
    )

    assert (
        FakeGateClient.calls.count(
            (
                "address",
                "EQTY",
            )
        )
        == 1
    )

    assert (
        stat.S_IMODE(
            path.stat().st_mode
        )
        == 0o600
    )

    loaded = (
        bulk_cli._load_plan(
            path
        )
    )

    assert (
        loaded["digest"]
        == bulk_cli.plan_digest(
            loaded
        )
    )


def test_incomplete_plan_can_resume_only_failed_currency(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configure_fake_gate(
        monkeypatch
    )

    path = (
        tmp_path
        / "plan.json"
    )

    FakeGateClient.fail_abc_address = True

    first = asyncio.run(
        bulk_cli
        .generate_catalog_plan(
            path,
            resume=False,
        )
    )

    assert first["complete"] is False

    assert (
        first["currency_results"]["ABC"]["status"]
        == "error"
    )

    assert (
        first["currency_results"]["EQTY"]["status"]
        == "complete"
    )

    FakeGateClient.calls = []
    FakeGateClient.fail_abc_address = False

    resumed = asyncio.run(
        bulk_cli
        .generate_catalog_plan(
            path,
            resume=True,
        )
    )

    assert resumed["complete"] is True

    assert (
        resumed["summary"]["ready_routes"]
        == 3
    )

    assert (
        (
            "networks",
            "EQTY",
        )
        not in FakeGateClient.calls
    )

    assert (
        (
            "address",
            "EQTY",
        )
        not in FakeGateClient.calls
    )

    assert (
        (
            "networks",
            "ABC",
        )
        in FakeGateClient.calls
    )

    assert (
        (
            "address",
            "ABC",
        )
        in FakeGateClient.calls
    )


def test_apply_plan_uses_zero_gate_calls_and_one_db_commit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configure_fake_gate(
        monkeypatch
    )

    path = (
        tmp_path
        / "plan.json"
    )

    plan = asyncio.run(
        bulk_cli
        .generate_catalog_plan(
            path,
            resume=False,
        )
    )

    fake_session = FakeSession()

    monkeypatch.setattr(
        bulk_cli,
        "GateClient",
        ForbiddenGateClient,
    )

    monkeypatch.setattr(
        bulk_cli,
        "_trust_table_exists",
        lambda: True,
    )

    monkeypatch.setattr(
        bulk_cli,
        "SessionLocal",
        lambda: fake_session,
    )

    observed = []

    def fake_bootstrap(
        session,
        payload,
    ):
        observed.append(
            payload
        )

        return SimpleNamespace(
            state="bootstrapped",
            destination_id=
                len(
                    observed
                ),
        )

    monkeypatch.setattr(
        bulk_cli,
        "bootstrap_public_destination",
        fake_bootstrap,
    )

    (
        bootstrapped,
        already_trusted,
    ) = (
        bulk_cli.apply_catalog_plan(
            path,
            confirm_digest=
                plan["digest"],
        )
    )

    assert bootstrapped == 3
    assert already_trusted == 0

    assert len(
        observed
    ) == 3

    assert fake_session.commits == 1
    assert fake_session.rollbacks == 0
    assert fake_session.closed == 1


def test_apply_rolls_back_everything_on_existing_mismatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configure_fake_gate(
        monkeypatch
    )

    path = (
        tmp_path
        / "plan.json"
    )

    plan = asyncio.run(
        bulk_cli
        .generate_catalog_plan(
            path,
            resume=False,
        )
    )

    fake_session = FakeSession()

    monkeypatch.setattr(
        bulk_cli,
        "_trust_table_exists",
        lambda: True,
    )

    monkeypatch.setattr(
        bulk_cli,
        "SessionLocal",
        lambda: fake_session,
    )

    calls = 0

    def fake_bootstrap(
        session,
        payload,
    ):
        nonlocal calls

        calls += 1

        if calls == 2:
            raise (
                bulk_cli
                .DonationDestinationBootstrapError(
                    "mismatch"
                )
            )

        return SimpleNamespace(
            state="bootstrapped",
            destination_id=calls,
        )

    monkeypatch.setattr(
        bulk_cli,
        "bootstrap_public_destination",
        fake_bootstrap,
    )

    with pytest.raises(
        bulk_cli
        .DonationDestinationBootstrapError
    ):
        bulk_cli.apply_catalog_plan(
            path,
            confirm_digest=
                plan["digest"],
        )

    assert fake_session.commits == 0
    assert fake_session.rollbacks == 1
    assert fake_session.closed == 1


def test_apply_refuses_wrong_plan_digest_before_db(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configure_fake_gate(
        monkeypatch
    )

    path = (
        tmp_path
        / "plan.json"
    )

    asyncio.run(
        bulk_cli
        .generate_catalog_plan(
            path,
            resume=False,
        )
    )

    monkeypatch.setattr(
        bulk_cli,
        "SessionLocal",
        lambda: pytest.fail(
            "DB session must not open "
            "for digest mismatch"
        ),
    )

    with pytest.raises(
        bulk_cli
        .DonationCatalogBootstrapError
    ):
        bulk_cli.apply_catalog_plan(
            path,
            confirm_digest=
                "0" * 64,
        )


def test_tampered_plan_is_rejected(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configure_fake_gate(
        monkeypatch
    )

    path = (
        tmp_path
        / "plan.json"
    )

    asyncio.run(
        bulk_cli
        .generate_catalog_plan(
            path,
            resume=False,
        )
    )

    data = json.loads(
        path.read_text(
            encoding="utf-8",
        )
    )

    ready = next(
        route
        for route in data["routes"]
        if route["status"]
        == "ready"
    )

    ready["address"] = (
        ready["address"]
        + "-tampered"
    )

    path.write_text(
        json.dumps(
            data
        ),
        encoding="utf-8",
    )

    path.chmod(
        0o600
    )

    with pytest.raises(
        bulk_cli
        .DonationCatalogBootstrapError
    ):
        bulk_cli._load_plan(
            path
        )


def test_bulk_tool_contains_no_http_or_schema_migration_surface() -> None:
    source = Path(
        bulk_cli.__file__
    ).read_text(
        encoding="utf-8",
    )

    for forbidden in (
        "APIRouter",
        "@router.",
        "FastAPI",
        "HTTPException",
        "migrate_database",
        "init_db",
        "create_all",
    ):
        assert forbidden not in source


def test_apply_path_does_not_reference_gate_client() -> None:
    import inspect

    source = inspect.getsource(
        bulk_cli.apply_catalog_plan
    )

    assert "GateClient" not in source
    assert "list_spot_currencies" not in source
    assert "list_currency_chains" not in source
    assert "get_deposit_address" not in source

def test_operator_plan_path_preserves_final_symlink(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "target.json"
    )

    target.write_text(
        "{}\n",
        encoding="utf-8",
    )

    target.chmod(
        0o600
    )

    link = (
        tmp_path
        / "plan-link.json"
    )

    link.symlink_to(
        target
    )

    normalized = (
        bulk_cli._operator_plan_path(
            str(
                link
            )
        )
    )

    assert normalized == link
    assert normalized.is_symlink()

    with pytest.raises(
        bulk_cli
        .DonationCatalogBootstrapError,
        match="symlink",
    ):
        bulk_cli._load_plan(
            normalized
        )


def test_apply_refuses_stale_ready_route_before_db(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configure_fake_gate(
        monkeypatch
    )

    path = (
        tmp_path
        / "plan.json"
    )

    plan = asyncio.run(
        bulk_cli
        .generate_catalog_plan(
            path,
            resume=False,
        )
    )

    for route in plan[
        "routes"
    ]:
        if route[
            "status"
        ] == "ready":
            route[
                "observed_at"
            ] = (
                "2000-01-01T00:00:00+00:00"
            )

    plan[
        "completed_at"
    ] = (
        bulk_cli._utc_now()
    )

    bulk_cli._write_plan(
        path,
        plan,
    )

    monkeypatch.setattr(
        bulk_cli,
        "_trust_table_exists",
        lambda: pytest.fail(
            "Trust-table inspection must not "
            "occur for stale routes"
        ),
    )

    monkeypatch.setattr(
        bulk_cli,
        "SessionLocal",
        lambda: pytest.fail(
            "DB session must not open "
            "for stale routes"
        ),
    )

    with pytest.raises(
        bulk_cli
        .DonationCatalogBootstrapError,
        match="routes are stale",
    ):
        bulk_cli.apply_catalog_plan(
            path,
            confirm_digest=
                plan["digest"],
        )
