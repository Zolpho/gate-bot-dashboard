from __future__ import annotations

from sqlalchemy import create_engine, inspect

from app import models as _models  # noqa: F401
from app.config import Settings
from app.db import Base


def test_auth_foundation_settings_default_fail_open_for_rollout() -> None:
    settings = Settings()

    assert settings.dashboard_mfa_required is False
    assert str(settings.dashboard_auth_encryption_key_file) == (
        "/run/secrets/dashboard_auth.key"
    )
    assert settings.dashboard_auth_session_ttl_seconds == 3600
    assert settings.dashboard_auth_challenge_ttl_seconds == 300


def test_auth_foundation_ttl_bounds() -> None:
    low_session = Settings(
        dashboard_auth_session_ttl_seconds=300,
    )
    high_session = Settings(
        dashboard_auth_session_ttl_seconds=86400,
    )
    low_challenge = Settings(
        dashboard_auth_challenge_ttl_seconds=60,
    )
    high_challenge = Settings(
        dashboard_auth_challenge_ttl_seconds=900,
    )

    assert low_session.dashboard_auth_session_ttl_seconds == 300
    assert high_session.dashboard_auth_session_ttl_seconds == 86400
    assert low_challenge.dashboard_auth_challenge_ttl_seconds == 60
    assert high_challenge.dashboard_auth_challenge_ttl_seconds == 900


def test_auth_foundation_tables_are_created_without_raw_tokens(tmp_path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth-foundation.db'}"
    )

    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    table_names = set(
        inspector.get_table_names()
    )

    expected = {
        "dashboard_auth_factors",
        "dashboard_auth_sessions",
        "dashboard_auth_challenges",
        "dashboard_auth_recovery_codes",
        "dashboard_auth_events",
        "dashboard_auth_rate_limit_events",
        "dashboard_auth_passkey_users",
        "dashboard_auth_passkey_credentials",
    }

    assert expected <= table_names

    factor_columns = {
        column["name"]
        for column in inspector.get_columns(
            "dashboard_auth_factors"
        )
    }

    session_columns = {
        column["name"]
        for column in inspector.get_columns(
            "dashboard_auth_sessions"
        )
    }

    challenge_columns = {
        column["name"]
        for column in inspector.get_columns(
            "dashboard_auth_challenges"
        )
    }

    assert factor_columns == {
        "username",
        "totp_secret_ciphertext",
        "totp_enabled",
        "totp_confirmed_at",
        "totp_last_used_counter",
        "created_at",
        "updated_at",
    }

    assert session_columns == {
        "id",
        "token_hash",
        "username",
        "credential_fingerprint",
        "auth_method",
        "mfa_completed",
        "created_at",
        "expires_at",
        "client_ip",
        "user_agent",
        "last_seen_at",
        "revoked_at",
    }

    assert challenge_columns == {
        "id",
        "token_hash",
        "username",
        "purpose",
        "metadata_json",
        "created_at",
        "expires_at",
        "consumed_at",
    }

    # Security invariant: opaque raw tokens are never durable.
    assert "token" not in session_columns
    assert "token" not in challenge_columns
    assert "token_hash" in session_columns
    assert "token_hash" in challenge_columns

    # Password identity remains in dashboard_users.json.
    assert "password_hash" not in factor_columns
    assert "password_hash" not in session_columns
    assert "password_hash" not in challenge_columns


def test_auth_foundation_has_unique_token_hashes(tmp_path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth-constraints.db'}"
    )

    Base.metadata.create_all(engine)

    inspector = inspect(engine)

    session_unique = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints(
            "dashboard_auth_sessions"
        )
    }

    challenge_unique = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints(
            "dashboard_auth_challenges"
        )
    }

    assert ("token_hash",) in session_unique
    assert ("token_hash",) in challenge_unique


def test_auth_encryption_key_generation_and_loading(tmp_path) -> None:
    from app.auth_state import (
        AUTH_ENCRYPTION_KEY_BYTES,
        generate_auth_encryption_key,
        load_auth_encryption_key,
    )

    key_path = (
        tmp_path
        / "dashboard_auth.key"
    )

    encoded = (
        generate_auth_encryption_key()
    )

    key_path.write_text(
        encoded + "\n",
        encoding="ascii",
    )

    key_path.chmod(0o600)

    loaded = (
        load_auth_encryption_key(
            key_path
        )
    )

    assert (
        len(loaded)
        == AUTH_ENCRYPTION_KEY_BYTES
    )

    assert (
        encoded
        not in repr(loaded)
    )


