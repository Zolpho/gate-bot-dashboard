from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api import donate as donate_api
from app.db import (
    Base,
    SessionLocal,
    engine,
)
from app.models import (
    PublicDonationDestination,
)


class FakeGateClient:
    address = "0xDonationAddress"
    memo = None

    catalog_calls = 0
    network_calls = 0
    deposit_address_calls = 0
    signed_account_ids: list[str] = []

    def __init__(
        self,
        settings=None,
        account=None,
    ) -> None:
        self.account = account

    async def __aenter__(self):
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
    ):
        type(self).catalog_calls += 1

        return SimpleNamespace(
            data=[
                {
                    "currency": "USDT",
                    "name": "Tether",
                    "deposit_disabled": False,
                    "chains": [
                        {
                            "chain": "BASE",
                            "name_en": "Base",
                            "is_deposit_disabled": 0,
                            "contract_address":
                                "0xToken",
                        },
                        {
                            "chain": "ETH",
                            "name_en": "Ethereum",
                            "is_deposit_disabled": 0,
                            "contract_address":
                                "0xToken",
                        },
                    ],
                },
                {
                    "currency": "EQTY",
                    "name": "EQTY",
                    "deposit_disabled": False,
                    "chains": [
                        {
                            "chain": "BASE",
                            "name_en": "Base",
                            "is_deposit_disabled": 0,
                        }
                    ],
                },
            ]
        )

    async def list_currency_chains(
        self,
        currency: str,
    ):
        type(self).network_calls += 1

        return SimpleNamespace(
            data=[
                {
                    "chain": "BASE",
                    "name_en": "Base",
                    "is_deposit_disabled": 0,
                    "contract_address":
                        "0xToken",
                },
                {
                    "chain": "ETH",
                    "name_en": "Ethereum",
                    "is_deposit_disabled": 0,
                    "contract_address":
                        "0xToken",
                },
            ]
        )

    async def get_deposit_address(
        self,
        currency: str,
    ):
        type(self).deposit_address_calls += 1

        account_id = getattr(
            self.account,
            "id",
            "",
        )

        type(self).signed_account_ids.append(
            account_id
        )

        return SimpleNamespace(
            data={
                "currency": currency,
                "min_deposit_amount": "1",
                "multichain_addresses": [
                    {
                        "chain": "BASE",
                        "address":
                            type(self).address,
                        "payment_id":
                            type(self).memo,
                        "payment_name":
                            (
                                "Memo"
                                if type(self).memo
                                else None
                            ),
                        "obtain_failed": 0,
                        "min_confirms": 10,
                    },
                    {
                        "chain": "ETH",
                        "address":
                            type(self).address,
                        "payment_id":
                            type(self).memo,
                        "payment_name":
                            (
                                "Memo"
                                if type(self).memo
                                else None
                            ),
                        "obtain_failed": 0,
                        "min_confirms": 12,
                    },
                ],
            }
        )


@pytest.fixture(autouse=True)
def clean_donation_state(
    monkeypatch,
):
    Base.metadata.create_all(
        bind=engine
    )

    with SessionLocal() as session:
        session.execute(
            delete(
                PublicDonationDestination
            )
        )
        session.commit()

    donate_api.reset_donation_runtime_caches()

    FakeGateClient.address = (
        "0xDonationAddress"
    )
    FakeGateClient.memo = None
    FakeGateClient.catalog_calls = 0
    FakeGateClient.network_calls = 0
    FakeGateClient.deposit_address_calls = 0
    FakeGateClient.signed_account_ids = []

    fake_account = SimpleNamespace(
        id="eqtydao",
        name="EQTYDAO",
        enabled=True,
        configured=True,
    )

    def fake_get_gate_account(
        account_id: str,
    ):
        assert account_id == "eqtydao"
        return fake_account

    monkeypatch.setattr(
        donate_api,
        "GateClient",
        FakeGateClient,
    )

    monkeypatch.setattr(
        donate_api,
        "get_gate_account",
        fake_get_gate_account,
    )

    monkeypatch.setattr(
        donate_api,
        "SIGNED_REFRESH_MIN_INTERVAL_SECONDS",
        0.0,
    )

    yield

    donate_api.reset_donation_runtime_caches()


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(
        donate_api.router
    )
    return TestClient(app)


def test_public_catalog_requires_no_auth(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/donate/currencies"
    )

    assert response.status_code == 200
    assert (
        response.headers[
            "cache-control"
        ]
        == "no-store"
    )

    payload = response.json()

    assert payload["destination"] == {
        "name":
            "EQTY DAO Market Making"
    }

    symbols = {
        item["currency"]
        for item in payload[
            "currencies"
        ]
    }

    assert symbols == {
        "USDT",
        "EQTY",
    }

    serialized = repr(payload)

    assert "authorized_user" not in serialized
    assert "account_id" not in serialized
    assert "api_key" not in serialized
    assert "api_secret" not in serialized

    # conftest has DEMO_MODE=true.
    # Public Donate still used the Gate read seam.
    assert FakeGateClient.catalog_calls == 1


