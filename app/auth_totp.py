from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.orm import Session

from .auth_state import load_auth_encryption_key
from .config import Settings
from .db import SessionLocal, engine, session_scope, utcnow
from .models import DashboardAuthFactor

TOTP_DIGITS = 6
TOTP_INTERVAL_SECONDS = 30
TOTP_SECRET_LENGTH = 32
TOTP_VALID_WINDOW = 1


class TotpError(RuntimeError):
    """Base error for dashboard TOTP state."""


class TotpEnrollmentError(TotpError):
    """Raised when TOTP enrollment state is invalid."""


class TotpSecretError(TotpError):
    """Raised when encrypted TOTP material cannot be used."""


def _normalize_username(
    username: str,
) -> str:
    normalized = str(
        username or ""
    ).strip().lower()

    if not normalized:
        raise TotpError(
            "username cannot be empty"
        )

    if len(normalized) > 64:
        raise TotpError(
            "username is too long"
        )

    return normalized


def _normalize_time(
    value: datetime | None,
) -> datetime:
    current = (
        value
        if value is not None
        else utcnow()
    )

    if current.tzinfo is None:
        return current.replace(
            tzinfo=UTC
        )

    return current.astimezone(
        UTC
    )


def _totp(
    secret: str,
) -> pyotp.TOTP:
    return pyotp.TOTP(
        secret,
        digits=TOTP_DIGITS,
        interval=(
            TOTP_INTERVAL_SECONDS
        ),
        digest=hashlib.sha1,
    )


def _normalized_secret(
    secret: str,
) -> str:
    normalized = (
        str(
            secret or ""
        )
        .replace(" ", "")
        .strip()
        .upper()
    )

    if not normalized:
        raise TotpSecretError(
            "TOTP secret cannot be empty"
        )

    try:
        _totp(
            normalized
        ).at(0)
    except Exception as exc:
        raise TotpSecretError(
            "TOTP secret is invalid"
        ) from exc

    return normalized


def _fernet(
    settings: Settings,
) -> Fernet:
    raw_key = (
        load_auth_encryption_key(
            settings
            .dashboard_auth_encryption_key_file
        )
    )

    encoded_key = (
        base64.urlsafe_b64encode(
            raw_key
        )
    )

    return Fernet(
        encoded_key
    )


def generate_totp_secret() -> str:
    return pyotp.random_base32(
        length=TOTP_SECRET_LENGTH
    )


def provisioning_uri(
    *,
    username: str,
    secret: str,
    issuer: str,
) -> str:
    normalized_username = (
        _normalize_username(
            username
        )
    )

    normalized_secret = (
        _normalized_secret(
            secret
        )
    )

    normalized_issuer = str(
        issuer or ""
    ).strip()

    if not normalized_issuer:
        raise TotpEnrollmentError(
            "TOTP issuer cannot be empty"
        )

    return _totp(
        normalized_secret
    ).provisioning_uri(
        name=normalized_username,
        issuer_name=(
            normalized_issuer
        ),
    )


def encrypt_totp_secret(
    secret: str,
    *,
    settings: Settings,
) -> str:
    normalized = (
        _normalized_secret(
            secret
        )
    )

    token = _fernet(
        settings
    ).encrypt(
        normalized.encode(
            "ascii"
        )
    )

    return token.decode(
        "ascii"
    )


def decrypt_totp_secret(
    ciphertext: str,
    *,
    settings: Settings,
) -> str:
    value = str(
        ciphertext or ""
    ).strip()

    if not value:
        raise TotpSecretError(
            "Encrypted TOTP secret is empty"
        )

    try:
        plaintext = (
            _fernet(
                settings
            )
            .decrypt(
                value.encode(
                    "ascii"
                )
            )
            .decode(
                "ascii"
            )
        )
    except (
        InvalidToken,
        UnicodeError,
        ValueError,
    ) as exc:
        raise TotpSecretError(
            "Encrypted TOTP secret cannot be decrypted"
        ) from exc

    return _normalized_secret(
        plaintext
    )


def matching_totp_counter(
    secret: str,
    code: str,
    *,
    at: datetime | None = None,
    valid_window: int = TOTP_VALID_WINDOW,
) -> int | None:
    normalized_secret = (
        _normalized_secret(
            secret
        )
    )

    normalized_code = str(
        code or ""
    ).strip()

    if (
        len(normalized_code)
        != TOTP_DIGITS
        or not normalized_code.isdigit()
    ):
        return None

    window = int(
        valid_window
    )

    if window < 0 or window > 2:
        raise TotpError(
            "TOTP valid window must be between 0 and 2"
        )

    reference = _normalize_time(
        at
    )

    generator = _totp(
        normalized_secret
    )

    base_counter = int(
        generator.timecode(
            reference
        )
    )

    # Prefer the exact current counter, then adjacent clock-skew
    # counters. This keeps behavior deterministic if a caller
    # accidentally supplies a duplicated code across a boundary.
    offsets = [0]

    for distance in range(
        1,
        window + 1,
    ):
        offsets.extend(
            (
                -distance,
                distance,
            )
        )

    for offset in offsets:
        candidate = (
            generator.at(
                reference,
                counter_offset=offset,
            )
        )

        if hmac.compare_digest(
            candidate,
            normalized_code,
        ):
            return (
                base_counter
                + offset
            )

    return None


def _factor_snapshot(
    row: DashboardAuthFactor,
) -> dict[str, Any]:
    return {
        "username":
            row.username,
        "totp_enabled":
            row.totp_enabled,
        "totp_confirmed_at":
            (
                row
                .totp_confirmed_at
                .isoformat()
                if row
                .totp_confirmed_at
                else None
            ),
        "totp_last_used_counter":
            row
            .totp_last_used_counter,
        "has_totp_secret":
            bool(
                row
                .totp_secret_ciphertext
            ),
    }