def test_auth_encryption_key_rejects_invalid_material(tmp_path) -> None:
    import pytest

    from app.auth_state import (
        AuthEncryptionKeyError,
        load_auth_encryption_key,
    )

    missing = (
        tmp_path
        / "missing.key"
    )

    with pytest.raises(
        AuthEncryptionKeyError
    ):
        load_auth_encryption_key(
            missing
        )

    malformed = (
        tmp_path
        / "malformed.key"
    )

    malformed.write_text(
        "not-a-32-byte-key\n",
        encoding="ascii",
    )

    with pytest.raises(
        AuthEncryptionKeyError
    ):
        load_auth_encryption_key(
            malformed
        )


def test_credential_fingerprint_changes_with_password_record() -> None:
    from app.auth_state import (
        credential_fingerprint,
    )

    first = credential_fingerprint(
        username="Alice",
        password_hash="hash-one",
    )

    second = credential_fingerprint(
        username="alice",
        password_hash="hash-two",
    )

    repeated = credential_fingerprint(
        username="alice",
        password_hash="hash-one",
    )

    assert len(first) == 64
    assert first == repeated
    assert first != second


def test_session_uses_hash_only_and_can_be_revoked() -> None:
    from sqlalchemy import select

    from app.auth_state import (
        create_auth_session,
        credential_fingerprint,
        get_auth_session,
        hash_opaque_token,
        revoke_auth_session,
    )
    from app.db import (
        init_db,
        session_scope,
    )
    from app.models import (
        DashboardAuthSession,
    )

    init_db()

    fingerprint = (
        credential_fingerprint(
            username="session-user",
            password_hash=(
                "pbkdf2_sha256$100000$"
                "salt$hash"
            ),
        )
    )

    token, issued = (
        create_auth_session(
            username="session-user",
            credential_hash=(
                fingerprint
            ),
            ttl_seconds=600,
        )
    )

    assert token
    assert issued["username"] == (
        "session-user"
    )
    assert "token" not in issued

    with session_scope() as db:
        row = db.scalar(
            select(
                DashboardAuthSession
            ).where(
                DashboardAuthSession
                .token_hash
                == hash_opaque_token(
                    token
                )
            )
        )

        assert row is not None
        assert row.token_hash != token

    active = get_auth_session(
        token
    )

    assert active is not None
    assert active["username"] == (
        "session-user"
    )

    assert revoke_auth_session(
        token
    )

    assert (
        get_auth_session(
            token
        )
        is None
    )


def test_expired_session_is_not_active() -> None:
    from datetime import (
        UTC,
        datetime,
        timedelta,
    )

    from app.auth_state import (
        create_auth_session,
        credential_fingerprint,
        get_auth_session,
    )
    from app.db import init_db

    init_db()

    issued_at = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    fingerprint = (
        credential_fingerprint(
            username="expired-user",
            password_hash="hash",
        )
    )

    token, _ = (
        create_auth_session(
            username="expired-user",
            credential_hash=(
                fingerprint
            ),
            ttl_seconds=300,
            now=issued_at,
        )
    )

    assert (
        get_auth_session(
            token,
            now=(
                issued_at
                + timedelta(
                    seconds=301
                )
            ),
        )
        is None
    )


def test_challenge_is_hash_only_and_one_time() -> None:
    from sqlalchemy import select

    from app.auth_state import (
        consume_auth_challenge,
        create_auth_challenge,
        hash_opaque_token,
    )
    from app.db import (
        init_db,
        session_scope,
    )
    from app.models import (
        DashboardAuthChallenge,
    )

    init_db()

    token, issued = (
        create_auth_challenge(
            username="challenge-user",
            purpose="login_mfa",
            metadata={
                "factor": "totp",
            },
        )
    )

    assert token
    assert "token" not in issued
    assert issued["metadata"] == {
        "factor": "totp",
    }

    with session_scope() as db:
        row = db.scalar(
            select(
                DashboardAuthChallenge
            ).where(
                DashboardAuthChallenge
                .token_hash
                == hash_opaque_token(
                    token
                )
            )
        )

        assert row is not None
        assert row.token_hash != token

    consumed = (
        consume_auth_challenge(
            token,
            purpose="login_mfa",
        )
    )

    assert consumed is not None
    assert consumed[
        "consumed_at"
    ]

    assert (
        consume_auth_challenge(
            token,
            purpose="login_mfa",
        )
        is None
    )


