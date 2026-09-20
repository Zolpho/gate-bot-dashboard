from __future__ import annotations

import base64
import json
import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .config import Settings
from .db import SessionLocal, engine, session_scope, utcnow
from .models import DashboardAuthPasskeyCredential, DashboardAuthPasskeyUser

PASSKEY_USER_HANDLE_BYTES = 32


class PasskeyError(RuntimeError):
    """Base error for dashboard WebAuthn operations."""


class PasskeyConfigurationError(PasskeyError):
    """Raised when WebAuthn is not explicitly configured and enabled."""


class PasskeyStateError(PasskeyError):
    """Raised when durable passkey state does not permit an operation."""


class PasskeyVerificationError(PasskeyError):
    """Raised when a WebAuthn ceremony cannot be verified."""


def _normalize_username(value: str) -> str:
    normalized = str(value or "").strip().lower()

    if not normalized:
        raise PasskeyStateError(
            "username cannot be empty"
        )

    if len(normalized) > 64:
        raise PasskeyStateError(
            "username is too long"
        )

    return normalized


def _normalize_label(value: str) -> str:
    normalized = (
        str(value or "").strip()
        or "Passkey"
    )

    if len(normalized) > 128:
        raise PasskeyStateError(
            "passkey label is too long"
        )

    return normalized


