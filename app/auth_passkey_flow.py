from __future__ import annotations

import base64
import binascii
import hmac
import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .auth_passkey import (
    generate_passkey_authentication_options,
    generate_passkey_registration_options,
    verify_and_store_passkey_registration_in_session,
    verify_and_update_passkey_authentication_in_session,
)
from .auth_state import (
    consume_auth_challenge_in_session,
    create_auth_challenge,
    get_auth_challenge_in_session,
    hash_opaque_token,
)
from .config import Settings
from .db import SessionLocal, engine

PASSKEY_REGISTRATION_PURPOSE = (
    "passkey_registration"
)

PASSKEY_AUTHENTICATION_PURPOSE = (
    "passkey_authentication"
)

WEBAUTHN_CHALLENGE_BYTES = 32


class PasskeyFlowError(RuntimeError):
    """Base error for challenge-bound passkey ceremonies."""


class PasskeyChallengeError(PasskeyFlowError):
    """Raised when durable ceremony state is missing or invalid."""


def _normalize_username(
    value: str,
) -> str:
    normalized = str(
        value or ""
    ).strip().lower()

    if (
        not normalized
        or len(normalized) > 64
    ):
        raise PasskeyChallengeError(
            "Invalid passkey username"
        )

    return normalized


def _new_webauthn_challenge() -> bytes:
    return secrets.token_bytes(
        WEBAUTHN_CHALLENGE_BYTES
    )