def test_challenge_wrong_purpose_does_not_consume() -> None:
    from app.auth_state import (
        consume_auth_challenge,
        create_auth_challenge,
    )
    from app.db import init_db

    init_db()

    token, _ = (
        create_auth_challenge(
            username="purpose-user",
            purpose=(
                "passkey_registration"
            ),
        )
    )

    assert (
        consume_auth_challenge(
            token,
            purpose="login_mfa",
        )
        is None
    )

    assert (
        consume_auth_challenge(
            token,
            purpose=(
                "passkey_registration"
            ),
        )
        is not None
    )


def test_passkey_foundation_settings_are_opt_in() -> None:
    settings = Settings()

    assert settings.dashboard_mfa_required is False
    assert settings.dashboard_webauthn_rp_id == ""
    assert settings.dashboard_webauthn_origin == ""
    assert (
        settings.dashboard_webauthn_rp_name
        == "Gate Bot Dashboard"
    )

    configured = Settings(
        dashboard_webauthn_rp_id=(
            "zolpho.github.io"
        ),
        dashboard_webauthn_origin=(
            "https://zolpho.github.io"
        ),
        dashboard_webauthn_rp_name=(
            "Gate Bot Dashboard"
        ),
    )

    assert (
        configured.dashboard_webauthn_rp_id
        == "zolpho.github.io"
    )
    assert (
        configured.dashboard_webauthn_origin
        == "https://zolpho.github.io"
    )


def test_passkey_foundation_tables_support_multiple_credentials(
    tmp_path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'passkeys.db'}"
    )

    Base.metadata.create_all(
        engine
    )

    inspector = inspect(
        engine
    )

    passkey_user_columns = {
        column["name"]
        for column in inspector.get_columns(
            "dashboard_auth_passkey_users"
        )
    }

    passkey_credential_columns = {
        column["name"]
        for column in inspector.get_columns(
            "dashboard_auth_passkey_credentials"
        )
    }

    assert passkey_user_columns == {
        "username",
        "user_handle",
        "enabled",
        "created_at",
        "updated_at",
    }

    assert passkey_credential_columns == {
        "id",
        "username",
        "credential_id",
        "credential_public_key",
        "sign_count",
        "transports_json",
        "credential_device_type",
        "credential_backed_up",
        "label",
        "created_at",
        "last_used_at",
        "revoked_at",
    }

    user_uniques = {
        tuple(
            item["column_names"]
        )
        for item in inspector.get_unique_constraints(
            "dashboard_auth_passkey_users"
        )
    }

    credential_uniques = {
        tuple(
            item["column_names"]
        )
        for item in inspector.get_unique_constraints(
            "dashboard_auth_passkey_credentials"
        )
    }

    assert (
        "user_handle",
    ) in user_uniques

    assert (
        "credential_id",
    ) in credential_uniques

    # The server stores only public credential material.
    assert (
        "credential_public_key"
        in passkey_credential_columns
    )
    assert (
        "private_key"
        not in passkey_credential_columns
    )


def test_passkey_factor_switch_is_independent_from_totp(
    tmp_path,
) -> None:
    from sqlalchemy.orm import Session

    from app.models import (
        DashboardAuthFactor,
        DashboardAuthPasskeyUser,
    )

    engine = create_engine(
        f"sqlite:///{tmp_path / 'passkey-switch.db'}"
    )

    Base.metadata.create_all(
        engine
    )

    with Session(
        engine
    ) as db:
        db.add(
            DashboardAuthFactor(
                username="alice",
                totp_enabled=True,
            )
        )

        db.add(
            DashboardAuthPasskeyUser(
                username="alice",
                user_handle=b"a" * 64,
                enabled=False,
            )
        )

        db.commit()

        totp = db.get(
            DashboardAuthFactor,
            "alice",
        )

        passkey = db.get(
            DashboardAuthPasskeyUser,
            "alice",
        )

        assert totp is not None
        assert passkey is not None

        assert totp.totp_enabled is True
        assert passkey.enabled is False

        passkey.enabled = True
        db.commit()

        assert totp.totp_enabled is True
        assert passkey.enabled is True