def _challenge_bytes(
    value: bytes | bytearray | memoryview,
) -> bytes:
    try:
        challenge = bytes(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise PasskeyStateError(
            "WebAuthn challenge is invalid"
        ) from exc

    if len(challenge) < 16:
        raise PasskeyStateError(
            "WebAuthn challenge is too short"
        )

    return challenge


def _webauthn_config(
    settings: Settings,
) -> tuple[str, str, str]:
    if not (
        settings
        .dashboard_webauthn_enabled
    ):
        raise PasskeyConfigurationError(
            "WebAuthn is disabled"
        )

    rp_id = str(
        settings
        .dashboard_webauthn_rp_id
        or ""
    ).strip()

    origin = str(
        settings
        .dashboard_webauthn_origin
        or ""
    ).strip()

    rp_name = str(
        settings
        .dashboard_webauthn_rp_name
        or ""
    ).strip()

    if not rp_id:
        raise PasskeyConfigurationError(
            "WebAuthn RP ID is not configured"
        )

    if not origin:
        raise PasskeyConfigurationError(
            "WebAuthn origin is not configured"
        )

    if not rp_name:
        raise PasskeyConfigurationError(
            "WebAuthn RP name is not configured"
        )

    return (
        rp_id,
        origin,
        rp_name,
    )


def _b64url_encode(
    value: bytes,
) -> str:
    return (
        base64
        .urlsafe_b64encode(
            value
        )
        .decode(
            "ascii"
        )
        .rstrip(
            "="
        )
    )


def _b64url_decode(
    value: str,
) -> bytes:
    normalized = str(
        value or ""
    ).strip()

    if not normalized:
        raise PasskeyVerificationError(
            "Passkey credential ID is missing"
        )

    padding = (
        "="
        * (
            -len(
                normalized
            )
            % 4
        )
    )

    try:
        return (
            base64
            .urlsafe_b64decode(
                (
                    normalized
                    + padding
                ).encode(
                    "ascii"
                )
            )
        )

    except Exception as exc:
        raise PasskeyVerificationError(
            "Passkey credential ID is invalid"
        ) from exc


def _enum_text(
    value: Any,
) -> str:
    return str(
        getattr(
            value,
            "value",
            value,
        )
        or ""
    )


def _transports_from_json(
    value: str,
) -> list[str]:
    try:
        parsed = json.loads(
            str(
                value
                or "[]"
            )
        )

    except json.JSONDecodeError:
        return []

    if not isinstance(
        parsed,
        list,
    ):
        return []

    result: list[str] = []

    for item in parsed:
        normalized = str(
            item or ""
        ).strip().lower()

        if (
            normalized
            and normalized
            not in result
        ):
            result.append(
                normalized
            )

    return result


def _transports_from_credential(
    credential: Any,
) -> list[str]:
    payload = credential

    if isinstance(
        payload,
        str,
    ):
        try:
            payload = json.loads(
                payload
            )

        except json.JSONDecodeError:
            return []

    if not isinstance(
        payload,
        dict,
    ):
        return []

    response = payload.get(
        "response"
    )

    if (
        not isinstance(
            response,
            dict,
        )
        or not isinstance(
            response.get(
                "transports"
            ),
            list,
        )
    ):
        return []

    result: list[str] = []

    for item in response[
        "transports"
    ]:
        normalized = str(
            item or ""
        ).strip().lower()

        if (
            normalized
            and normalized
            not in result
        ):
            result.append(
                normalized
            )

    return result


def _descriptor(
    row: DashboardAuthPasskeyCredential,
) -> PublicKeyCredentialDescriptor:
    transports: list[
        AuthenticatorTransport
    ] = []

    for value in (
        _transports_from_json(
            row.transports_json
        )
    ):
        try:
            transports.append(
                AuthenticatorTransport(
                    value
                )
            )

        except ValueError:
            continue

    return PublicKeyCredentialDescriptor(
        id=bytes(
            row.credential_id
        ),
        transports=(
            transports
            or None
        ),
    )


def _credential_id_from_payload(
    credential: Any,
) -> bytes:
    raw_id = getattr(
        credential,
        "raw_id",
        None,
    )

    if raw_id is not None:
        return bytes(
            raw_id
        )

    payload = credential

    if isinstance(
        payload,
        str,
    ):
        try:
            payload = json.loads(
                payload
            )

        except json.JSONDecodeError as exc:
            raise PasskeyVerificationError(
                "Passkey response is invalid JSON"
            ) from exc

    if not isinstance(
        payload,
        dict,
    ):
        raise PasskeyVerificationError(
            "Passkey response is invalid"
        )

    encoded = payload.get(
        "rawId",
        payload.get(
            "id",
            "",
        ),
    )

    return _b64url_decode(
        str(
            encoded
            or ""
        )
    )


def _credential_snapshot(
    row: DashboardAuthPasskeyCredential,
) -> dict[str, Any]:
    return {
        "credential_id":
            _b64url_encode(
                bytes(
                    row.credential_id
                )
            ),
        "username":
            row.username,
        "label":
            row.label,
        "sign_count":
            int(
                row.sign_count
            ),
        "transports":
            _transports_from_json(
                row.transports_json
            ),
        "credential_device_type":
            row.credential_device_type,
        "credential_backed_up":
            bool(
                row
                .credential_backed_up
            ),
        "created_at":
            row.created_at,
        "last_used_at":
            row.last_used_at,
        "revoked_at":
            row.revoked_at,
    }


def _begin_serialized_write(
    db: Session,
) -> None:
    if (
        engine
        .dialect
        .name
        == "sqlite"
    ):
        db.execute(
            text(
                "BEGIN IMMEDIATE"
            )
        )


def ensure_passkey_user(
    username: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized = (
        _normalize_username(
            username
        )
    )

    reference = (
        now
        or utcnow()
    )

    db = SessionLocal()

    try:
        _begin_serialized_write(
            db
        )

        row = db.get(
            DashboardAuthPasskeyUser,
            normalized,
        )

        if row is None:
            row = (
                DashboardAuthPasskeyUser(
                    username=normalized,
                    user_handle=(
                        secrets
                        .token_bytes(
                            PASSKEY_USER_HANDLE_BYTES
                        )
                    ),
                    enabled=False,
                    created_at=reference,
                    updated_at=reference,
                )
            )

            db.add(
                row
            )

            db.flush()

        result = {
            "username":
                row.username,
            "user_handle":
                bytes(
                    row.user_handle
                ),
            "enabled":
                bool(
                    row.enabled
                ),
        }

        db.commit()

        return result

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def passkey_status(
    username: str,
) -> dict[str, Any]:
    normalized = (
        _normalize_username(
            username
        )
    )

    with session_scope() as db:
        user = db.get(
            DashboardAuthPasskeyUser,
            normalized,
        )

        credentials = list(
            db.scalars(
                select(
                    DashboardAuthPasskeyCredential
                )
                .where(
                    DashboardAuthPasskeyCredential
                    .username
                    == normalized,
                    DashboardAuthPasskeyCredential
                    .revoked_at
                    .is_(
                        None
                    ),
                )
                .order_by(
                    DashboardAuthPasskeyCredential
                    .id
                )
            )
        )

        enabled = bool(
            user is not None
            and user.enabled
        )

        return {
            "username":
                normalized,
            "enabled":
                enabled,
            "available":
                bool(
                    enabled
                    and credentials
                ),
            "credential_count":
                len(
                    credentials
                ),
            "credentials": [
                _credential_snapshot(
                    row
                )
                for row
                in credentials
            ],
        }


def set_passkey_enabled(
    username: str,
    enabled: bool,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized = (
        _normalize_username(
            username
        )
    )

    target = bool(
        enabled
    )

    db = SessionLocal()

    try:
        _begin_serialized_write(
            db
        )

        user = db.get(
            DashboardAuthPasskeyUser,
            normalized,
        )

        if user is None:
            if target:
                raise PasskeyStateError(
                    "No passkey is registered"
                )

            db.rollback()

            return (
                passkey_status(
                    normalized
                )
            )

        active_count = int(
            db.scalar(
                select(
                    func.count()
                )
                .select_from(
                    DashboardAuthPasskeyCredential
                )
                .where(
                    DashboardAuthPasskeyCredential
                    .username
                    == normalized,
                    DashboardAuthPasskeyCredential
                    .revoked_at
                    .is_(
                        None
                    ),
                )
            )
            or 0
        )

        if (
            target
            and active_count < 1
        ):
            raise PasskeyStateError(
                "No active passkey credential "
                "is registered"
            )

        user.enabled = (
            target
        )

        user.updated_at = (
            now
            or utcnow()
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

    return passkey_status(
        normalized
    )


def revoke_passkey_credential(
    username: str,
    credential_id: str,
    *,
    now: datetime | None = None,
) -> bool:
    normalized = (
        _normalize_username(
            username
        )
    )

    raw_credential_id = (
        _b64url_decode(
            credential_id
        )
    )

    reference = (
        now
        or utcnow()
    )

    db = SessionLocal()

    try:
        _begin_serialized_write(
            db
        )

        row = db.scalar(
            select(
                DashboardAuthPasskeyCredential
            ).where(
                DashboardAuthPasskeyCredential
                .username
                == normalized,
                DashboardAuthPasskeyCredential
                .credential_id
                == raw_credential_id,
                DashboardAuthPasskeyCredential
                .revoked_at
                .is_(
                    None
                ),
            )
        )

        if row is None:
            db.rollback()
            return False

        row.revoked_at = (
            reference
        )

        remaining = int(
            db.scalar(
                select(
                    func.count()
                )
                .select_from(
                    DashboardAuthPasskeyCredential
                )
                .where(
                    DashboardAuthPasskeyCredential
                    .username
                    == normalized,
                    DashboardAuthPasskeyCredential
                    .revoked_at
                    .is_(
                        None
                    ),
                    DashboardAuthPasskeyCredential
                    .id
                    != row.id,
                )
            )
            or 0
        )

        if remaining == 0:
            user = db.get(
                DashboardAuthPasskeyUser,
                normalized,
            )

            if user is not None:
                user.enabled = False
                user.updated_at = (
                    reference
                )

        db.commit()

        return True

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def generate_passkey_registration_options(
    *,
    username: str,
    challenge: (
        bytes
        | bytearray
        | memoryview
    ),
    settings: Settings,
    display_name: str | None = None,
) -> dict[str, Any]:
    (
        rp_id,
        _origin,
        rp_name,
    ) = _webauthn_config(
        settings
    )

    normalized = (
        _normalize_username(
            username
        )
    )

    identity = (
        ensure_passkey_user(
            normalized
        )
    )

    with session_scope() as db:
        rows = list(
            db.scalars(
                select(
                    DashboardAuthPasskeyCredential
                ).where(
                    DashboardAuthPasskeyCredential
                    .username
                    == normalized,
                    DashboardAuthPasskeyCredential
                    .revoked_at
                    .is_(
                        None
                    ),
                )
            )
        )

    options = (
        generate_registration_options(
            rp_id=rp_id,
            rp_name=rp_name,
            user_id=(
                identity[
                    "user_handle"
                ]
            ),
            user_name=normalized,
            user_display_name=(
                str(
                    display_name
                    or ""
                ).strip()
                or normalized
            ),
            challenge=(
                _challenge_bytes(
                    challenge
                )
            ),
            exclude_credentials=(
                [
                    _descriptor(
                        row
                    )
                    for row
                    in rows
                ]
                or None
            ),
            authenticator_selection=(
                AuthenticatorSelectionCriteria(
                    resident_key=(
                        ResidentKeyRequirement
                        .REQUIRED
                    ),
                    require_resident_key=True,
                    user_verification=(
                        UserVerificationRequirement
                        .REQUIRED
                    ),
                )
            ),
            attestation=(
                AttestationConveyancePreference
                .NONE
            ),
        )
    )

    return json.loads(
        options_to_json(
            options
        )
    )


def verify_and_store_passkey_registration_in_session(
    db: Session,
    *,
    username: str,
    challenge: (
        bytes
        | bytearray
        | memoryview
    ),
    credential: Any,
    settings: Settings,
    label: str = "Passkey",
    now: datetime | None = None,
) -> dict[str, Any]:
    (
        rp_id,
        origin,
        _rp_name,
    ) = _webauthn_config(
        settings
    )

    normalized = (
        _normalize_username(
            username
        )
    )

    if (
        db.get(
            DashboardAuthPasskeyUser,
            normalized,
        )
        is None
    ):
        raise PasskeyStateError(
            "Passkey registration "
            "was not initialized"
        )

    try:
        verified = (
            verify_registration_response(
                credential=credential,
                expected_challenge=(
                    _challenge_bytes(
                        challenge
                    )
                ),
                expected_rp_id=(
                    rp_id
                ),
                expected_origin=(
                    origin
                ),
                require_user_verification=True,
            )
        )

    except Exception as exc:
        raise PasskeyVerificationError(
            "Invalid passkey registration response"
        ) from exc

    credential_id = bytes(
        verified
        .credential_id
    )

    public_key = bytes(
        verified
        .credential_public_key
    )

    if (
        not credential_id
        or not public_key
    ):
        raise PasskeyVerificationError(
            "Verified passkey material is empty"
        )

    existing = db.scalar(
        select(
            DashboardAuthPasskeyCredential
        ).where(
            DashboardAuthPasskeyCredential
            .credential_id
            == credential_id
        )
    )

    if existing is not None:
        raise PasskeyStateError(
            "Passkey credential is already registered"
        )

    row = (
        DashboardAuthPasskeyCredential(
            username=normalized,
            credential_id=(
                credential_id
            ),
            credential_public_key=(
                public_key
            ),
            sign_count=int(
                verified
                .sign_count
            ),
            transports_json=(
                json.dumps(
                    _transports_from_credential(
                        credential
                    ),
                    separators=(
                        ",",
                        ":",
                    ),
                )
            ),
            credential_device_type=(
                _enum_text(
                    verified
                    .credential_device_type
                )
            ),
            credential_backed_up=(
                bool(
                    verified
                    .credential_backed_up
                )
            ),
            label=(
                _normalize_label(
                    label
                )
            ),
            created_at=(
                now
                or utcnow()
            ),
        )
    )

    db.add(
        row
    )

    db.flush()

    return (
        _credential_snapshot(
            row
        )
    )


def store_passkey_registration(
    *,
    username: str,
    challenge: (
        bytes
        | bytearray
        | memoryview
    ),
    credential: Any,
    settings: Settings,
    label: str = "Passkey",
    now: datetime | None = None,
) -> dict[str, Any]:
    db = SessionLocal()

    try:
        _begin_serialized_write(
            db
        )

        result = (
            verify_and_store_passkey_registration_in_session(
                db,
                username=username,
                challenge=challenge,
                credential=credential,
                settings=settings,
                label=label,
                now=now,
            )
        )

        db.commit()

        return result

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def generate_passkey_authentication_options(
    *,
    challenge: (
        bytes
        | bytearray
        | memoryview
    ),
    settings: Settings,
    username: str | None = None,
) -> dict[str, Any]:
    (
        rp_id,
        _origin,
        _rp_name,
    ) = _webauthn_config(
        settings
    )

    allow_credentials = None

    if username is not None:
        normalized = (
            _normalize_username(
                username
            )
        )

        with session_scope() as db:
            user = db.get(
                DashboardAuthPasskeyUser,
                normalized,
            )

            if (
                user is None
                or not user.enabled
            ):
                raise PasskeyStateError(
                    "Passkey authentication "
                    "is not enabled"
                )

            rows = list(
                db.scalars(
                    select(
                        DashboardAuthPasskeyCredential
                    ).where(
                        DashboardAuthPasskeyCredential
                        .username
                        == normalized,
                        DashboardAuthPasskeyCredential
                        .revoked_at
                        .is_(
                            None
                        ),
                    )
                )
            )

        if not rows:
            raise PasskeyStateError(
                "No active passkey credential "
                "is registered"
            )

        allow_credentials = [
            _descriptor(
                row
            )
            for row
            in rows
        ]

    options = (
        generate_authentication_options(
            rp_id=rp_id,
            challenge=(
                _challenge_bytes(
                    challenge
                )
            ),
            allow_credentials=(
                allow_credentials
            ),
            user_verification=(
                UserVerificationRequirement
                .REQUIRED
            ),
        )
    )

    return json.loads(
        options_to_json(
            options
        )
    )


def verify_and_update_passkey_authentication_in_session(
    db: Session,
    *,
    challenge: (
        bytes
        | bytearray
        | memoryview
    ),
    credential: Any,
    settings: Settings,
    username: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    (
        rp_id,
        origin,
        _rp_name,
    ) = _webauthn_config(
        settings
    )

    credential_id = (
        _credential_id_from_payload(
            credential
        )
    )

    row = db.scalar(
        select(
            DashboardAuthPasskeyCredential
        )
        .where(
            DashboardAuthPasskeyCredential
            .credential_id
            == credential_id,
            DashboardAuthPasskeyCredential
            .revoked_at
            .is_(
                None
            ),
        )
        .with_for_update()
    )

    if row is None:
        raise PasskeyVerificationError(
            "Passkey credential "
            "is not registered"
        )

    if username is not None:
        normalized = (
            _normalize_username(
                username
            )
        )

        if (
            row.username
            != normalized
        ):
            raise PasskeyVerificationError(
                "Passkey credential does not "
                "belong to this user"
            )

    user = db.get(
        DashboardAuthPasskeyUser,
        row.username,
    )

    if (
        user is None
        or not user.enabled
    ):
        raise PasskeyStateError(
            "Passkey authentication "
            "is not enabled"
        )

    current_sign_count = int(
        row.sign_count
    )

    try:
        verified = (
            verify_authentication_response(
                credential=credential,
                expected_challenge=(
                    _challenge_bytes(
                        challenge
                    )
                ),
                expected_rp_id=(
                    rp_id
                ),
                expected_origin=(
                    origin
                ),
                credential_public_key=(
                    bytes(
                        row
                        .credential_public_key
                    )
                ),
                credential_current_sign_count=(
                    current_sign_count
                ),
                require_user_verification=True,
            )
        )

    except Exception as exc:
        raise PasskeyVerificationError(
            "Invalid passkey "
            "authentication response"
        ) from exc

    if (
        bytes(
            verified
            .credential_id
        )
        != credential_id
    ):
        raise PasskeyVerificationError(
            "Verified passkey "
            "credential ID mismatch"
        )

    new_sign_count = int(
        verified
        .new_sign_count
    )

    if (
        new_sign_count
        < current_sign_count
    ):
        raise PasskeyVerificationError(
            "Passkey sign counter "
            "moved backwards"
        )

    row.sign_count = (
        new_sign_count
    )

    row.credential_device_type = (
        _enum_text(
            verified
            .credential_device_type
        )
    )

    row.credential_backed_up = (
        bool(
            verified
            .credential_backed_up
        )
    )

    row.last_used_at = (
        now
        or utcnow()
    )

    db.flush()

    result = (
        _credential_snapshot(
            row
        )
    )

    result[
        "user_verified"
    ] = bool(
        verified
        .user_verified
    )

    return result


def authenticate_passkey(
    *,
    challenge: (
        bytes
        | bytearray
        | memoryview
    ),
    credential: Any,
    settings: Settings,
    username: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    db = SessionLocal()

    try:
        _begin_serialized_write(
            db
        )

        result = (
            verify_and_update_passkey_authentication_in_session(
                db,
                challenge=challenge,
                credential=credential,
                settings=settings,
                username=username,
                now=now,
            )
        )

        db.commit()

        return result

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()
