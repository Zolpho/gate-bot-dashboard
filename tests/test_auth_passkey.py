from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

import app.auth_passkey as passkeys
from app.auth_passkey import (
    PasskeyConfigurationError,
    PasskeyStateError,
    PasskeyVerificationError,
    authenticate_passkey,
    generate_passkey_authentication_options,
    generate_passkey_registration_options,
    passkey_status,
    revoke_passkey_credential,
    set_passkey_enabled,
    store_passkey_registration,
    verify_and_store_passkey_registration_in_session,
)
from app.config import Settings
from app.db import SessionLocal, init_db
from app.models import DashboardAuthPasskeyCredential


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
                "hybrid",
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
    label: str = "Laptop",
) -> dict:
    challenge = (
        b"r"
        * 32
    )

    generate_passkey_registration_options(
        username=username,
        challenge=challenge,
        settings=_settings(),
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
        store_passkey_registration(
            username=username,
            challenge=challenge,
            credential=(
                _credential(
                    credential_id
                )
            ),
            settings=_settings(),
            label=label,
        )
    )


def test_passkey_engine_requires_explicit_global_gate() -> None:
    init_db()

    settings = Settings(
        dashboard_webauthn_rp_id=(
            "example.invalid"
        ),
        dashboard_webauthn_origin=(
            "https://example.invalid"
        ),
    )

    assert (
        settings
        .dashboard_webauthn_enabled
        is False
    )

    with pytest.raises(
        PasskeyConfigurationError
    ):
        generate_passkey_registration_options(
            username=(
                "passkey-gate-user"
            ),
            challenge=(
                b"g"
                * 32
            ),
            settings=settings,
        )


def test_registration_options_are_discoverable_and_user_handle_is_stable() -> None:
    init_db()

    first = (
        generate_passkey_registration_options(
            username=(
                "passkey-options-user"
            ),
            challenge=(
                b"a"
                * 32
            ),
            settings=_settings(),
        )
    )

    second = (
        generate_passkey_registration_options(
            username=(
                "passkey-options-user"
            ),
            challenge=(
                b"b"
                * 32
            ),
            settings=_settings(),
        )
    )

    assert (
        first[
            "rp"
        ][
            "id"
        ]
        == "example.invalid"
    )

    assert (
        first[
            "user"
        ][
            "id"
        ]
        == second[
            "user"
        ][
            "id"
        ]
    )

    selection = (
        first[
            "authenticatorSelection"
        ]
    )

    assert (
        selection[
            "residentKey"
        ]
        == "required"
    )

    assert (
        selection[
            "requireResidentKey"
        ]
        is True
    )

    assert (
        selection[
            "userVerification"
        ]
        == "required"
    )

    status = (
        passkey_status(
            "passkey-options-user"
        )
    )

    assert (
        status[
            "enabled"
        ]
        is False
    )

    assert (
        status[
            "credential_count"
        ]
        == 0
    )


def test_registration_does_not_enable_factor_until_user_switches_it_on(
    monkeypatch,
) -> None:
    init_db()

    captured: dict = {}

    def fake_verify(
        **kwargs,
    ):
        captured.update(
            kwargs
        )

        return (
            _fake_registration(
                b"credential-one"
            )
        )

    generate_passkey_registration_options(
        username=(
            "passkey-register-user"
        ),
        challenge=(
            b"c"
            * 32
        ),
        settings=_settings(),
    )

    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        fake_verify,
    )

    stored = (
        store_passkey_registration(
            username=(
                "passkey-register-user"
            ),
            challenge=(
                b"c"
                * 32
            ),
            credential=(
                _credential(
                    b"credential-one"
                )
            ),
            settings=_settings(),
            label="MacBook",
        )
    )

    assert (
        captured[
            "expected_rp_id"
        ]
        == "example.invalid"
    )

    assert (
        captured[
            "expected_origin"
        ]
        == "https://example.invalid"
    )

    assert (
        captured[
            "require_user_verification"
        ]
        is True
    )

    assert (
        stored[
            "label"
        ]
        == "MacBook"
    )

    assert (
        stored[
            "transports"
        ]
        == [
            "internal",
            "hybrid",
        ]
    )

    before = (
        passkey_status(
            "passkey-register-user"
        )
    )

    assert (
        before[
            "enabled"
        ]
        is False
    )

    assert (
        before[
            "available"
        ]
        is False
    )

    assert (
        before[
            "credential_count"
        ]
        == 1
    )

    after = (
        set_passkey_enabled(
            "passkey-register-user",
            True,
        )
    )

    assert (
        after[
            "enabled"
        ]
        is True
    )

    assert (
        after[
            "available"
        ]
        is True
    )


def test_multiple_credentials_and_duplicate_credential_rejection(
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-multiple-user"
    )

    generate_passkey_registration_options(
        username=username,
        challenge=(
            b"d"
            * 32
        ),
        settings=_settings(),
    )

    def fake_verify(
        *,
        credential,
        **_kwargs,
    ):
        raw_id = (
            credential[
                "rawId"
            ]
        )

        padding = (
            "="
            * (
                -len(
                    raw_id
                )
                % 4
            )
        )

        credential_id = (
            base64
            .urlsafe_b64decode(
                raw_id
                + padding
            )
        )

        return (
            _fake_registration(
                credential_id
            )
        )

    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        fake_verify,
    )

    first = (
        _credential(
            b"credential-multi-one"
        )
    )

    second = (
        _credential(
            b"credential-multi-two"
        )
    )

    store_passkey_registration(
        username=username,
        challenge=(
            b"d"
            * 32
        ),
        credential=first,
        settings=_settings(),
        label="Phone",
    )

    options = (
        generate_passkey_registration_options(
            username=username,
            challenge=(
                b"e"
                * 32
            ),
            settings=_settings(),
        )
    )

    assert (
        len(
            options.get(
                "excludeCredentials",
                [],
            )
        )
        == 1
    )

    store_passkey_registration(
        username=username,
        challenge=(
            b"e"
            * 32
        ),
        credential=second,
        settings=_settings(),
        label="Security key",
    )

    assert (
        passkey_status(
            username
        )[
            "credential_count"
        ]
        == 2
    )

    with pytest.raises(
        PasskeyStateError
    ):
        store_passkey_registration(
            username=username,
            challenge=(
                b"f"
                * 32
            ),
            credential=first,
            settings=_settings(),
        )


