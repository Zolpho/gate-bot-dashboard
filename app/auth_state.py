from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import SessionLocal, engine, session_scope, utcnow
from .models import (
    DashboardAuthChallenge,
    DashboardAuthSession,
)

AUTH_TOKEN_BYTES = 32
AUTH_ENCRYPTION_KEY_BYTES = 32

SESSION_AUTH_METHODS = {
    "password",
    "password_passkey",
    "password_recovery",
    "password_totp",
}

CHALLENGE_PURPOSES = {
    "login_mfa",
    "totp_enrollment",
    "passkey_registration",
    "passkey_authentication",
}


class AuthStateError(RuntimeError):
    """Raised when durable authentication state is invalid."""


class AuthEncryptionKeyError(AuthStateError):
    """Raised when the separate MFA encryption key is unusable."""


def _normalize_username(
    username: str,
) -> str:
    normalized = str(
        username or ""
    ).strip().lower()

    if not normalized:
        raise AuthStateError(
            "username cannot be empty"
        )

    if len(normalized) > 64:
        raise AuthStateError(
            "username is too long"
        )

    return normalized


def _normalize_purpose(
    purpose: str,
) -> str:
    normalized = str(
        purpose or ""
    ).strip().lower()

    if normalized not in CHALLENGE_PURPOSES:
        raise AuthStateError(
            "Unsupported authentication challenge purpose"
        )

    return normalized


def _normalize_auth_method(
    auth_method: str,
) -> str:
    normalized = str(
        auth_method or ""
    ).strip().lower()

    if normalized not in SESSION_AUTH_METHODS:
        raise AuthStateError(
            "Unsupported session authentication method"
        )

    return normalized


def _as_utc(
    value: datetime,
) -> datetime:
    if value.tzinfo is None:
        return value.replace(
            tzinfo=UTC
        )

    return value.astimezone(
        UTC
    )


def _now(
    value: datetime | None,
) -> datetime:
    return _as_utc(
        value
        if value is not None
        else utcnow()
    )


def new_opaque_token() -> str:
    """
    Return a high-entropy token suitable for sending to a client.

    The returned raw value must never be persisted.
    """

    return secrets.token_urlsafe(
        AUTH_TOKEN_BYTES
    )


def hash_opaque_token(
    token: str,
) -> str:
    normalized = str(
        token or ""
    )

    if not normalized:
        raise AuthStateError(
            "opaque token cannot be empty"
        )

    return hashlib.sha256(
        normalized.encode(
            "utf-8"
        )
    ).hexdigest()


def credential_fingerprint(
    *,
    username: str,
    password_hash: str,
) -> str:
    """
    Bind a future session to the current file-backed password record.

    No password or password hash is stored in the session table.
    Changing the password changes this fingerprint and can therefore
    invalidate all sessions created against the previous credential.
    """

    normalized_username = (
        _normalize_username(
            username
        )
    )

    normalized_hash = str(
        password_hash or ""
    ).strip()

    if not normalized_hash:
        raise AuthStateError(
            "password hash cannot be empty"
        )

    payload = (
        normalized_username
        + "\0"
        + normalized_hash
    ).encode(
        "utf-8"
    )

    return hashlib.sha256(
        payload
    ).hexdigest()


def generate_auth_encryption_key() -> str:
    """
    Generate a printable 256-bit key for future authenticated encryption.

    This function only generates key material. R2B2 deliberately does not
    implement custom encryption or persist the key.
    """

    raw = secrets.token_bytes(
        AUTH_ENCRYPTION_KEY_BYTES
    )

    return (
        base64.urlsafe_b64encode(
            raw
        )
        .decode("ascii")
        .rstrip("=")
    )


def _decode_auth_encryption_key(
    encoded: str,
) -> bytes:
    value = str(
        encoded or ""
    ).strip()

    if not value:
        raise AuthEncryptionKeyError(
            "Authentication encryption key is empty"
        )

    try:
        raw = (
            base64.urlsafe_b64decode(
                value
                + "="
                * (
                    -len(value)
                    % 4
                )
            )
        )
    except (
        ValueError,
        binascii.Error,
    ) as exc:
        raise AuthEncryptionKeyError(
            "Authentication encryption key is not valid URL-safe base64"
        ) from exc

    if len(raw) != AUTH_ENCRYPTION_KEY_BYTES:
        raise AuthEncryptionKeyError(
            "Authentication encryption key must decode to exactly 32 bytes"
        )

    return raw


