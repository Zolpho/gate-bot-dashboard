from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .config import Settings, get_settings

PASSWORD_SCHEME = "pbkdf2_sha256"
DEFAULT_PBKDF2_ITERATIONS = 600_000
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_ROLE_VALUES = {"account_operator", "super_admin"}
_basic = HTTPBasic(auto_error=False)


class UserConfigError(RuntimeError):
    """Raised when dashboard user configuration is invalid."""


@dataclass(frozen=True, slots=True)
class DashboardUser:
    username: str
    role: Literal["account_operator", "super_admin"]
    account_ids: tuple[str, ...]
    enabled: bool = True
    password_hash: str = ""
    auth_source: str = "file"

    @property
    def is_super_admin(self) -> bool:
        return self.role == "super_admin"

    def can_manage(self, account_id: str) -> bool:
        normalized = account_id.strip().lower()
        return self.is_super_admin or normalized in self.account_ids

    def safe_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "role": self.role,
            "account_ids": list(self.account_ids),
            "enabled": self.enabled,
            "auth_source": self.auth_source,
        }


def _encode_b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_b64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, *, iterations: int = DEFAULT_PBKDF2_ITERATIONS) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PASSWORD_SCHEME}${iterations}${_encode_b64(salt)}${_encode_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations_text, salt_text, expected_text = encoded.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        iterations = int(iterations_text)
        if iterations < 100_000 or iterations > 5_000_000:
            return False
        salt = _decode_b64(salt_text)
        expected = _decode_b64(expected_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, binascii.Error):
        return False


def _normalize_account_ids(raw: Any, *, username: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise UserConfigError(f"User '{username}' account_ids must be an array")
    normalized: list[str] = []
    for value in raw:
        account_id = str(value).strip().lower()
        if not account_id:
            continue
        if account_id not in normalized:
            normalized.append(account_id)
    return tuple(normalized)


def _load_file_users(path: Path) -> tuple[DashboardUser, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise UserConfigError(f"Cannot read dashboard users file {path}: {exc}") from exc

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UserConfigError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("users"), list):
        raise UserConfigError(f"{path} must contain an object with a 'users' array")

    users: list[DashboardUser] = []
    seen: set[str] = set()
    for index, raw in enumerate(payload["users"], start=1):
        if not isinstance(raw, dict):
            raise UserConfigError(f"User entry {index} must be a JSON object")
        username = str(raw.get("username", "")).strip().lower()
        if not _USERNAME_RE.fullmatch(username):
            raise UserConfigError(
                f"Invalid username at entry {index}: use 1-64 lowercase letters, numbers, '.', '_' or '-'"
            )
        if username in seen:
            raise UserConfigError(f"Duplicate dashboard username: {username}")
        seen.add(username)

        role = str(raw.get("role") or "account_operator").strip().lower()
        if role not in _ROLE_VALUES:
            raise UserConfigError(f"Invalid role for user '{username}': {role}")

        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise UserConfigError(f"User '{username}' enabled must be true or false")

        password_hash = str(raw.get("password_hash", "")).strip()
        if enabled and not password_hash:
            raise UserConfigError(f"Enabled user '{username}' is missing password_hash")

        account_ids = _normalize_account_ids(raw.get("account_ids"), username=username)
        if role == "account_operator" and enabled and not account_ids:
            raise UserConfigError(f"Account operator '{username}' must have at least one account_id")

        users.append(
            DashboardUser(
                username=username,
                role=role,  # type: ignore[arg-type]
                account_ids=account_ids,
                enabled=enabled,
                password_hash=password_hash,
            )
        )
    return tuple(users)


def load_dashboard_users(settings: Settings | None = None) -> tuple[DashboardUser, ...]:
    settings = settings or get_settings()
    return _load_file_users(settings.dashboard_users_file)


def safe_user_config(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    users = load_dashboard_users(settings)
    enabled_users = [user for user in users if user.enabled]
    return {
        "configured": bool(enabled_users or settings.legacy_admin_enabled),
        "user_count": len(users),
        "enabled_user_count": len(enabled_users),
        "legacy_super_admin_enabled": settings.legacy_admin_enabled,
    }


def _authentication_error(detail: str = "Authentication required") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": 'Basic realm="Gate Bot Dashboard Actions"'},
    )


def authenticate_credentials(
    credentials: HTTPBasicCredentials | None,
    settings: Settings | None = None,
) -> DashboardUser:
    settings = settings or get_settings()
    if credentials is None:
        raise _authentication_error()

    username = credentials.username.strip().lower()
    password = credentials.password

    # Backward-compatible optional super-admin credentials from .env. Public GET
    # routes do not use them; they only authorize protected actions.
    if settings.legacy_admin_enabled:
        legacy_valid = hmac.compare_digest(username, settings.dashboard_username.strip().lower()) and hmac.compare_digest(
            password, settings.dashboard_password
        )
        if legacy_valid:
            return DashboardUser(
                username=username,
                role="super_admin",
                account_ids=(),
                enabled=True,
                auth_source="legacy_env",
            )

    try:
        users = load_dashboard_users(settings)
    except UserConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    user = next((item for item in users if item.username == username and item.enabled), None)
    if user is None or not verify_password(password, user.password_hash):
        raise _authentication_error("Invalid username or password")
    return user


def require_user(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DashboardUser:
    return authenticate_credentials(credentials, settings)


def require_super_admin(user: Annotated[DashboardUser, Depends(require_user)]) -> DashboardUser:
    if not user.is_super_admin:
        raise HTTPException(status_code=403, detail="Super-admin permission is required")
    return user


def require_account_access(user: DashboardUser, account_id: str) -> str:
    normalized = account_id.strip().lower()
    if not user.can_manage(normalized):
        raise HTTPException(status_code=403, detail="You are not allowed to manage this Gate account")
    return normalized


def resolve_authorized_account(user: DashboardUser, requested_account_id: str | None) -> str | None:
    if requested_account_id:
        return require_account_access(user, requested_account_id)
    if user.is_super_admin:
        return None
    if len(user.account_ids) == 1:
        return user.account_ids[0]
    raise HTTPException(status_code=400, detail="account_id is required for this user")