def test_public_networks_require_no_auth(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/donate/USDT/networks"
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["currency"] == "USDT"

    chains = {
        item["chain"]
        for item in payload[
            "networks"
        ]
    }

    assert chains == {
        "BASE",
        "ETH",
    }

    for network in payload["networks"]:
        # Contract addresses are public token metadata and
        # intentionally remain visible. What this discovery
        # endpoint must not expose is an account-specific
        # deposit destination or memo/QR detail.
        assert "contract_address" in network
        assert "address" not in network
        assert "address_available" not in network
        assert "payment_id" not in network
        assert "payment_name" not in network
        assert "qr_payload" not in network
        assert "qr_svg_data_uri" not in network
        assert "withdraw_enabled" not in network


def test_public_address_is_permanently_eqtydao_scoped(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/donate/USDT",
        params={
            "chain": "BASE",
            # Caller attempts to inject another account.
            # FastAPI ignores unknown query fields and the
            # backend remains hard-pinned to EQTYDAO.
            "account_id": "zolnode",
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["currency"] == "USDT"

    assert (
        payload["network"]["address"]
        == "0xDonationAddress"
    )

    assert payload["destination"] == {
        "name":
            "EQTY DAO Market Making"
    }

    assert (
        FakeGateClient.signed_account_ids
        == ["eqtydao"]
    )

    serialized = repr(payload)

    assert "zolnode" not in serialized
    assert "'account_id'" not in serialized
    assert "authorized_user" not in serialized


def test_signed_address_read_is_cached_per_currency(
    client: TestClient,
) -> None:
    first = client.get(
        "/api/donate/USDT",
        params={
            "chain": "BASE",
        },
    )

    second = client.get(
        "/api/donate/USDT",
        params={
            "chain": "ETH",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200

    # Gate returns all multichain addresses in one
    # signed currency-level response, so selecting a
    # second network does not create another signed read.
    assert (
        FakeGateClient.deposit_address_calls
        == 1
    )


def test_invalid_network_uses_no_signed_gate_read(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/donate/USDT",
        params={
            "chain": "NOT-A-CHAIN",
        },
    )

    assert response.status_code == 404

    assert (
        FakeGateClient.deposit_address_calls
        == 0
    )


def test_gate_address_change_fails_closed(
    client: TestClient,
) -> None:
    first = client.get(
        "/api/donate/USDT",
        params={
            "chain": "BASE",
        },
    )

    assert first.status_code == 200

    FakeGateClient.address = (
        "0xUnexpectedNewAddress"
    )

    # Force the next request through the Gate-read seam.
    # Durable destination trust is deliberately preserved.
    donate_api.reset_donation_runtime_caches()

    second = client.get(
        "/api/donate/USDT",
        params={
            "chain": "BASE",
        },
    )

    assert second.status_code == 503

    assert second.json() == {
        "detail":
            "Donation destination "
            "temporarily unavailable"
    }

    with SessionLocal() as session:
        row = session.query(
            PublicDonationDestination
        ).one()

        assert row.status == "blocked"
        assert (
            row.address
            == "0xDonationAddress"
        )
        assert (
            row.observed_address
            == "0xUnexpectedNewAddress"
        )


def test_blocked_destination_does_not_auto_recover(
    client: TestClient,
) -> None:
    first = client.get(
        "/api/donate/USDT",
        params={
            "chain": "BASE",
        },
    )

    assert first.status_code == 200

    FakeGateClient.address = "0xChanged"

    donate_api.reset_donation_runtime_caches()

    changed = client.get(
        "/api/donate/USDT",
        params={
            "chain": "BASE",
        },
    )

    assert changed.status_code == 503

    FakeGateClient.address = (
        "0xDonationAddress"
    )

    donate_api.reset_donation_runtime_caches()

    restored = client.get(
        "/api/donate/USDT",
        params={
            "chain": "BASE",
        },
    )

    assert restored.status_code == 503


def test_memo_change_also_fails_closed(
    client: TestClient,
) -> None:
    FakeGateClient.memo = "111"

    first = client.get(
        "/api/donate/USDT",
        params={
            "chain": "BASE",
        },
    )

    assert first.status_code == 200

    FakeGateClient.memo = "222"

    donate_api.reset_donation_runtime_caches()

    second = client.get(
        "/api/donate/USDT",
        params={
            "chain": "BASE",
        },
    )

    assert second.status_code == 503

    with SessionLocal() as session:
        row = session.query(
            PublicDonationDestination
        ).one()

        assert row.memo == "111"
        assert row.observed_memo == "222"


def test_donate_router_is_get_only() -> None:
    methods = set()

    for route in donate_api.router.routes:
        methods.update(
            method
            for method in route.methods
            if method not in {
                "HEAD",
                "OPTIONS",
            }
        )

    assert methods == {
        "GET"
    }