def load_auth_encryption_key(
    path: Path,
) -> bytes:
    try:
        value = path.read_text(
            encoding="ascii"
        )
    except FileNotFoundError as exc:
        raise AuthEncryptionKeyError(
            f"Authentication encryption key file not found: {path}"
        ) from exc
    except (
        OSError,
        UnicodeError,
    ) as exc:
        raise AuthEncryptionKeyError(
            f"Cannot read authentication encryption key file: {path}"
        ) from exc

    return _decode_auth_encryption_key(
        value
    )


def _safe_json(
    value: dict[str, Any] | None,
) -> str:
    return json.dumps(
        value or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _load_json(
    value: str,
) -> dict[str, Any]:
    try:
        decoded = json.loads(
            value
        )
    except (
        TypeError,
        json.JSONDecodeError,
    ):
        return {}

    return (
        decoded
        if isinstance(
            decoded,
            dict,
        )
        else {}
    )


def _session_snapshot(
    row: DashboardAuthSession,
) -> dict[str, Any]:
    return {
        "id":
            row.id,
        "username":
            row.username,
        "credential_fingerprint":
            row.credential_fingerprint,
        "auth_method":
            row.auth_method,
        "mfa_completed":
            row.mfa_completed,
        "created_at":
            (
                row.created_at.isoformat()
                if row.created_at
                else None
            ),
        "expires_at":
            (
                row.expires_at.isoformat()
                if row.expires_at
                else None
            ),
        "last_seen_at":
            (
                row.last_seen_at.isoformat()
                if row.last_seen_at
                else None
            ),
        "revoked_at":
            (
                row.revoked_at.isoformat()
                if row.revoked_at
                else None
            ),
    }


def _challenge_snapshot(
    row: DashboardAuthChallenge,
) -> dict[str, Any]:
    return {
        "id":
            row.id,
        "username":
            row.username,
        "purpose":
            row.purpose,
        "metadata":
            _load_json(
                row.metadata_json
            ),
        "created_at":
            (
                row.created_at.isoformat()
                if row.created_at
                else None
            ),
        "expires_at":
            (
                row.expires_at.isoformat()
                if row.expires_at
                else None
            ),
        "consumed_at":
            (
                row.consumed_at.isoformat()
                if row.consumed_at
                else None
            ),
    }


def create_auth_session(
    *,
    username: str,
    credential_hash: str,
    auth_method: str = "password",
    mfa_completed: bool = False,
    ttl_seconds: int = 3600,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    normalized_username = (
        _normalize_username(
            username
        )
    )

    normalized_auth_method = (
        _normalize_auth_method(
            auth_method
        )
    )

    ttl = int(
        ttl_seconds
    )

    if ttl < 300 or ttl > 86400:
        raise AuthStateError(
            "Session TTL must be between 300 and 86400 seconds"
        )

    fingerprint = str(
        credential_hash or ""
    ).strip()

    if (
        len(fingerprint) != 64
        or any(
            character
            not in "0123456789abcdef"
            for character
            in fingerprint.lower()
        )
    ):
        raise AuthStateError(
            "credential fingerprint must be a SHA-256 hex digest"
        )

    issued_at = _now(
        now
    )

    for _attempt in range(3):
        raw_token = (
            new_opaque_token()
        )

        token_hash = (
            hash_opaque_token(
                raw_token
            )
        )

        row = DashboardAuthSession(
            token_hash=token_hash,
            username=(
                normalized_username
            ),
            credential_fingerprint=(
                fingerprint.lower()
            ),
            auth_method=(
                normalized_auth_method
            ),
            mfa_completed=bool(
                mfa_completed
            ),
            created_at=issued_at,
            expires_at=(
                issued_at
                + timedelta(
                    seconds=ttl
                )
            ),
        )

        try:
            with session_scope() as db:
                db.add(row)
                db.flush()

                snapshot = (
                    _session_snapshot(
                        row
                    )
                )

            return (
                raw_token,
                snapshot,
            )

        except IntegrityError:
            continue

    raise AuthStateError(
        "Could not allocate a unique authentication session token"
    )


def get_auth_session(
    token: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    token_hash = (
        hash_opaque_token(
            token
        )
    )

    reference = _now(
        now
    )

    with session_scope() as db:
        row = db.scalar(
            select(
                DashboardAuthSession
            ).where(
                DashboardAuthSession
                .token_hash
                == token_hash
            )
        )

        if row is None:
            return None

        if row.revoked_at is not None:
            return None

        if (
            _as_utc(
                row.expires_at
            )
            <= reference
        ):
            return None

        return _session_snapshot(
            row
        )


def revoke_auth_session(
    token: str,
    *,
    now: datetime | None = None,
) -> bool:
    token_hash = (
        hash_opaque_token(
            token
        )
    )

    reference = _now(
        now
    )

    with session_scope() as db:
        row = db.scalar(
            select(
                DashboardAuthSession
            ).where(
                DashboardAuthSession
                .token_hash
                == token_hash
            )
        )

        if row is None:
            return False

        if row.revoked_at is None:
            row.revoked_at = (
                reference
            )

        return True


def create_auth_challenge(
    *,
    username: str,
    purpose: str,
    ttl_seconds: int = 300,
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    normalized_username = (
        _normalize_username(
            username
        )
    )

    normalized_purpose = (
        _normalize_purpose(
            purpose
        )
    )

    ttl = int(
        ttl_seconds
    )

    if ttl < 60 or ttl > 900:
        raise AuthStateError(
            "Challenge TTL must be between 60 and 900 seconds"
        )

    issued_at = _now(
        now
    )

    for _attempt in range(3):
        raw_token = (
            new_opaque_token()
        )

        token_hash = (
            hash_opaque_token(
                raw_token
            )
        )

        row = DashboardAuthChallenge(
            token_hash=token_hash,
            username=(
                normalized_username
            ),
            purpose=(
                normalized_purpose
            ),
            metadata_json=(
                _safe_json(
                    metadata
                )
            ),
            created_at=issued_at,
            expires_at=(
                issued_at
                + timedelta(
                    seconds=ttl
                )
            ),
        )

        try:
            with session_scope() as db:
                db.add(row)
                db.flush()

                snapshot = (
                    _challenge_snapshot(
                        row
                    )
                )

            return (
                raw_token,
                snapshot,
            )

        except IntegrityError:
            continue

    raise AuthStateError(
        "Could not allocate a unique authentication challenge token"
    )


def get_auth_challenge(
    token: str,
    *,
    purpose: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """
    Read an active challenge without consuming it.

    Successful MFA verification must still call
    consume_auth_challenge() before issuing a session.
    """

    normalized_purpose = (
        _normalize_purpose(
            purpose
        )
    )

    token_hash = (
        hash_opaque_token(
            token
        )
    )

    reference = _now(
        now
    )

    with session_scope() as db:
        row = db.scalar(
            select(
                DashboardAuthChallenge
            ).where(
                DashboardAuthChallenge
                .token_hash
                == token_hash
            )
        )

        if row is None:
            return None

        if (
            row.purpose
            != normalized_purpose
        ):
            return None

        if (
            row.consumed_at
            is not None
        ):
            return None

        if (
            _as_utc(
                row.expires_at
            )
            <= reference
        ):
            return None

        return _challenge_snapshot(
            row
        )


def consume_auth_challenge(
    token: str,
    *,
    purpose: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    token_hash = (
        hash_opaque_token(
            token
        )
    )

    normalized_purpose = (
        _normalize_purpose(
            purpose
        )
    )

    reference = _now(
        now
    )

    db = SessionLocal()

    try:
        # Serialize read + consume under SQLite so two concurrent
        # requests cannot both successfully consume one challenge.
        if engine.dialect.name == "sqlite":
            db.execute(
                text(
                    "BEGIN IMMEDIATE"
                )
            )

        row = db.scalar(
            select(
                DashboardAuthChallenge
            ).where(
                DashboardAuthChallenge
                .token_hash
                == token_hash
            )
        )

        if (
            row is None
            or row.purpose
            != normalized_purpose
            or row.consumed_at
            is not None
            or _as_utc(
                row.expires_at
            )
            <= reference
        ):
            db.rollback()
            return None

        row.consumed_at = (
            reference
        )

        db.flush()

        snapshot = (
            _challenge_snapshot(
                row
            )
        )

        db.commit()

        return snapshot

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

def get_auth_challenge_in_session(
    db: Session,
    token: str,
    *,
    purpose: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """
    Read an active authentication challenge using a caller-owned
    transaction.

    This helper never commits or rolls back the supplied session.
    """

    token_hash = hash_opaque_token(
        token
    )

    normalized_purpose = (
        _normalize_purpose(
            purpose
        )
    )

    reference = _now(
        now
    )

    row = db.scalar(
        select(
            DashboardAuthChallenge
        ).where(
            DashboardAuthChallenge
            .token_hash
            == token_hash
        )
    )

    if (
        row is None
        or row.purpose
        != normalized_purpose
        or row.consumed_at
        is not None
        or _as_utc(
            row.expires_at
        )
        <= reference
    ):
        return None

    return _challenge_snapshot(
        row
    )


def consume_auth_challenge_in_session(
    db: Session,
    token: str,
    *,
    purpose: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """
    Consume an active challenge inside a caller-owned transaction.

    The caller owns serialization, commit and rollback.
    """

    token_hash = hash_opaque_token(
        token
    )

    normalized_purpose = (
        _normalize_purpose(
            purpose
        )
    )

    reference = _now(
        now
    )

    row = db.scalar(
        select(
            DashboardAuthChallenge
        ).where(
            DashboardAuthChallenge
            .token_hash
            == token_hash
        )
    )

    if (
        row is None
        or row.purpose
        != normalized_purpose
        or row.consumed_at
        is not None
        or _as_utc(
            row.expires_at
        )
        <= reference
    ):
        return None

    row.consumed_at = (
        reference
    )

    db.flush()

    return _challenge_snapshot(
        row
    )


def create_auth_session_in_session(
    db: Session,
    *,
    username: str,
    credential_hash: str,
    auth_method: str = "password",
    mfa_completed: bool = False,
    ttl_seconds: int = 3600,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Create an authentication session inside a caller-owned
    transaction.

    A persistence failure is intentionally allowed to propagate so
    the caller can roll back factor consumption, challenge
    consumption and session creation together.
    """

    normalized_username = (
        _normalize_username(
            username
        )
    )

    normalized_auth_method = (
        _normalize_auth_method(
            auth_method
        )
    )

    ttl = int(
        ttl_seconds
    )

    if ttl < 300 or ttl > 86400:
        raise AuthStateError(
            "Session TTL must be between "
            "300 and 86400 seconds"
        )

    fingerprint = str(
        credential_hash or ""
    ).strip()

    if (
        len(fingerprint) != 64
        or any(
            character
            not in "0123456789abcdef"
            for character
            in fingerprint.lower()
        )
    ):
        raise AuthStateError(
            "credential fingerprint must be "
            "a SHA-256 hex digest"
        )

    issued_at = _now(
        now
    )

    raw_token = (
        new_opaque_token()
    )

    row = DashboardAuthSession(
        token_hash=(
            hash_opaque_token(
                raw_token
            )
        ),
        username=(
            normalized_username
        ),
        credential_fingerprint=(
            fingerprint.lower()
        ),
        auth_method=(
            normalized_auth_method
        ),
        mfa_completed=bool(
            mfa_completed
        ),
        created_at=issued_at,
        expires_at=(
            issued_at
            + timedelta(
                seconds=ttl
            )
        ),
    )

    db.add(
        row
    )

    db.flush()

    return (
        raw_token,
        _session_snapshot(
            row
        ),
    )