def totp_status(
    username: str,
) -> dict[str, Any]:
    normalized = (
        _normalize_username(
            username
        )
    )

    with session_scope() as db:
        row = db.get(
            DashboardAuthFactor,
            normalized,
        )

        if row is None:
            return {
                "username":
                    normalized,
                "totp_enabled":
                    False,
                "totp_confirmed_at":
                    None,
                "totp_last_used_counter":
                    None,
                "has_totp_secret":
                    False,
            }

        return _factor_snapshot(
            row
        )


def begin_totp_enrollment(
    *,
    username: str,
    settings: Settings,
) -> dict[str, Any]:
    normalized = (
        _normalize_username(
            username
        )
    )

    secret = (
        generate_totp_secret()
    )

    ciphertext = (
        encrypt_totp_secret(
            secret,
            settings=settings,
        )
    )

    uri = provisioning_uri(
        username=normalized,
        secret=secret,
        issuer=settings.app_name,
    )

    with session_scope() as db:
        row = db.get(
            DashboardAuthFactor,
            normalized,
        )

        if (
            row is not None
            and row.totp_enabled
        ):
            raise TotpEnrollmentError(
                "TOTP is already enabled for this user"
            )

        if row is None:
            row = DashboardAuthFactor(
                username=normalized,
            )

            db.add(
                row
            )

        row.totp_secret_ciphertext = (
            ciphertext
        )

        row.totp_enabled = False
        row.totp_confirmed_at = None
        row.totp_last_used_counter = None

        db.flush()

        factor = (
            _factor_snapshot(
                row
            )
        )

    return {
        "username":
            normalized,
        "secret":
            secret,
        "provisioning_uri":
            uri,
        "factor":
            factor,
    }


def confirm_totp_enrollment(
    *,
    username: str,
    code: str,
    settings: Settings,
    now: datetime | None = None,
) -> bool:
    normalized = (
        _normalize_username(
            username
        )
    )

    reference = (
        _normalize_time(
            now
        )
    )

    db = SessionLocal()

    try:
        if engine.dialect.name == "sqlite":
            db.execute(
                text(
                    "BEGIN IMMEDIATE"
                )
            )

        row = db.get(
            DashboardAuthFactor,
            normalized,
        )

        if row is None:
            db.rollback()
            raise TotpEnrollmentError(
                "No TOTP enrollment exists for this user"
            )

        if row.totp_enabled:
            db.rollback()
            raise TotpEnrollmentError(
                "TOTP is already enabled for this user"
            )

        if not (
            row
            .totp_secret_ciphertext
        ):
            db.rollback()
            raise TotpEnrollmentError(
                "TOTP enrollment has no encrypted secret"
            )

        secret = decrypt_totp_secret(
            row.totp_secret_ciphertext,
            settings=settings,
        )

        counter = (
            matching_totp_counter(
                secret,
                code,
                at=reference,
            )
        )

        if counter is None:
            db.rollback()
            return False

        row.totp_enabled = True
        row.totp_confirmed_at = (
            reference
        )
        row.totp_last_used_counter = (
            counter
        )

        db.commit()

        return True

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def verify_totp_for_user(
    *,
    username: str,
    code: str,
    settings: Settings,
    now: datetime | None = None,
) -> bool:
    normalized = (
        _normalize_username(
            username
        )
    )

    reference = (
        _normalize_time(
            now
        )
    )

    db = SessionLocal()

    try:
        # Serialize verify + last-counter update so the same
        # valid TOTP cannot win twice under concurrent requests.
        if engine.dialect.name == "sqlite":
            db.execute(
                text(
                    "BEGIN IMMEDIATE"
                )
            )

        row = db.get(
            DashboardAuthFactor,
            normalized,
        )

        if (
            row is None
            or not row.totp_enabled
            or not row
            .totp_secret_ciphertext
        ):
            db.rollback()
            return False

        secret = decrypt_totp_secret(
            row.totp_secret_ciphertext,
            settings=settings,
        )

        counter = (
            matching_totp_counter(
                secret,
                code,
                at=reference,
            )
        )

        if counter is None:
            db.rollback()
            return False

        previous = (
            row
            .totp_last_used_counter
        )

        if (
            previous is not None
            and counter <= previous
        ):
            db.rollback()
            return False

        row.totp_last_used_counter = (
            counter
        )

        db.commit()

        return True

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

def verify_totp_for_user_in_session(
    db: Session,
    *,
    username: str,
    code: str,
    settings: Settings,
    now: datetime | None = None,
) -> bool:
    """
    Verify and reserve a TOTP counter in a caller-owned transaction.

    The caller owns BEGIN/commit/rollback. A successful counter
    update is therefore committed only with the surrounding
    authentication transaction.
    """

    normalized = (
        _normalize_username(
            username
        )
    )

    reference = (
        _normalize_time(
            now
        )
    )

    row = db.get(
        DashboardAuthFactor,
        normalized,
    )

    if (
        row is None
        or not row.totp_enabled
        or not row
        .totp_secret_ciphertext
    ):
        return False

    secret = decrypt_totp_secret(
        row.totp_secret_ciphertext,
        settings=settings,
    )

    counter = (
        matching_totp_counter(
            secret,
            code,
            at=reference,
        )
    )

    if counter is None:
        return False

    previous = (
        row.totp_last_used_counter
    )

    if (
        previous is not None
        and counter <= previous
    ):
        return False

    row.totp_last_used_counter = (
        counter
    )

    db.flush()

    return True
