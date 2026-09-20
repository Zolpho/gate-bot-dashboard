from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

import app.auth_passkey as passkeys
from app.auth_passkey import (
    PasskeyVerificationError,
    passkey_status,
    set_passkey_enabled,
)
from app.auth_passkey_flow import (
    PasskeyChallengeError,
    begin_passkey_authentication,
    begin_passkey_registration,
    complete_passkey_registration,
    verify_passkey_authentication_challenge_in_session,
)
from app.auth_state import (
    get_auth_challenge,
    get_auth_challenge_in_session,
)
from app.config import Settings
from app.db import SessionLocal, init_db
from app.models import (
    DashboardAuthPasskeyCredential,
)


def _settings() -> Settings:
    return Settings(
        dashboard_webauthn_enabled=True,
        dashboard_webauthn_rp_id=(
            "example.invalid"
        ),
        dashboard_webauthn_origin=(
            "https://example.invalid"
        ),
        dashboard_webauthn_rp_name=(
            "Gate Bot Dashboard Test"
        ),
    )


def _b64url(
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


def _credential(
    credential_id: bytes,
) -> dict:
    encoded = (
        _b64url(
            credential_id
        )
    )

    return {
        "id":
            encoded,
        "rawId":
            encoded,
        "response": {
            "transports": [
                "internal",
            ],
        },
        "type":
            "public-key",
        "clientExtensionResults":
            {},
    }


def _fake_registration(
    credential_id: bytes,
    *,
    sign_count: int = 0,
):
    return SimpleNamespace(
        credential_id=(
            credential_id
        ),
        credential_public_key=(
            b"public-key-"
            + credential_id
        ),
        sign_count=(
            sign_count
        ),
        credential_device_type=(
            SimpleNamespace(
                value="single_device"
            )
        ),
        credential_backed_up=False,
        user_verified=True,
    )


def _register(
    monkeypatch,
    *,
    username: str,
    credential_id: bytes,
    sign_count: int = 0,
) -> dict:
    started = (
        begin_passkey_registration(
            username=username,
            settings=_settings(),
        )
    )

    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        lambda **_kwargs: (
            _fake_registration(
                credential_id,
                sign_count=(
                    sign_count
                ),
            )
        ),
    )

    return (
        complete_passkey_registration(
            challenge_token=(
                started[
                    "challenge_token"
                ]
            ),
            credential=(
                _credential(
                    credential_id
                )
            ),
            settings=_settings(),
            label="Test passkey",
        )
    )


def test_registration_challenge_matches_browser_options_and_is_one_time(
    monkeypatch,
) -> None:
    init_db()

    username = (
        "flow-registration-user"
    )

    started = (
        begin_passkey_registration(
            username=username,
            settings=_settings(),
        )
    )

    challenge_token = (
        started[
            "challenge_token"
        ]
    )

    durable = (
        get_auth_challenge(
            challenge_token,
            purpose=(
                "passkey_registration"
            ),
        )
    )

    assert durable is not None

    metadata = durable[
        "metadata"
    ]

    assert (
        metadata[
            "webauthn_challenge"
        ]
        == started[
            "options"
        ][
            "challenge"
        ]
    )

    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        lambda **_kwargs: (
            _fake_registration(
                b"flow-registration-credential"
            )
        ),
    )

    completed = (
        complete_passkey_registration(
            challenge_token=(
                challenge_token
            ),
            credential=(
                _credential(
                    b"flow-registration-credential"
                )
            ),
            settings=_settings(),
            label="Laptop",
        )
    )

    assert (
        completed[
            "challenge"
        ][
            "consumed_at"
        ]
    )

    status = (
        passkey_status(
            username
        )
    )

    assert (
        status[
            "credential_count"
        ]
        == 1
    )

    assert (
        status[
            "enabled"
        ]
        is False
    )

    with pytest.raises(
        PasskeyChallengeError
    ):
        complete_passkey_registration(
            challenge_token=(
                challenge_token
            ),
            credential=(
                _credential(
                    b"another-credential"
                )
            ),
            settings=_settings(),
        )


def test_failed_registration_does_not_consume_challenge(
    monkeypatch,
) -> None:
    init_db()

    started = (
        begin_passkey_registration(
            username=(
                "flow-registration-failure-user"
            ),
            settings=_settings(),
        )
    )

    challenge_token = (
        started[
            "challenge_token"
        ]
    )

    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        lambda **_kwargs: (
            (_ for _ in ())
            .throw(
                ValueError(
                    "invalid registration"
                )
            )
        ),
    )

    with pytest.raises(
        PasskeyVerificationError
    ):
        complete_passkey_registration(
            challenge_token=(
                challenge_token
            ),
            credential=(
                _credential(
                    b"invalid-registration"
                )
            ),
            settings=_settings(),
        )

    assert (
        get_auth_challenge(
            challenge_token,
            purpose=(
                "passkey_registration"
            ),
        )
        is not None
    )


