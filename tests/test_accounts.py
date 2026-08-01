from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.accounts import AccountConfigError, _load_from_file


def test_load_multiple_accounts_without_exposing_credentials(tmp_path: Path) -> None:
    path = tmp_path / "accounts.json"
    path.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "zolnode",
                        "name": "zolnode",
                        "api_key": "key-z",
                        "api_secret": "secret-z",
                        "enabled": True,
                    },
                    {
                        "id": "arnold",
                        "name": "Arnold",
                        "api_key": "key-a",
                        "api_secret": "secret-a",
                        "enabled": "true",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    accounts = _load_from_file(path)
    assert [account.id for account in accounts] == ["zolnode", "arnold"]
    assert accounts[0].safe_dict()["configured"] is True
    assert "api_key" not in accounts[0].safe_dict()
    assert "api_secret" not in accounts[0].safe_dict()


def test_duplicate_account_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "accounts.json"
    path.write_text(
        json.dumps(
            {
                "accounts": [
                    {"id": "zolnode", "api_key": "a", "api_secret": "b"},
                    {"id": "zolnode", "api_key": "c", "api_secret": "d"},
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AccountConfigError, match="Duplicate account"):
        _load_from_file(path)
