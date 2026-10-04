from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from scripts import (
    bootstrap_public_donation_destination
    as bootstrap_cli,
)


class FakeGateClient:
    calls: list[
        tuple[
            str,
            str,
        ]
    ] = []

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

        return SimpleNamespace(
            data=[
                {
                    "chain": "BASEEVM",
                    "name_en": "Base",
                    "is_deposit_disabled": 0,
                },
            ]
        )

    async def get_deposit_address(
        self,
        currency: str,
    ):
        type(self).calls.append(
            (
                "address",
                getattr(
                    self.account,
                    "id",
                    "",
                ),
            )
        )

        return SimpleNamespace(
            data={
                "currency": currency,
                "min_deposit_amount": "1",
                "multichain_addresses": [
                    {
                        "chain": "BASEEVM",
                        "address":
                            "0xAbCdEf",
                        "payment_id": None,
                        "obtain_failed": 0,
                        "min_confirms": 5,
                    },
                ],
            }
        )


@pytest.fixture(autouse=True)
def reset_fake() -> None:
    FakeGateClient.calls = []


def test_parser_has_no_wallet_account_override() -> None:
    parser = (
        bootstrap_cli.build_parser()
    )

    destinations = {
        action.dest
        for action in parser._actions
    }

    assert "currency" in destinations
    assert "chain" in destinations
    assert "expected_address" in destinations
    assert "expected_memo" in destinations
    assert "apply" in destinations

    assert "account" not in destinations
    assert "account_id" not in destinations


def test_expected_evm_address_is_case_insensitive() -> None:
    payload = {
        "currency": "EQTY",
        "network": {
            "chain": "BASEEVM",
            "address": "0xAbCdEf",
            "payment_id": None,
        },
    }

    assert (
        bootstrap_cli.destination_matches_expected(
            payload,
            expected_address="0xabcdef",
            expected_memo="",
        )
    )


def test_expected_memo_must_match() -> None:
    payload = {
        "currency": "USDT",
        "network": {
            "chain": "ETH",
            "address": "0xAbCdEf",
            "payment_id": "111",
        },
    }

    assert not (
        bootstrap_cli.destination_matches_expected(
            payload,
            expected_address="0xabcdef",
            expected_memo="222",
        )
    )


def test_observation_uses_fixed_eqtydao_and_gate_gets(
    monkeypatch,
) -> None:
    fake_account = SimpleNamespace(
        id="eqtydao",
        enabled=True,
        configured=True,
    )

    monkeypatch.setattr(
        bootstrap_cli,
        "GateClient",
        FakeGateClient,
    )

    monkeypatch.setattr(
        bootstrap_cli,
        "get_settings",
        lambda: SimpleNamespace(),
    )

    def fake_get_gate_account(
        account_id: str,
    ):
        assert account_id == "eqtydao"
        return fake_account

    monkeypatch.setattr(
        bootstrap_cli,
        "get_gate_account",
        fake_get_gate_account,
    )

    payload = asyncio.run(
        bootstrap_cli
        .observe_public_donation_destination(
            currency="EQTY",
            chain="BASEEVM",
        )
    )

    assert payload["currency"] == "EQTY"

    assert (
        payload["network"]["chain"]
        == "BASEEVM"
    )

    assert (
        payload["network"]["address"]
        == "0xAbCdEf"
    )

    assert FakeGateClient.calls == [
        (
            "networks",
            "EQTY",
        ),
        (
            "address",
            "eqtydao",
        ),
    ]


def test_cli_does_not_migrate_schema() -> None:
    source = inspect.getsource(
        bootstrap_cli
    )

    assert "init_db" not in source
    assert "migrate_database" not in source
    assert "create_all" not in source


def test_cli_requires_apply_for_database_write_path() -> None:
    source = inspect.getsource(
        bootstrap_cli.run
    )

    assert "if not args.apply" in source

    preview_index = source.index(
        "if not args.apply"
    )

    session_index = source.index(
        "session = SessionLocal()"
    )

    assert (
        preview_index
        < session_index
    )


def test_cli_has_no_http_bootstrap_surface() -> None:
    source = inspect.getsource(
        bootstrap_cli
    )

    for forbidden in (
        "APIRouter",
        "@router.",
        "FastAPI",
        "HTTPException",
    ):
        assert forbidden not in source