def test_authentication_challenge_is_bound_to_parent_flow(
    monkeypatch,
) -> None:
    init_db()

    username = (
        "flow-parent-user"
    )

    _register(
        monkeypatch,
        username=username,
        credential_id=(
            b"flow-parent-credential"
        ),
    )

    set_passkey_enabled(
        username,
        True,
    )

    parent = (
        "opaque-parent-challenge-one"
    )

    started = (
        begin_passkey_authentication(
            username=username,
            settings=_settings(),
            parent_challenge_token=(
                parent
            ),
        )
    )

    monkeypatch.setattr(
        passkeys,
        "verify_authentication_response",
        lambda **_kwargs: (
            pytest.fail(
                "WebAuthn verifier must not run "
                "for a wrong parent challenge"
            )
        ),
    )

    db = SessionLocal()

    try:
        db.execute(
            text(
                "BEGIN IMMEDIATE"
            )
        )

        with pytest.raises(
            PasskeyChallengeError
        ):
            verify_passkey_authentication_challenge_in_session(
                db,
                challenge_token=(
                    started[
                        "challenge_token"
                    ]
                ),
                credential=(
                    _credential(
                        b"flow-parent-credential"
                    )
                ),
                settings=_settings(),
                username=username,
                parent_challenge_token=(
                    "different-parent"
                ),
            )

        db.rollback()

    finally:
        db.close()

    assert (
        get_auth_challenge(
            started[
                "challenge_token"
            ],
            purpose=(
                "passkey_authentication"
            ),
        )
        is not None
    )


def test_parent_bound_challenge_cannot_be_used_as_unbound(
    monkeypatch,
) -> None:
    init_db()

    username = (
        "flow-bound-user"
    )

    _register(
        monkeypatch,
        username=username,
        credential_id=(
            b"flow-bound-credential"
        ),
    )

    set_passkey_enabled(
        username,
        True,
    )

    started = (
        begin_passkey_authentication(
            username=username,
            settings=_settings(),
            parent_challenge_token=(
                "bound-parent"
            ),
        )
    )

    db = SessionLocal()

    try:
        db.execute(
            text(
                "BEGIN IMMEDIATE"
            )
        )

        with pytest.raises(
            PasskeyChallengeError
        ):
            verify_passkey_authentication_challenge_in_session(
                db,
                challenge_token=(
                    started[
                        "challenge_token"
                    ]
                ),
                credential=(
                    _credential(
                        b"flow-bound-credential"
                    )
                ),
                settings=_settings(),
                username=username,
                parent_challenge_token=None,
            )

        db.rollback()

    finally:
        db.close()


def test_authentication_update_and_challenge_consumption_share_transaction(
    monkeypatch,
) -> None:
    init_db()

    username = (
        "flow-atomic-user"
    )

    credential_id = (
        b"flow-atomic-credential"
    )

    _register(
        monkeypatch,
        username=username,
        credential_id=(
            credential_id
        ),
        sign_count=2,
    )

    set_passkey_enabled(
        username,
        True,
    )

    parent = (
        "flow-atomic-parent"
    )

    started = (
        begin_passkey_authentication(
            username=username,
            settings=_settings(),
            parent_challenge_token=(
                parent
            ),
        )
    )

    monkeypatch.setattr(
        passkeys,
        "verify_authentication_response",
        lambda **_kwargs: (
            SimpleNamespace(
                credential_id=(
                    credential_id
                ),
                new_sign_count=3,
                credential_device_type=(
                    SimpleNamespace(
                        value="multi_device"
                    )
                ),
                credential_backed_up=True,
                user_verified=True,
            )
        ),
    )

    db = SessionLocal()

    try:
        db.execute(
            text(
                "BEGIN IMMEDIATE"
            )
        )

        verified = (
            verify_passkey_authentication_challenge_in_session(
                db,
                challenge_token=(
                    started[
                        "challenge_token"
                    ]
                ),
                credential=(
                    _credential(
                        credential_id
                    )
                ),
                settings=_settings(),
                username=username,
                parent_challenge_token=(
                    parent
                ),
            )
        )

        assert (
            verified[
                "credential"
            ][
                "sign_count"
            ]
            == 3
        )

        row = db.scalar(
            select(
                DashboardAuthPasskeyCredential
            ).where(
                DashboardAuthPasskeyCredential
                .credential_id
                == credential_id
            )
        )

        assert row is not None
        assert row.sign_count == 3

        assert (
            get_auth_challenge_in_session(
                db,
                started[
                    "challenge_token"
                ],
                purpose=(
                    "passkey_authentication"
                ),
            )
            is None
        )

        # Caller-owned transaction: deliberately prove
        # credential update + challenge consumption roll back
        # together.
        db.rollback()

    finally:
        db.close()

    db = SessionLocal()

    try:
        row = db.scalar(
            select(
                DashboardAuthPasskeyCredential
            ).where(
                DashboardAuthPasskeyCredential
                .credential_id
                == credential_id
            )
        )

        assert row is not None
        assert row.sign_count == 2

    finally:
        db.close()

    assert (
        get_auth_challenge(
            started[
                "challenge_token"
            ],
            purpose=(
                "passkey_authentication"
            ),
        )
        is not None
    )
