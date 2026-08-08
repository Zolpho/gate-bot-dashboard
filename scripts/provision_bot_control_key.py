#!/usr/bin/env python3

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GATE_BASE = "https://api.gateio.ws/api/v4"

MONITOR_FILE = Path("secrets/gate_accounts.json")
CONTROL_FILE = Path("secrets/gate_bot_control.json")

KEY_NAME = "eqty-dashboard-bot-control"

EXPECTED_PERMISSIONS = {
    "quant": False,   # READ-WRITE
    "wallet": True,   # READ-ONLY
    "spot": True,     # READ-ONLY
    "account": True,  # READ-ONLY
}


class GateError(RuntimeError):
    pass


def gate_request(
    *,
    api_key: str,
    api_secret: str,
    method: str,
    endpoint: str,
    body: Any = None,
    query: list[tuple[str, Any]] | None = None,
    timeout: float = 30.0,
) -> Any:
    method = method.upper()

    parsed = urllib.parse.urlsplit(GATE_BASE)
    prefix = parsed.path.rstrip("/")

    endpoint = "/" + endpoint.lstrip("/")

    query_string = urllib.parse.urlencode(
        query or [],
        doseq=True,
    )

    if body is None:
        body_bytes = b""
    else:
        body_bytes = json.dumps(
            body,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    timestamp = str(int(time.time()))

    body_hash = hashlib.sha512(
        body_bytes
    ).hexdigest()

    sign_payload = "\n".join([
        method,
        prefix + endpoint,
        query_string,
        body_hash,
        timestamp,
    ])

    signature = hmac.new(
        api_secret.encode("utf-8"),
        sign_payload.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()

    url = GATE_BASE + endpoint

    if query_string:
        url += "?" + query_string

    headers = {
        "Accept": "application/json",
        "KEY": api_key,
        "Timestamp": timestamp,
        "SIGN": signature,
        "User-Agent": "EQTY-Gate-Bot-Control-Provisioner/1.0",
    }

    if body is not None:
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=body_bytes if body is not None else None,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            raw = response.read()

            if not raw:
                return None

            return json.loads(raw)

    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw

        raise GateError(
            f"Gate HTTP {exc.code}: {payload}"
        ) from exc

    except urllib.error.URLError as exc:
        raise GateError(
            f"Gate network error: {exc.reason}"
        ) from exc


def load_accounts(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"accounts": []}

    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    if (
        not isinstance(payload, dict)
        or not isinstance(
            payload.get("accounts"),
            list,
        )
    ):
        raise RuntimeError(
            f"{path} must contain an accounts array"
        )

    return payload


def find_account(
    payload: dict[str, Any],
    account_id: str,
) -> dict[str, Any]:
    normalized = account_id.strip().lower()

    matches = [
        item
        for item in payload["accounts"]
        if str(
            item.get("id", "")
        ).strip().lower() == normalized
    ]

    if len(matches) != 1:
        raise RuntimeError(
            f"Account {normalized!r} not found "
            f"uniquely in {MONITOR_FILE}"
        )

    return matches[0]


def save_atomically(
    path: Path,
    payload: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    os.chmod(path.parent, 0o700)

    if path.exists():
        stamp = datetime.now(
            timezone.utc
        ).strftime("%Y%m%dT%H%M%SZ")

        backup = path.with_name(
            f"{path.name}.bak.{stamp}"
        )

        shutil.copy2(
            path,
            backup,
        )

        os.chmod(
            backup,
            0o600,
        )

        print(
            f"Local backup: {backup}"
        )

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )

    temp_path = Path(temp_name)

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                payload,
                handle,
                indent=2,
                ensure_ascii=False,
            )

            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.chmod(
            temp_path,
            0o600,
        )

        os.replace(
            temp_path,
            path,
        )

        os.chmod(
            path,
            0o600,
        )

    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def list_subaccounts(
    parent_key: str,
    parent_secret: str,
) -> list[dict[str, Any]]:
    result = gate_request(
        api_key=parent_key,
        api_secret=parent_secret,
        method="GET",
        endpoint="/sub_accounts",
        query=[("type", "0")],
    )

    if not isinstance(result, list):
        raise GateError(
            "Unexpected Gate subaccount response"
        )

    return [
        item
        for item in result
        if isinstance(item, dict)
    ]


def list_subaccount_keys(
    parent_key: str,
    parent_secret: str,
    gate_uid: str,
) -> list[dict[str, Any]]:
    result = gate_request(
        api_key=parent_key,
        api_secret=parent_secret,
        method="GET",
        endpoint=(
            f"/sub_accounts/"
            f"{urllib.parse.quote(gate_uid, safe='')}"
            f"/keys"
        ),
    )

    if not isinstance(result, list):
        raise GateError(
            "Unexpected Gate API-key list response"
        )

    return [
        item
        for item in result
        if isinstance(item, dict)
    ]


def permission_map(
    key_data: dict[str, Any],
) -> dict[str, bool]:
    result: dict[str, bool] = {}

    for permission in (
        key_data.get("perms")
        or []
    ):
        if not isinstance(permission, dict):
            continue

        name = str(
            permission.get("name", "")
        ).strip().lower()

        if not name:
            continue

        result[name] = bool(
            permission.get("read_only")
        )

    return result


def verify_permissions(
    key_data: dict[str, Any],
) -> None:
    actual = permission_map(
        key_data
    )

    errors = []

    for name, expected_read_only in (
        EXPECTED_PERMISSIONS.items()
    ):
        if name not in actual:
            errors.append(
                f"{name}: missing"
            )
            continue

        if actual[name] != expected_read_only:
            expected = (
                "READ-ONLY"
                if expected_read_only
                else "READ-WRITE"
            )

            actual_mode = (
                "READ-ONLY"
                if actual[name]
                else "READ-WRITE"
            )

            errors.append(
                f"{name}: expected {expected}, "
                f"got {actual_mode}"
            )

    if errors:
        raise GateError(
            "Bot Control permission verification "
            "failed: "
            + "; ".join(errors)
        )


def delete_remote_key(
    parent_key: str,
    parent_secret: str,
    gate_uid: str,
    api_key: str,
) -> None:
    gate_request(
        api_key=parent_key,
        api_secret=parent_secret,
        method="DELETE",
        endpoint=(
            f"/sub_accounts/"
            f"{urllib.parse.quote(gate_uid, safe='')}"
            f"/keys/"
            f"{urllib.parse.quote(api_key, safe='')}"
        ),
    )


def test_new_key(
    api_key: str,
    api_secret: str,
    expected_uid: str,
) -> None:
    last_error = None

    for attempt in range(1, 11):
        try:
            account = gate_request(
                api_key=api_key,
                api_secret=api_secret,
                method="GET",
                endpoint="/account/detail",
            )

            if str(
                account.get("user_id", "")
            ) != str(expected_uid):
                raise GateError(
                    "New credential authenticated as "
                    f"user_id={account.get('user_id')}, "
                    f"expected {expected_uid}"
                )

            bots = gate_request(
                api_key=api_key,
                api_secret=api_secret,
                method="GET",
                endpoint="/bot/portfolio/running",
                query=[
                    ("page", 1),
                    ("page_size", 1),
                ],
            )

            if isinstance(bots, dict):
                code = bots.get("code")

                if code not in (
                    None,
                    0,
                    "0",
                    200,
                    "200",
                ):
                    raise GateError(
                        f"Bot API returned: {bots}"
                    )

            return

        except Exception as exc:
            last_error = exc

            if attempt == 10:
                break

            time.sleep(3)

    raise GateError(
        "New Bot Control key did not become "
        f"usable: {last_error}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--account-id",
        required=True,
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually create and save the Bot Control key",
    )

    args = parser.parse_args()

    monitor_payload = load_accounts(
        MONITOR_FILE
    )

    monitor_account = find_account(
        monitor_payload,
        args.account_id,
    )

    account_id = str(
        monitor_account["id"]
    ).strip().lower()

    display_name = str(
        monitor_account.get("name")
        or account_id
    ).strip()

    gate_uid = str(
        monitor_account.get("gate_uid")
        or ""
    ).strip()

    monitor_key = str(
        monitor_account.get("api_key")
        or ""
    ).strip()

    if not gate_uid:
        raise RuntimeError(
            f"{account_id} has no gate_uid"
        )

    control_payload = load_accounts(
        CONTROL_FILE
    )

    existing_local = [
        item
        for item in control_payload["accounts"]
        if str(
            item.get("id", "")
        ).strip().lower() == account_id
    ]

    if existing_local:
        raise RuntimeError(
            f"{account_id} already exists in "
            f"{CONTROL_FILE}"
        )

    print(
        "Enter the MAIN-account Gate API "
        "credential authorized to manage "
        "subaccount API keys."
    )

    parent_key = getpass.getpass(
        "Main Gate API key: "
    ).strip()

    parent_secret = getpass.getpass(
        "Main Gate API secret: "
    ).strip()

    if not parent_key or not parent_secret:
        raise RuntimeError(
            "Main Gate credentials are required"
        )

    subaccounts = list_subaccounts(
        parent_key,
        parent_secret,
    )

    matches = [
        item
        for item in subaccounts
        if str(
            item.get("user_id", "")
        ) == gate_uid
    ]

    if len(matches) != 1:
        raise RuntimeError(
            f"{account_id} / Gate UID {gate_uid} "
            "is not a child subaccount of this "
            "main account.\n"
            "Main-account credentials such as "
            "zolnode must be created manually "
            "in Gate and imported separately."
        )

    subaccount = matches[0]

    keys = list_subaccount_keys(
        parent_key,
        parent_secret,
        gate_uid,
    )

    bot_control_matches = [
        item
        for item in keys
        if str(
            item.get("name", "")
        ).strip().lower() == KEY_NAME.lower()
    ]

    if bot_control_matches:
        raise RuntimeError(
            f"A Gate key named {KEY_NAME!r} "
            f"already exists for {account_id}. "
            "Not creating a duplicate."
        )

    monitor_remote = next(
        (
            item
            for item in keys
            if str(
                item.get("key", "")
            ) == monitor_key
        ),
        None,
    )

    if monitor_remote is None:
        raise RuntimeError(
            "Could not find the currently configured "
            "Monitor key in Gate's subaccount key list."
        )

    ip_whitelist = [
        str(item).strip()
        for item in (
            monitor_remote.get("ip_whitelist")
            or []
        )
        if str(item).strip()
    ]

    if not ip_whitelist:
        raise RuntimeError(
            "Monitor key has no IP whitelist. "
            "Refusing to create an unrestricted "
            "Bot Control key."
        )

    print()
    print("=== Bot Control provisioning plan ===")
    print(
        f"Dashboard account: {account_id}"
    )
    print(
        "Gate login:        "
        f"{subaccount.get('login_name')}"
    )
    print(
        f"Gate user ID:      {gate_uid}"
    )
    print(
        f"Key name:          {KEY_NAME}"
    )
    print(
        "IP whitelist:      "
        + ", ".join(ip_whitelist)
    )
    print()
    print("Permissions:")
    print("  quant    READ-WRITE")
    print("  wallet   READ-ONLY")
    print("  spot     READ-ONLY")
    print("  account  READ-ONLY")
    print()
    print(
        f"Storage: {CONTROL_FILE}"
    )

    if not args.apply:
        print()
        print(
            "DRY RUN ONLY — no Gate key was created."
        )
        print(
            "Run again with --apply to proceed."
        )
        return 0

    confirmation = input(
        f"\nType {account_id} to create "
        "the Bot Control key: "
    ).strip().lower()

    if confirmation != account_id:
        raise RuntimeError(
            "Confirmation did not match; aborted"
        )

    created_key = ""
    created_secret = ""

    try:
        response = gate_request(
            api_key=parent_key,
            api_secret=parent_secret,
            method="POST",
            endpoint=(
                f"/sub_accounts/"
                f"{urllib.parse.quote(gate_uid, safe='')}"
                f"/keys"
            ),
            body={
                "mode": 1,
                "name": KEY_NAME,
                "perms": [
                    {
                        "name": "quant",
                        "read_only": False,
                    },
                    {
                        "name": "wallet",
                        "read_only": True,
                    },
                    {
                        "name": "spot",
                        "read_only": True,
                    },
                    {
                        "name": "account",
                        "read_only": True,
                    },
                ],
                "ip_whitelist": ip_whitelist,
            },
        )

        if not isinstance(response, dict):
            raise GateError(
                "Unexpected Gate key creation response"
            )

        created_key = str(
            response.get("key")
            or ""
        ).strip()

        created_secret = str(
            response.get("secret")
            or ""
        ).strip()

        if not created_key or not created_secret:
            raise GateError(
                "Gate did not return both key "
                "and secret"
            )

        verify_permissions(
            response
        )

        print()
        print(
            "Gate key created: ..."
            + created_key[-6:]
        )

        # Re-read Gate's authoritative configuration.
        verified_remote = None

        for _ in range(10):
            keys_after = list_subaccount_keys(
                parent_key,
                parent_secret,
                gate_uid,
            )

            verified_remote = next(
                (
                    item
                    for item in keys_after
                    if str(
                        item.get("key", "")
                    ) == created_key
                ),
                None,
            )

            if verified_remote is not None:
                break

            time.sleep(2)

        if verified_remote is None:
            raise GateError(
                "Created key was not visible "
                "in Gate key inventory"
            )

        verify_permissions(
            verified_remote
        )

        remote_whitelist = sorted(
            str(item)
            for item in (
                verified_remote.get(
                    "ip_whitelist"
                )
                or []
            )
        )

        if remote_whitelist != sorted(
            ip_whitelist
        ):
            raise GateError(
                "IP whitelist verification failed: "
                f"{remote_whitelist}"
            )

        print(
            "Gate permission verification: OK"
        )

        print(
            "Gate IP whitelist verification: OK"
        )

        test_new_key(
            created_key,
            created_secret,
            gate_uid,
        )

        print(
            "Bot API authentication test: OK"
        )

        control_payload["accounts"].append({
            "id": account_id,
            "name": display_name,
            "account_type": "subaccount",
            "gate_uid": gate_uid,
            "api_key": created_key,
            "api_secret": created_secret,
            "enabled": True,
        })

        save_atomically(
            CONTROL_FILE,
            control_payload,
        )

        print()
        print(
            f"Saved securely to {CONTROL_FILE}"
        )

        print(
            "File mode:",
            oct(
                CONTROL_FILE.stat().st_mode
                & 0o777
            ),
        )

        print()
        print(
            "SUCCESS: Bot Control credential "
            f"provisioned for {account_id}"
        )

        return 0

    except Exception:
        if created_key:
            print(
                "\nProvisioning failed after "
                "remote key creation.",
                file=sys.stderr,
            )

            print(
                "Attempting Gate rollback...",
                file=sys.stderr,
            )

            try:
                delete_remote_key(
                    parent_key,
                    parent_secret,
                    gate_uid,
                    created_key,
                )

                print(
                    "Remote Gate key deleted.",
                    file=sys.stderr,
                )

            except Exception as rollback_error:
                print(
                    "WARNING: automatic rollback "
                    "FAILED:",
                    rollback_error,
                    file=sys.stderr,
                )

                print(
                    "Delete Gate key ..."
                    + created_key[-6:]
                    + " manually.",
                    file=sys.stderr,
                )

        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())

    except KeyboardInterrupt:
        print(
            "\nCancelled.",
            file=sys.stderr,
        )
        raise SystemExit(130)

    except Exception as exc:
        print(
            f"\nERROR: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)
