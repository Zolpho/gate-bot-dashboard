#!/usr/bin/env python3
"""Onboard an existing Gate sub-account into the EQTY Gate bot dashboard.

The script can create a new Gate API key pair for an already-existing
sub-account, write the credentials to secrets/gate_accounts.json, and create the
matching account-scoped dashboard login in secrets/dashboard_users.json.

Parent/main-account Gate credentials are used only in memory and are never
written to disk. Local JSON changes are backed up and written atomically. If a
new remote Gate key is created but local onboarding fails, the script attempts
to delete that key again.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

DEFAULT_ACCOUNTS_FILE = Path("secrets/gate_accounts.json")
DEFAULT_USERS_FILE = Path("secrets/dashboard_users.json")
DEFAULT_GATE_BASE_URL = "https://api.gateio.ws/api/v4"
DEFAULT_PBKDF2_ITERATIONS = 600_000
DEFAULT_KEY_NAME = "eqty-dashboard-read"
DEFAULT_PERMISSIONS = ("quant", "wallet", "spot", "account")

ACCOUNT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
ALLOWED_GATE_PERMISSIONS = {
    "quant",
    "wallet",
    "spot",
    "futures",
    "delivery",
    "earn",
    "custody",
    "options",
    "account",
    "loan",
    "margin",
    "unified",
    "copy",
}


class ConfigurationError(RuntimeError):
    """Raised when local onboarding configuration is invalid."""


class GateAPIError(RuntimeError):
    """Raised when Gate rejects an API request or returns invalid data."""

    def __init__(self, message: str, *, status_code: int | None = None, response: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


def _encode_b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def hash_password(password: str, *, iterations: int = DEFAULT_PBKDF2_ITERATIONS) -> str:
    """Return a hash compatible with app.security.verify_password()."""
    if len(password) < 12:
        raise ValueError("Dashboard password must contain at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_encode_b64(salt)}${_encode_b64(digest)}"


def prompt_secret(label: str, *, env_name: str | None = None) -> str:
    if env_name:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    while True:
        value = getpass.getpass(label).strip()
        if value:
            return value
        print("Error: value cannot be empty", file=sys.stderr)


def prompt_password() -> str:
    while True:
        first = getpass.getpass("Dashboard password (minimum 12 characters): ")
        second = getpass.getpass("Confirm dashboard password: ")
        if first != second:
            print("Error: passwords do not match", file=sys.stderr)
            continue
        try:
            hash_password(first)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            continue
        return first


def normalize_account_id(value: str) -> str:
    account_id = value.strip().lower()
    if not ACCOUNT_ID_RE.fullmatch(account_id):
        raise ValueError(
            "Account ID must use 1-64 lowercase letters, numbers, '_' or '-', "
            "and start with a letter or number"
        )
    return account_id


def normalize_username(value: str) -> str:
    username = value.strip().lower()
    if not USERNAME_RE.fullmatch(username):
        raise ValueError(
            "Username must use 1-64 lowercase letters, numbers, '.', '_' or '-', "
            "and start with a letter or number"
        )
    return username


def read_json(path: Path, *, root_key: str) -> dict[str, Any]:
    if not path.exists():
        return {root_key: []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(f"Cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get(root_key), list):
        raise ConfigurationError(f"{path} must contain an object with a '{root_key}' array")
    return payload


def validate_local_accounts(payload: dict[str, Any], path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(payload["accounts"], start=1):
        if not isinstance(raw, dict):
            raise ConfigurationError(f"Gate account entry {index} in {path} must be an object")
        account_id = str(raw.get("id", "")).strip().lower()
        if not ACCOUNT_ID_RE.fullmatch(account_id):
            raise ConfigurationError(f"Invalid Gate account id at entry {index}: {account_id!r}")
        if account_id in result:
            raise ConfigurationError(f"Duplicate Gate account id in {path}: {account_id}")
        result[account_id] = raw
    return result


def validate_local_users(payload: dict[str, Any], path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(payload["users"], start=1):
        if not isinstance(raw, dict):
            raise ConfigurationError(f"Dashboard user entry {index} in {path} must be an object")
        username = str(raw.get("username", "")).strip().lower()
        if not USERNAME_RE.fullmatch(username):
            raise ConfigurationError(f"Invalid dashboard username at entry {index}: {username!r}")
        if username in result:
            raise ConfigurationError(f"Duplicate dashboard username in {path}: {username}")
        result[username] = raw
    return result


def account_assignment_conflicts(users: Iterable[dict[str, Any]], account_id: str) -> list[str]:
    conflicts: list[str] = []
    for user in users:
        if not isinstance(user, dict) or not bool(user.get("enabled", True)):
            continue
        if str(user.get("role") or "account_operator").strip().lower() != "account_operator":
            continue
        account_ids = {
            str(value).strip().lower()
            for value in (user.get("account_ids") or [])
            if str(value).strip()
        }
        if account_id in account_ids:
            username = str(user.get("username", "")).strip().lower()
            if username:
                conflicts.append(username)
    return sorted(set(conflicts))


def snapshot_file(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.bak.{timestamp}")
    shutil.copy2(path, backup)
    os.chmod(backup, 0o600)
    return backup


def save_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def restore_snapshot(path: Path, snapshot: bytes | None) -> None:
    if snapshot is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.restore.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(snapshot)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _decode_response(raw_bytes: bytes, content_type: str = "") -> Any:
    text = raw_bytes.decode("utf-8", errors="replace")
    if "json" in content_type.lower() or text[:1] in {"{", "["}:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return text


def gate_request(
    *,
    api_key: str,
    api_secret: str,
    method: str,
    endpoint: str,
    base_url: str,
    query: Sequence[tuple[str, Any]] | None = None,
    body: Any = None,
    timeout: float = 20.0,
) -> Any:
    """Call a signed Gate API v4 endpoint using only the Python standard library."""
    method = method.upper()
    base_url = base_url.rstrip("/")
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError(f"Invalid Gate base URL: {base_url}")
    prefix = parsed.path.rstrip("/")
    endpoint = "/" + endpoint.lstrip("/")
    query_string = urllib.parse.urlencode(query or [], doseq=True)
    body_bytes = (
        json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if body is not None
        else b""
    )
    timestamp = str(int(time.time()))
    body_hash = hashlib.sha512(body_bytes).hexdigest()
    sign_payload = f"{method}\n{prefix}{endpoint}\n{query_string}\n{body_hash}\n{timestamp}"
    signature = hmac.new(
        api_secret.encode("utf-8"), sign_payload.encode("utf-8"), hashlib.sha512
    ).hexdigest()

    url = f"{base_url}{endpoint}"
    if query_string:
        url = f"{url}?{query_string}"
    headers = {
        "Accept": "application/json",
        "KEY": api_key,
        "Timestamp": timestamp,
        "SIGN": signature,
        "User-Agent": "EQTY-Gate-Dashboard-Onboarding/1.0",
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return _decode_response(raw, response.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        decoded = _decode_response(raw, exc.headers.get("Content-Type", "") if exc.headers else "")
        if isinstance(decoded, dict):
            detail = decoded.get("message") or decoded.get("detail") or decoded.get("label") or decoded
        else:
            detail = decoded
        raise GateAPIError(
            f"Gate API returned HTTP {exc.code}: {detail}",
            status_code=exc.code,
            response=decoded,
        ) from exc
    except urllib.error.URLError as exc:
        raise GateAPIError(f"Gate network error: {exc.reason}") from exc


def ensure_bot_api_success(payload: Any) -> None:
    if isinstance(payload, dict):
        code = payload.get("code")
        if code not in (None, 0, "0", 200, "200"):
            message = payload.get("message") or payload.get("detail") or "Unknown Gate bot API error"
            raise GateAPIError(f"Gate bot API error {code}: {message}", response=payload)


def list_subaccounts(parent_key: str, parent_secret: str, *, base_url: str, timeout: float) -> list[dict[str, Any]]:
    payload = gate_request(
        api_key=parent_key,
        api_secret=parent_secret,
        method="GET",
        endpoint="/sub_accounts",
        base_url=base_url,
        query=[("type", "1")],
        timeout=timeout,
    )
    if not isinstance(payload, list):
        raise GateAPIError("Gate returned an invalid sub-account list", response=payload)
    result = [item for item in payload if isinstance(item, dict)]
    if not result:
        raise GateAPIError("Gate returned no regular sub-accounts")
    return result


def select_subaccount(
    subaccounts: list[dict[str, Any]],
    *,
    requested_login: str | None,
    requested_user_id: str | None,
) -> dict[str, Any]:
    if requested_user_id:
        matches = [item for item in subaccounts if str(item.get("user_id", "")) == requested_user_id.strip()]
        if len(matches) != 1:
            raise ConfigurationError(f"Could not find Gate sub-account user_id={requested_user_id}")
        selected = matches[0]
    elif requested_login:
        normalized = requested_login.strip().lower()
        matches = [
            item
            for item in subaccounts
            if str(item.get("login_name", "")).strip().lower() == normalized
        ]
        if len(matches) != 1:
            raise ConfigurationError(f"Could not uniquely find Gate sub-account login_name={requested_login}")
        selected = matches[0]
    else:
        ordered = sorted(subaccounts, key=lambda item: str(item.get("login_name", "")).lower())
        print("Available Gate sub-accounts:")
        for index, item in enumerate(ordered, start=1):
            state = "normal" if int(item.get("state", 0) or 0) == 1 else f"state={item.get('state')}"
            print(
                f"  {index}. {item.get('login_name')} "
                f"(user_id={item.get('user_id')}, {state})"
            )
        while True:
            value = input("Select Gate sub-account by number or login name: ").strip()
            if value.isdigit() and 1 <= int(value) <= len(ordered):
                selected = ordered[int(value) - 1]
                break
            matches = [
                item
                for item in ordered
                if str(item.get("login_name", "")).strip().lower() == value.lower()
            ]
            if len(matches) == 1:
                selected = matches[0]
                break
            print("Error: select one of the listed sub-accounts", file=sys.stderr)

    login_name = str(selected.get("login_name", "")).strip()
    user_id = str(selected.get("user_id", "")).strip()
    if not login_name or not user_id:
        raise GateAPIError("Selected Gate sub-account is missing login_name or user_id", response=selected)
    return selected


def normalize_permissions(values: list[str]) -> list[str]:
    source = values or list(DEFAULT_PERMISSIONS)
    result: list[str] = []
    for raw in source:
        for value in raw.split(","):
            permission = value.strip().lower()
            if not permission:
                continue
            if permission not in ALLOWED_GATE_PERMISSIONS:
                raise ValueError(f"Unsupported Gate permission: {permission}")
            if permission not in result:
                result.append(permission)
    if not result:
        raise ValueError("At least one Gate permission is required")
    return result


def normalize_ip_whitelist(values: list[str], *, allow_empty: bool, allow_non_global: bool) -> list[str]:
    result: list[str] = []
    for raw in values:
        for value in raw.split(","):
            candidate = value.strip()
            if not candidate:
                continue
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError as exc:
                raise ValueError(f"Invalid IP whitelist address: {candidate}") from exc
            if not address.is_global and not allow_non_global:
                raise ValueError(
                    f"IP whitelist address {candidate} is not a public/global IP. "
                    "Use the public egress/NAT IP seen by Gate, or pass --allow-non-global-ip."
                )
            canonical = str(address)
            if canonical not in result:
                result.append(canonical)
    if not result and not allow_empty:
        raise ValueError(
            "At least one public egress IP is required for the Gate key whitelist. "
            "Pass --allow-empty-ip-whitelist only when intentionally creating an unrestricted key."
        )
    return result


def prompt_ip_whitelist(*, allow_empty: bool, allow_non_global: bool) -> list[str]:
    while True:
        raw = input(
            "Public egress IP(s) for the Gate API whitelist, comma-separated: "
        ).strip()
        try:
            return normalize_ip_whitelist(
                [raw], allow_empty=allow_empty, allow_non_global=allow_non_global
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)


def create_subaccount_key(
    *,
    parent_key: str,
    parent_secret: str,
    user_id: str,
    key_name: str,
    key_mode: int,
    permissions: list[str],
    ip_whitelist: list[str],
    base_url: str,
    timeout: float,
) -> tuple[str, str, dict[str, Any]]:
    payload = gate_request(
        api_key=parent_key,
        api_secret=parent_secret,
        method="POST",
        endpoint=f"/sub_accounts/{urllib.parse.quote(user_id, safe='')}/keys",
        base_url=base_url,
        body={
            "mode": key_mode,
            "name": key_name,
            "perms": [
                {"name": permission, "read_only": True} for permission in permissions
            ],
            "ip_whitelist": ip_whitelist,
        },
        timeout=timeout,
    )
    if not isinstance(payload, dict):
        raise GateAPIError("Gate returned an invalid API-key creation response", response=payload)
    api_key = str(payload.get("key", "")).strip()
    api_secret = str(payload.get("secret", "")).strip()
    if not api_key or not api_secret:
        raise GateAPIError(
            "Gate created a key but did not return both key and secret; onboarding cannot continue safely",
            response=payload,
        )
    return api_key, api_secret, payload


def delete_subaccount_key(
    *,
    parent_key: str,
    parent_secret: str,
    user_id: str,
    subaccount_key: str,
    base_url: str,
    timeout: float,
) -> None:
    gate_request(
        api_key=parent_key,
        api_secret=parent_secret,
        method="DELETE",
        endpoint=(
            f"/sub_accounts/{urllib.parse.quote(user_id, safe='')}/keys/"
            f"{urllib.parse.quote(subaccount_key, safe='')}"
        ),
        base_url=base_url,
        timeout=timeout,
    )


def test_subaccount_key(
    *, api_key: str, api_secret: str, base_url: str, timeout: float
) -> Any:
    payload = gate_request(
        api_key=api_key,
        api_secret=api_secret,
        method="GET",
        endpoint="/bot/portfolio/running",
        base_url=base_url,
        query=[("page", 1), ("page_size", 1)],
        timeout=timeout,
    )
    ensure_bot_api_success(payload)
    return payload


def prompt_existing_key() -> tuple[str, str]:
    api_key = prompt_secret("Existing sub-account API key: ")
    api_secret = prompt_secret("Existing sub-account API secret: ")
    return api_key, api_secret


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a Gate sub-account API key, add it to gate_accounts.json, "
            "and create the matching account-scoped dashboard user"
        )
    )
    parser.add_argument("--accounts-file", default=str(DEFAULT_ACCOUNTS_FILE))
    parser.add_argument("--users-file", default=str(DEFAULT_USERS_FILE))
    parser.add_argument("--gate-base-url", default=DEFAULT_GATE_BASE_URL)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--api-source",
        choices=("create", "existing"),
        default="create",
        help="Create a new Gate sub-account key or register an already-created key",
    )
    parser.add_argument("--subaccount-login", help="Existing Gate sub-account login name")
    parser.add_argument("--subaccount-user-id", help="Existing Gate sub-account numeric user ID")
    parser.add_argument("--account-id", help="Local dashboard account ID; defaults to Gate login name")
    parser.add_argument("--display-name", help="Public account display name")
    parser.add_argument("--username", help="Dashboard username; defaults to account ID")
    parser.add_argument("--key-name", default=DEFAULT_KEY_NAME)
    parser.add_argument(
        "--key-mode", type=int, choices=(1, 2), default=1, help="Gate key mode: 1 classic, 2 portfolio"
    )
    parser.add_argument(
        "--permission",
        action="append",
        default=[],
        help="Read-only Gate permission; repeat or comma-separate. Defaults to quant,wallet,spot,account",
    )
    parser.add_argument(
        "--ip-whitelist",
        action="append",
        default=[],
        help="Public egress IP allowed to use the new Gate key; repeat or comma-separate",
    )
    parser.add_argument(
        "--allow-empty-ip-whitelist",
        action="store_true",
        help="Allow creating a Gate key with no IP restriction",
    )
    parser.add_argument(
        "--allow-non-global-ip",
        action="store_true",
        help="Allow private/reserved IPs in the Gate whitelist",
    )
    parser.add_argument(
        "--allow-shared-account",
        action="store_true",
        help="Allow the Gate account to be assigned to another enabled account_operator",
    )
    parser.add_argument("--skip-key-test", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Skip final confirmation")
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Restart only the gate-bot-dashboard Compose service after saving",
    )
    parser.add_argument("--compose-service", default="gate-bot-dashboard")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    accounts_path = Path(args.accounts_file)
    users_path = Path(args.users_file)

    remote_created = False
    created_key = ""
    parent_key = ""
    parent_secret = ""
    selected_user_id = ""
    accounts_snapshot: bytes | None = None
    users_snapshot: bytes | None = None
    local_committed = False

    try:
        accounts_payload = read_json(accounts_path, root_key="accounts")
        users_payload = read_json(users_path, root_key="users")
        local_accounts = validate_local_accounts(accounts_payload, accounts_path)
        local_users = validate_local_users(users_payload, users_path)

        if args.api_source == "create":
            print(
                "Enter a main-account Gate API key authorized to manage sub-account API keys.\n"
                "These credentials are used only in memory and are not stored."
            )
            parent_key = prompt_secret(
                "Main-account Gate API key: ", env_name="GATE_PARENT_API_KEY"
            )
            parent_secret = prompt_secret(
                "Main-account Gate API secret: ", env_name="GATE_PARENT_API_SECRET"
            )
            subaccounts = list_subaccounts(
                parent_key, parent_secret, base_url=args.gate_base_url, timeout=args.timeout
            )
            selected = select_subaccount(
                subaccounts,
                requested_login=args.subaccount_login,
                requested_user_id=args.subaccount_user_id,
            )
            selected_login = str(selected["login_name"]).strip()
            selected_user_id = str(selected["user_id"]).strip()
            selected_state = int(selected.get("state", 0) or 0)
            if selected_state != 1:
                raise ConfigurationError(
                    f"Gate sub-account {selected_login} is not in normal state (state={selected_state})"
                )
        else:
            selected_login = (args.subaccount_login or input("Gate sub-account login name: ")).strip()
            if not selected_login:
                raise ConfigurationError("Gate sub-account login name is required")
            selected_user_id = (args.subaccount_user_id or "").strip()

        account_id = normalize_account_id(args.account_id or selected_login)
        username = normalize_username(args.username or account_id)
        display_name = (args.display_name or selected_login).strip()
        if not display_name:
            raise ConfigurationError("Display name cannot be empty")
        if account_id in local_accounts:
            raise ConfigurationError(
                f"Gate account '{account_id}' already exists in {accounts_path}; this add-only script will not replace it"
            )
        if username in local_users:
            raise ConfigurationError(
                f"Dashboard user '{username}' already exists in {users_path}; this add-only script will not replace it"
            )
        conflicts = account_assignment_conflicts(users_payload["users"], account_id)
        if conflicts and not args.allow_shared_account:
            raise ConfigurationError(
                f"Gate account '{account_id}' is already assigned to: {', '.join(conflicts)}"
            )

        permissions = normalize_permissions(args.permission)
        if args.api_source == "create":
            ip_whitelist = (
                normalize_ip_whitelist(
                    args.ip_whitelist,
                    allow_empty=args.allow_empty_ip_whitelist,
                    allow_non_global=args.allow_non_global_ip,
                )
                if args.ip_whitelist
                else prompt_ip_whitelist(
                    allow_empty=args.allow_empty_ip_whitelist,
                    allow_non_global=args.allow_non_global_ip,
                )
            )
        else:
            ip_whitelist = []

        dashboard_password = prompt_password()

        print("\nOnboarding plan:")
        print(f"  Gate sub-account: {selected_login}")
        print(f"  Gate user ID: {selected_user_id or '(not supplied)'}")
        print(f"  Local account ID: {account_id}")
        print(f"  Display name: {display_name}")
        print(f"  Dashboard username: {username}")
        print("  Dashboard role: account_operator")
        print(f"  API source: {args.api_source}")
        if args.api_source == "create":
            print(f"  Gate key name: {args.key_name}")
            print(f"  Gate key mode: {args.key_mode}")
            print(f"  Read-only permissions: {', '.join(permissions)}")
            print(f"  IP whitelist: {', '.join(ip_whitelist) if ip_whitelist else '(none)'}")
        print(f"  Accounts file: {accounts_path}")
        print(f"  Users file: {users_path}")

        if not args.yes:
            confirmation = input("Continue? [y/N]: ").strip().lower()
            if confirmation not in {"y", "yes"}:
                print("Cancelled; no remote or local changes were made.")
                return 1

        if args.api_source == "create":
            api_key, api_secret, _created_response = create_subaccount_key(
                parent_key=parent_key,
                parent_secret=parent_secret,
                user_id=selected_user_id,
                key_name=args.key_name,
                key_mode=args.key_mode,
                permissions=permissions,
                ip_whitelist=ip_whitelist,
                base_url=args.gate_base_url,
                timeout=args.timeout,
            )
            remote_created = True
            created_key = api_key
            print(f"Created Gate API key ending in ...{api_key[-6:]}")
        else:
            api_key, api_secret = prompt_existing_key()

        if not args.skip_key_test:
            print("Testing the sub-account key against Gate bot portfolio API...")
            test_subaccount_key(
                api_key=api_key,
                api_secret=api_secret,
                base_url=args.gate_base_url,
                timeout=args.timeout,
            )
            print("Gate API key test succeeded.")

        account_record = {
            "id": account_id,
            "name": display_name,
            "account_type": "subaccount",
            "gate_uid": selected_user_id,
            "api_key": api_key,
            "api_secret": api_secret,
            "enabled": True,
        }
        user_record = {
            "username": username,
            "password_hash": hash_password(dashboard_password),
            "account_ids": [account_id],
            "role": "account_operator",
            "enabled": True,
        }

        accounts_payload["accounts"].append(account_record)
        accounts_payload["accounts"].sort(
            key=lambda item: str(item.get("id", "")).strip().lower()
        )
        users_payload["users"].append(user_record)
        users_payload["users"].sort(
            key=lambda item: str(item.get("username", "")).strip().lower()
        )

        accounts_snapshot = snapshot_file(accounts_path)
        users_snapshot = snapshot_file(users_path)
        account_backup = None if args.no_backup else backup_file(accounts_path)
        user_backup = None if args.no_backup else backup_file(users_path)

        try:
            save_json_atomically(accounts_path, accounts_payload)
            save_json_atomically(users_path, users_payload)
            local_committed = True
        except Exception:
            restore_snapshot(accounts_path, accounts_snapshot)
            restore_snapshot(users_path, users_snapshot)
            raise

        print("\nOnboarding completed.")
        print(f"  Added Gate account: {account_id}")
        print(f"  Added dashboard user: {username}")
        print(f"  Saved: {accounts_path}")
        print(f"  Saved: {users_path}")
        if account_backup:
            print(f"  Backup: {account_backup}")
        if user_backup:
            print(f"  Backup: {user_backup}")
        print("  Parent Gate credentials and plaintext dashboard password were not stored.")

        if args.restart:
            print(f"Restarting Compose service {args.compose_service}...")
            try:
                subprocess.run(
                    ["docker", "compose", "restart", args.compose_service],
                    check=True,
                )
            except (OSError, subprocess.CalledProcessError) as exc:
                print(
                    f"WARNING: Onboarding was saved, but the container restart failed: {exc}",
                    file=sys.stderr,
                )
                print(
                    "Run this manually from the project directory:\n"
                    f"  docker compose restart {args.compose_service}",
                    file=sys.stderr,
                )
                return 3
            print("Dashboard service restarted.")
        else:
            print(
                "Restart the dashboard so it copies and reloads gate_accounts.json:\n"
                f"  docker compose restart {args.compose_service}"
            )
        return 0

    except (ConfigurationError, GateAPIError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if (
            not local_committed
            and remote_created
            and created_key
            and parent_key
            and parent_secret
            and selected_user_id
        ):
            print("Attempting to delete the newly created Gate API key...", file=sys.stderr)
            try:
                delete_subaccount_key(
                    parent_key=parent_key,
                    parent_secret=parent_secret,
                    user_id=selected_user_id,
                    subaccount_key=created_key,
                    base_url=args.gate_base_url,
                    timeout=args.timeout,
                )
                print("Remote Gate API key rollback succeeded.", file=sys.stderr)
            except Exception as rollback_exc:  # noqa: BLE001 - best-effort rollback report
                print(
                    "WARNING: Could not delete the newly created Gate API key. "
                    f"Delete key ending in ...{created_key[-6:]} manually. Rollback error: {rollback_exc}",
                    file=sys.stderr,
                )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