def _encode_bytes(
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


def _decode_bytes(
    value: Any,
) -> bytes:
    normalized = str(
        value or ""
    ).strip()

    if not normalized:
        raise PasskeyChallengeError(
            "WebAuthn challenge metadata is missing"
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
        decoded = (
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

    except (
        ValueError,
        UnicodeError,
        binascii.Error,
    ) as exc:
        raise PasskeyChallengeError(
            "WebAuthn challenge metadata is invalid"
        ) from exc

    if (
        len(
            decoded
        )
        != WEBAUTHN_CHALLENGE_BYTES
    ):
        raise PasskeyChallengeError(
            "WebAuthn challenge metadata has "
            "an invalid length"
        )

    return decoded


def _metadata(
    challenge: dict[str, Any],
) -> dict[str, Any]:
    value = challenge.get(
        "metadata"
    )

    if not isinstance(
        value,
        dict,
    ):
        raise PasskeyChallengeError(
            "Passkey challenge metadata is invalid"
        )

    return value


def _webauthn_binding(
    settings: Settings,
) -> dict[str, str]:
    rp_id = str(
        settings.dashboard_webauthn_rp_id
        or ""
    ).strip()

    origin = str(
        settings.dashboard_webauthn_origin
        or ""
    ).strip()

    if (
        not rp_id
        or not origin
    ):
        raise PasskeyChallengeError(
            "WebAuthn challenge configuration "
            "is incomplete"
        )

    return {
        "webauthn_rp_id":
            rp_id,
        "webauthn_origin":
            origin,
    }


def _verify_webauthn_binding(
    metadata: dict[str, Any],
    settings: Settings,
) -> None:
    expected = (
        _webauthn_binding(
            settings
        )
    )

    stored_rp_id = str(
        metadata.get(
            "webauthn_rp_id",
            "",
        )
        or ""
    ).strip()

    stored_origin = str(
        metadata.get(
            "webauthn_origin",
            "",
        )
        or ""
    ).strip()

    if (
        not stored_rp_id
        or not stored_origin
        or not hmac.compare_digest(
            stored_rp_id,
            expected[
                "webauthn_rp_id"
            ],
        )
        or not hmac.compare_digest(
            stored_origin,
            expected[
                "webauthn_origin"
            ],
        )
    ):
        raise PasskeyChallengeError(
            "WebAuthn challenge configuration "
            "binding is invalid"
        )


def _serialized_write(
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


def _parent_hash(
    token: str,
) -> str:
    normalized = str(
        token or ""
    )

    if not normalized:
        raise PasskeyChallengeError(
            "Parent authentication challenge is missing"
        )

    return hash_opaque_token(
        normalized
    )


def _verify_parent_binding(
    metadata: dict[str, Any],
    parent_challenge_token: str | None,
) -> None:
    stored = str(
        metadata.get(
            "parent_challenge_hash",
            "",
        )
        or ""
    ).strip()

    if (
        parent_challenge_token
        is None
    ):
        if stored:
            raise PasskeyChallengeError(
                "Passkey challenge is bound "
                "to another authentication flow"
            )

        return

    expected = (
        _parent_hash(
            parent_challenge_token
        )
    )

    if (
        not stored
        or not hmac.compare_digest(
            stored,
            expected,
        )
    ):
        raise PasskeyChallengeError(
            "Passkey challenge parent binding "
            "is invalid"
        )


def begin_passkey_registration(
    *,
    username: str,
    settings: Settings,
    display_name: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized = (
        _normalize_username(
            username
        )
    )

    webauthn_challenge = (
        _new_webauthn_challenge()
    )

    options = (
        generate_passkey_registration_options(
            username=normalized,
            challenge=(
                webauthn_challenge
            ),
            settings=settings,
            display_name=(
                display_name
            ),
        )
    )

    challenge_token, challenge = (
        create_auth_challenge(
            username=normalized,
            purpose=(
                PASSKEY_REGISTRATION_PURPOSE
            ),
            ttl_seconds=(
                settings
                .dashboard_auth_challenge_ttl_seconds
            ),
            metadata={
                "webauthn_challenge":
                    _encode_bytes(
                        webauthn_challenge
                    ),
                **_webauthn_binding(
                    settings
                ),
            },
            now=now,
        )
    )

    return {
        "status":
            "passkey_registration_required",
        "challenge_token":
            challenge_token,
        "challenge_expires_at":
            challenge[
                "expires_at"
            ],
        "options":
            options,
    }


def complete_passkey_registration(
    *,
    challenge_token: str,
    credential: Any,
    settings: Settings,
    label: str = "Passkey",
    now: datetime | None = None,
) -> dict[str, Any]:
    db = SessionLocal()

    try:
        _serialized_write(
            db
        )

        challenge = (
            get_auth_challenge_in_session(
                db,
                challenge_token,
                purpose=(
                    PASSKEY_REGISTRATION_PURPOSE
                ),
                now=now,
            )
        )

        if challenge is None:
            raise PasskeyChallengeError(
                "Invalid or expired passkey "
                "registration challenge"
            )

        metadata = (
            _metadata(
                challenge
            )
        )

        _verify_webauthn_binding(
            metadata,
            settings,
        )

        webauthn_challenge = (
            _decode_bytes(
                metadata.get(
                    "webauthn_challenge"
                )
            )
        )

        credential_result = (
            verify_and_store_passkey_registration_in_session(
                db,
                username=(
                    challenge[
                        "username"
                    ]
                ),
                challenge=(
                    webauthn_challenge
                ),
                credential=credential,
                settings=settings,
                label=label,
                now=now,
            )
        )

        consumed = (
            consume_auth_challenge_in_session(
                db,
                challenge_token,
                purpose=(
                    PASSKEY_REGISTRATION_PURPOSE
                ),
                now=now,
            )
        )

        if consumed is None:
            raise PasskeyChallengeError(
                "Passkey registration challenge "
                "is no longer valid"
            )

        db.commit()

        return {
            "credential":
                credential_result,
            "challenge":
                consumed,
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def begin_passkey_authentication(
    *,
    username: str,
    settings: Settings,
    parent_challenge_token: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized = (
        _normalize_username(
            username
        )
    )

    webauthn_challenge = (
        _new_webauthn_challenge()
    )

    options = (
        generate_passkey_authentication_options(
            username=normalized,
            challenge=(
                webauthn_challenge
            ),
            settings=settings,
        )
    )

    metadata: dict[
        str,
        Any,
    ] = {
        "webauthn_challenge":
            _encode_bytes(
                webauthn_challenge
            ),
        **_webauthn_binding(
            settings
        ),
    }

    if (
        parent_challenge_token
        is not None
    ):
        metadata[
            "parent_challenge_hash"
        ] = (
            _parent_hash(
                parent_challenge_token
            )
        )

    challenge_token, challenge = (
        create_auth_challenge(
            username=normalized,
            purpose=(
                PASSKEY_AUTHENTICATION_PURPOSE
            ),
            ttl_seconds=(
                settings
                .dashboard_auth_challenge_ttl_seconds
            ),
            metadata=metadata,
            now=now,
        )
    )

    return {
        "status":
            "passkey_authentication_required",
        "challenge_token":
            challenge_token,
        "challenge_expires_at":
            challenge[
                "expires_at"
            ],
        "options":
            options,
    }


def verify_passkey_authentication_challenge_in_session(
    db: Session,
    *,
    challenge_token: str,
    credential: Any,
    settings: Settings,
    username: str,
    parent_challenge_token: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized = (
        _normalize_username(
            username
        )
    )

    challenge = (
        get_auth_challenge_in_session(
            db,
            challenge_token,
            purpose=(
                PASSKEY_AUTHENTICATION_PURPOSE
            ),
            now=now,
        )
    )

    if challenge is None:
        raise PasskeyChallengeError(
            "Invalid or expired passkey "
            "authentication challenge"
        )

    if (
        str(
            challenge.get(
                "username",
                "",
            )
        ).strip().lower()
        != normalized
    ):
        raise PasskeyChallengeError(
            "Passkey challenge user mismatch"
        )

    metadata = (
        _metadata(
            challenge
        )
    )

    _verify_parent_binding(
        metadata,
        parent_challenge_token,
    )

    _verify_webauthn_binding(
        metadata,
        settings,
    )

    webauthn_challenge = (
        _decode_bytes(
            metadata.get(
                "webauthn_challenge"
            )
        )
    )

    credential_result = (
        verify_and_update_passkey_authentication_in_session(
            db,
            challenge=(
                webauthn_challenge
            ),
            credential=credential,
            settings=settings,
            username=normalized,
            now=now,
        )
    )

    consumed = (
        consume_auth_challenge_in_session(
            db,
            challenge_token,
            purpose=(
                PASSKEY_AUTHENTICATION_PURPOSE
            ),
            now=now,
        )
    )

    if consumed is None:
        raise PasskeyChallengeError(
            "Passkey authentication challenge "
            "is no longer valid"
        )

    return {
        "credential":
            credential_result,
        "challenge":
            consumed,
    }
