#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import sys
from pathlib import Path

DEFAULT_PBKDF2_ITERATIONS = 600_000


def _encode_b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def hash_password(password: str, *, iterations: int = DEFAULT_PBKDF2_ITERATIONS) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_encode_b64(salt)}${_encode_b64(digest)}"


DEFAULT_PATH = Path("secrets/dashboard_users.json")


def load_payload(path: Path) -> dict:
    if not path.exists():
        return {"users": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("users"), list):
        raise SystemExit(f"{path} must contain an object with a 'users' array")
    return payload


def save_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(path.parent, 0o700)
    os.chmod(path, 0o600)


def password_from_prompt() -> str:
    first = getpass.getpass("Password (minimum 12 characters): ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Passwords do not match")
    try:
        hash_password(first)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    return first


def add_or_update(args: argparse.Namespace) -> None:
    path = Path(args.file)
    payload = load_payload(path)
    username = args.username.strip().lower()
    accounts = sorted({value.strip().lower() for value in args.account if value.strip()})
    if args.role == "account_operator" and not accounts:
        raise SystemExit("An account_operator needs at least one --account")

    password = password_from_prompt()
    record = {
        "username": username,
        "password_hash": hash_password(password),
        "account_ids": accounts,
        "role": args.role,
        "enabled": True,
    }
    users = payload["users"]
    for index, existing in enumerate(users):
        if str(existing.get("username", "")).strip().lower() == username:
            users[index] = record
            action = "Updated"
            break
    else:
        users.append(record)
        action = "Added"
    users.sort(key=lambda item: str(item.get("username", "")))
    save_payload(path, payload)
    print(f"{action} {username} ({args.role}) in {path}")


def set_enabled(args: argparse.Namespace, enabled: bool) -> None:
    path = Path(args.file)
    payload = load_payload(path)
    username = args.username.strip().lower()
    for user in payload["users"]:
        if str(user.get("username", "")).strip().lower() == username:
            user["enabled"] = enabled
            save_payload(path, payload)
            print(f"{'Enabled' if enabled else 'Disabled'} {username}")
            return
    raise SystemExit(f"User not found: {username}")


def remove_user(args: argparse.Namespace) -> None:
    path = Path(args.file)
    payload = load_payload(path)
    username = args.username.strip().lower()
    before = len(payload["users"])
    payload["users"] = [
        user
        for user in payload["users"]
        if str(user.get("username", "")).strip().lower() != username
    ]
    if len(payload["users"]) == before:
        raise SystemExit(f"User not found: {username}")
    save_payload(path, payload)
    print(f"Removed {username}")


def list_users(args: argparse.Namespace) -> None:
    path = Path(args.file)
    payload = load_payload(path)
    if not payload["users"]:
        print("No dashboard users configured")
        return
    for user in payload["users"]:
        accounts = ",".join(user.get("account_ids") or []) or "all"
        print(
            f"{user.get('username')} role={user.get('role', 'account_operator')} "
            f"enabled={bool(user.get('enabled', True))} accounts={accounts}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage hashed Gate dashboard action users")
    parser.add_argument("--file", default=str(DEFAULT_PATH), help="Path to dashboard_users.json")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Add or replace a user")
    add.add_argument("--username", required=True)
    add.add_argument("--role", choices=("account_operator", "super_admin"), default="account_operator")
    add.add_argument("--account", action="append", default=[], help="Allowed Gate account ID; repeat as needed")
    add.set_defaults(func=add_or_update)

    for name, enabled in (("enable", True), ("disable", False)):
        command = sub.add_parser(name)
        command.add_argument("--username", required=True)
        command.set_defaults(func=lambda args, value=enabled: set_enabled(args, value))

    remove = sub.add_parser("remove")
    remove.add_argument("--username", required=True)
    remove.set_defaults(func=remove_user)

    listing = sub.add_parser("list")
    listing.set_defaults(func=list_users)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