def test_authentication_options_support_bound_and_discoverable_modes(
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-auth-options-user"
    )

    _register(
        monkeypatch,
        username=username,
        credential_id=(
            b"credential-auth-options"
        ),
    )

    set_passkey_enabled(
        username,
        True,
    )

    bound = (
        generate_passkey_authentication_options(
            username=username,
            challenge=(
                b"h"
                * 32
            ),
            settings=_settings(),
        )
    )

    assert (
        bound[
            "rpId"
        ]
        == "example.invalid"
    )

    assert (
        bound[
            "userVerification"
        ]
        == "required"
    )

    assert (
        len(
            bound.get(
                "allowCredentials",
                [],
            )
        )
        == 1
    )

    discoverable = (
        generate_passkey_authentication_options(
            username=None,
            challenge=(
                b"i"
                * 32
            ),
            settings=_settings(),
        )
    )

    assert (
        discoverable[
            "rpId"
        ]
        == "example.invalid"
    )

    assert (
        discoverable[
            "userVerification"
        ]
        == "required"
    )

    assert (
        discoverable.get(
            "allowCredentials"
        )
        in (
            None,
            [],
        )
    )


def test_authentication_updates_sign_counter_and_public_metadata(
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-authenticate-user"
    )

    credential_id = (
        b"credential-authenticate"
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

    captured: dict = {}

    def fake_authentication(
        **kwargs,
    ):
        captured.update(
            kwargs
        )

        return SimpleNamespace(
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

    monkeypatch.setattr(
        passkeys,
        "verify_authentication_response",
        fake_authentication,
    )

    result = (
        authenticate_passkey(
            username=username,
            challenge=(
                b"j"
                * 32
            ),
            credential=(
                _credential(
                    credential_id
                )
            ),
            settings=_settings(),
        )
    )

    assert (
        captured[
            "credential_current_sign_count"
        ]
        == 2
    )

    assert (
        captured[
            "require_user_verification"
        ]
        is True
    )

    assert (
        result[
            "sign_count"
        ]
        == 3
    )

    assert (
        result[
            "credential_device_type"
        ]
        == "multi_device"
    )

    assert (
        result[
            "credential_backed_up"
        ]
        is True
    )

    assert (
        result[
            "user_verified"
        ]
        is True
    )


def test_wrong_username_is_rejected_before_authenticator_acceptance(
    monkeypatch,
) -> None:
    init_db()

    credential_id = (
        b"credential-bound-user"
    )

    _register(
        monkeypatch,
        username=(
            "passkey-owner-user"
        ),
        credential_id=(
            credential_id
        ),
    )

    set_passkey_enabled(
        "passkey-owner-user",
        True,
    )

    monkeypatch.setattr(
        passkeys,
        "verify_authentication_response",
        lambda **_kwargs: (
            pytest.fail(
                "verifier must not run "
                "for wrong username"
            )
        ),
    )

    with pytest.raises(
        PasskeyVerificationError
    ):
        authenticate_passkey(
            username=(
                "passkey-other-user"
            ),
            challenge=(
                b"k"
                * 32
            ),
            credential=(
                _credential(
                    credential_id
                )
            ),
            settings=_settings(),
        )


def test_revoking_last_credential_disables_passkey_factor(
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-revoke-user"
    )

    stored = (
        _register(
            monkeypatch,
            username=username,
            credential_id=(
                b"credential-revoke"
            ),
        )
    )

    set_passkey_enabled(
        username,
        True,
    )

    assert (
        revoke_passkey_credential(
            username,
            stored[
                "credential_id"
            ],
        )
    )

    status = (
        passkey_status(
            username
        )
    )

    assert (
        status[
            "enabled"
        ]
        is False
    )

    assert (
        status[
            "available"
        ]
        is False
    )

    assert (
        status[
            "credential_count"
        ]
        == 0
    )

    with pytest.raises(
        PasskeyStateError
    ):
        generate_passkey_authentication_options(
            username=username,
            challenge=(
                b"l"
                * 32
            ),
            settings=_settings(),
        )


def test_registration_in_session_obeys_caller_rollback(
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-rollback-user"
    )

    credential_id = (
        b"credential-rollback"
    )

    generate_passkey_registration_options(
        username=username,
        challenge=(
            b"m"
            * 32
        ),
        settings=_settings(),
    )

    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        lambda **_kwargs: (
            _fake_registration(
                credential_id
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

        verify_and_store_passkey_registration_in_session(
            db,
            username=username,
            challenge=(
                b"m"
                * 32
            ),
            credential=(
                _credential(
                    credential_id
                )
            ),
            settings=_settings(),
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

        db.rollback()

    finally:
        db.close()

    assert (
        passkey_status(
            username
        )[
            "credential_count"
        ]
        == 0
    )
