from __future__ import annotations

import hmac
from datetime import datetime
from typing import Any

from sqlalchemy import text

from .auth_ip_restrictions import (
    evaluate_ip_restriction_access,
)
from .auth_passkey import (
    PasskeyStateError,
    PasskeyVerificationError,
    passkey_status,
)
from .auth_passkey_flow import (
    PasskeyChallengeError,
    begin_passkey_authentication,
    verify_passkey_authentication_challenge_in_session,
)
from .auth_rate_limit import (
    MFA_LOGIN,
    PASSWORD_LOGIN,
    enforce_auth_rate_limit,
)
from .auth_recovery import (
    consume_recovery_code_in_session,
    recovery_code_status,
)
from .auth_state import (
    consume_auth_challenge_in_session,
    create_auth_challenge,
    create_auth_session,
    create_auth_session_in_session,
    credential_fingerprint,
    get_auth_challenge,
    get_auth_challenge_in_session,
    get_auth_session,
    revoke_auth_session,
    touch_auth_session,
)
from .auth_totp import (
    totp_status,
    verify_totp_for_user_in_session,
)
from .config import Settings
from .db import SessionLocal, engine
from .security import (
    DashboardUser,
    load_dashboard_users,
    verify_password,
)

LOGIN_CHALLENGE_PURPOSE = (
    "login_mfa"
)

MFA_METHODS = {
    "totp",
    "recovery",
}

PASSKEY_MFA_METHOD = "passkey"


class LoginError(RuntimeError):
    """Base error for the transitional Bearer login flow."""


class LoginDenied(LoginError):
    """Authentication or MFA verification failed."""


class IpRestrictionDenied(LoginDenied):
    """
    Valid dashboard authentication cannot proceed from the
    currently observed network.
    """


class MfaEnrollmentRequired(LoginError):
    """
    Password authentication succeeded but current policy
    requires MFA enrollment before a Bearer session can exist.
    """


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
        raise LoginDenied(
            "Invalid username or password"
        )

    return normalized


def _normalize_mfa_method(
    value: str,
) -> str:
    normalized = str(
        value or ""
    ).strip().lower()

    if normalized not in MFA_METHODS:
        raise LoginDenied(
            "Unsupported MFA method"
        )

    return normalized


def _enabled_file_user(
    username: str,
    *,
    settings: Settings,
) -> DashboardUser | None:
    normalized = (
        _normalize_username(
            username
        )
    )

    users = load_dashboard_users(
        settings
    )

    return next(
        (
            user
            for user in users
            if (
                user.username
                == normalized
                and user.enabled
                and user.auth_source
                == "file"
            )
        ),
        None,
    )


def _fingerprint(
    user: DashboardUser,
) -> str:
    if not user.password_hash:
        raise LoginDenied(
            "Bearer login is unavailable "
            "for this dashboard identity"
        )

    return credential_fingerprint(
        username=user.username,
        password_hash=(
            user.password_hash
        ),
    )


def _require_ip_access(
    *,
    user: DashboardUser,
    settings: Settings,
    client_identifier: str | None,
) -> dict[str, Any]:
    decision = (
        evaluate_ip_restriction_access(
            username=user.username,
            client_ip=client_identifier,
            global_enforcement_enabled=(
                settings
                .dashboard_ip_restrictions_enforcement_enabled
            ),
        )
    )

    if not bool(
        decision.get(
            "allowed"
        )
    ):
        raise IpRestrictionDenied(
            "IP access denied"
        )

    return decision


def _authenticated_result(
    *,
    user: DashboardUser,
    fingerprint: str,
    auth_method: str,
    mfa_completed: bool,
    settings: Settings,
    client_identifier: str | None,
    user_agent: str | None,
    now: datetime | None,
) -> dict[str, Any]:
    _require_ip_access(
        user=user,
        settings=settings,
        client_identifier=(
            client_identifier
        ),
    )

    token, session = (
        create_auth_session(
            username=user.username,
            credential_hash=(
                fingerprint
            ),
            auth_method=auth_method,
            mfa_completed=(
                mfa_completed
            ),
            ttl_seconds=(
                settings
                .dashboard_auth_session_ttl_seconds
            ),
            client_ip=(
                client_identifier
            ),
            user_agent=(
                user_agent
            ),
            now=now,
        )
    )

    return {
        "status":
            "authenticated",
        "token_type":
            "bearer",
        "access_token":
            token,
        "user":
            user.safe_dict(),
        "session":
            session,
    }


def begin_password_login(
    *,
    username: str,
    password: str,
    settings: Settings,
    client_identifier: str | None = None,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Verify the file-backed dashboard password.

    If TOTP is already enabled, issue a short-lived MFA
    challenge. If MFA is not enrolled and global enforcement
    is disabled, issue a password-only Bearer session.

    No password is persisted in session/challenge state.
    """

    enforce_auth_rate_limit(
        settings=settings,
        username=username,
        action=PASSWORD_LOGIN,
        client_identifier=(
            client_identifier
        ),
        now=now,
    )


    normalized = (
        _normalize_username(
            username
        )
    )

    user = _enabled_file_user(
        normalized,
        settings=settings,
    )

    if (
        user is None
        or not verify_password(
            password,
            user.password_hash,
        )
    ):
        raise LoginDenied(
            "Invalid username or password"
        )

    # Do not issue an MFA challenge to a valid identity
    # from a network that would be unable to complete login.
    _require_ip_access(
        user=user,
        settings=settings,
        client_identifier=(
            client_identifier
        ),
    )

    fingerprint = (
        _fingerprint(
            user
        )
    )

    factor = totp_status(
        user.username
    )

    methods: list[str] = []

    if factor[
        "totp_enabled"
    ]:
        methods.append(
            "totp"
        )

        recovery = (
            recovery_code_status(
                user.username
            )
        )

        if (
            recovery[
                "active_count"
            ]
            > 0
        ):
            methods.append(
                "recovery"
            )

    if (
        settings
        .dashboard_webauthn_enabled
    ):
        passkey = (
            passkey_status(
                user.username
            )
        )

        if passkey[
            "available"
        ]:
            methods.append(
                PASSKEY_MFA_METHOD
            )

    if methods:
        challenge_token, challenge = (
            create_auth_challenge(
                username=(
                    user.username
                ),
                purpose=(
                    LOGIN_CHALLENGE_PURPOSE
                ),
                ttl_seconds=(
                    settings
                    .dashboard_auth_challenge_ttl_seconds
                ),
                metadata={
                    "credential_fingerprint":
                        fingerprint,
                    "allowed_methods":
                        methods,
                },
                now=now,
            )
        )

        return {
            "status":
                "mfa_required",
            "challenge_token":
                challenge_token,
            "methods":
                methods,
            "user":
                user.safe_dict(),
            "challenge":
                challenge,
        }

    if (
        settings
        .dashboard_mfa_required
    ):
        raise MfaEnrollmentRequired(
            "MFA enrollment is required"
        )

    return _authenticated_result(
        user=user,
        fingerprint=fingerprint,
        auth_method="password",
        mfa_completed=False,
        settings=settings,
        client_identifier=(
            client_identifier
        ),
        user_agent=(
            user_agent
        ),
        now=now,
    )


def begin_passkey_mfa_login(
    *,
    challenge_token: str,
    settings: Settings,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Start WebAuthn after the password-first login challenge.

    The parent password challenge remains active. The generated
    WebAuthn child challenge stores only a hash of the parent token.
    """

    parent = (
        get_auth_challenge(
            challenge_token,
            purpose=(
                LOGIN_CHALLENGE_PURPOSE
            ),
            now=now,
        )
    )

    if parent is None:
        raise LoginDenied(
            "Invalid or expired login challenge"
        )

    metadata = parent.get(
        "metadata"
    )

    if not isinstance(
        metadata,
        dict,
    ):
        raise LoginDenied(
            "Invalid login challenge"
        )

    allowed_methods = metadata.get(
        "allowed_methods"
    )

    if (
        not isinstance(
            allowed_methods,
            list,
        )
        or PASSKEY_MFA_METHOD
        not in allowed_methods
    ):
        raise LoginDenied(
            "Passkey is not available "
            "for this login challenge"
        )

    username = str(
        parent.get(
            "username",
            "",
        )
    ).strip().lower()

    user = _enabled_file_user(
        username,
        settings=settings,
    )

    if user is None:
        raise LoginDenied(
            "Invalid login challenge"
        )

    expected_fingerprint = str(
        metadata.get(
            "credential_fingerprint",
            "",
        )
    )

    current_fingerprint = (
        _fingerprint(
            user
        )
    )

    if not (
        expected_fingerprint
        and hmac.compare_digest(
            expected_fingerprint,
            current_fingerprint,
        )
    ):
        raise LoginDenied(
            "Login challenge is no longer valid"
        )

    try:
        return (
            begin_passkey_authentication(
                username=user.username,
                settings=settings,
                parent_challenge_token=(
                    challenge_token
                ),
                now=now,
            )
        )

    except (
        PasskeyChallengeError,
        PasskeyStateError,
        PasskeyVerificationError,
    ) as exc:
        raise LoginDenied(
            "Passkey authentication "
            "is not available"
        ) from exc


def complete_passkey_mfa_login(
    *,
    challenge_token: str,
    passkey_challenge_token: str,
    credential: Any,
    settings: Settings,
    client_identifier: str | None = None,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Complete password + passkey authentication atomically.

    Credential state update, child WebAuthn challenge consumption,
    parent password challenge consumption and Bearer-session issuance
    all share one serialized transaction.
    """

    preflight = (
        get_auth_challenge(
            challenge_token,
            purpose=(
                LOGIN_CHALLENGE_PURPOSE
            ),
            now=now,
        )
    )

    if preflight is None:
        raise LoginDenied(
            "Invalid or expired login challenge"
        )

    username = str(
        preflight.get(
            "username",
            "",
        )
    ).strip().lower()

    enforce_auth_rate_limit(
        settings=settings,
        username=username,
        action=MFA_LOGIN,
        client_identifier=(
            client_identifier
        ),
        challenge_token=(
            challenge_token
        ),
        now=now,
    )

    db = SessionLocal()

    try:
        if engine.dialect.name == "sqlite":
            db.execute(
                text(
                    "BEGIN IMMEDIATE"
                )
            )

        parent = (
            get_auth_challenge_in_session(
                db,
                challenge_token,
                purpose=(
                    LOGIN_CHALLENGE_PURPOSE
                ),
                now=now,
            )
        )

        if parent is None:
            raise LoginDenied(
                "Invalid or expired login challenge"
            )

        metadata = parent.get(
            "metadata"
        )

        if not isinstance(
            metadata,
            dict,
        ):
            raise LoginDenied(
                "Invalid login challenge"
            )

        allowed_methods = metadata.get(
            "allowed_methods"
        )

        if (
            not isinstance(
                allowed_methods,
                list,
            )
            or PASSKEY_MFA_METHOD
            not in allowed_methods
        ):
            raise LoginDenied(
                "Passkey is not available "
                "for this login challenge"
            )

        expected_fingerprint = str(
            metadata.get(
                "credential_fingerprint",
                "",
            )
        )

        user = _enabled_file_user(
            username,
            settings=settings,
        )

        if user is None:
            consumed = (
                consume_auth_challenge_in_session(
                    db,
                    challenge_token,
                    purpose=(
                        LOGIN_CHALLENGE_PURPOSE
                    ),
                    now=now,
                )
            )

            if consumed is None:
                raise LoginDenied(
                    "Invalid login challenge"
                )

            db.commit()

            raise LoginDenied(
                "Invalid login challenge"
            )

        current_fingerprint = (
            _fingerprint(
                user
            )
        )

        if not (
            expected_fingerprint
            and hmac.compare_digest(
                expected_fingerprint,
                current_fingerprint,
            )
        ):
            consumed = (
                consume_auth_challenge_in_session(
                    db,
                    challenge_token,
                    purpose=(
                        LOGIN_CHALLENGE_PURPOSE
                    ),
                    now=now,
                )
            )

            if consumed is None:
                raise LoginDenied(
                    "Login challenge is no longer valid"
                )

            db.commit()

            raise LoginDenied(
                "Login challenge is no longer valid"
            )

        # Re-check the current network at the actual
        # session-issuance boundary. A challenge may have been
        # started on another connection.
        _require_ip_access(
            user=user,
            settings=settings,
            client_identifier=(
                client_identifier
            ),
        )

        try:
            passkey_result = (
                verify_passkey_authentication_challenge_in_session(
                    db,
                    challenge_token=(
                        passkey_challenge_token
                    ),
                    credential=credential,
                    settings=settings,
                    username=(
                        user.username
                    ),
                    parent_challenge_token=(
                        challenge_token
                    ),
                    now=now,
                )
            )

        except (
            PasskeyChallengeError,
            PasskeyStateError,
            PasskeyVerificationError,
        ) as exc:
            raise LoginDenied(
                "Invalid or expired passkey "
                "challenge or credential"
            ) from exc

        consumed_parent = (
            consume_auth_challenge_in_session(
                db,
                challenge_token,
                purpose=(
                    LOGIN_CHALLENGE_PURPOSE
                ),
                now=now,
            )
        )

        if consumed_parent is None:
            raise LoginDenied(
                "Login challenge is no longer valid"
            )

        token, session = (
            create_auth_session_in_session(
                db,
                username=user.username,
                credential_hash=(
                    current_fingerprint
                ),
                auth_method=(
                    "password_passkey"
                ),
                mfa_completed=True,
                ttl_seconds=(
                    settings
                    .dashboard_auth_session_ttl_seconds
                ),
                client_ip=(
                    client_identifier
                ),
                user_agent=(
                    user_agent
                ),
                now=now,
            )
        )

        result = {
            "status":
                "authenticated",
            "token_type":
                "bearer",
            "access_token":
                token,
            "user":
                user.safe_dict(),
            "session":
                session,
            "passkey":
                passkey_result[
                    "credential"
                ],
        }

        db.commit()

        return result

    except LoginDenied:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def complete_mfa_login(
    *,
    challenge_token: str,
    method: str,
    code: str,
    settings: Settings,
    client_identifier: str | None = None,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Complete a password-authenticated MFA challenge atomically.

    Rate-limit reservation remains deliberately independent so a
    failed authentication attempt still consumes its limiter slot.

    Successful factor use, challenge consumption and Bearer-session
    issuance share one serialized database transaction.
    """

    normalized_method = (
        _normalize_mfa_method(
            method
        )
    )

    # Preflight read exists only to identify the username for the
    # persistent rate limiter. The challenge is re-read and validated
    # after BEGIN IMMEDIATE before any authentication state changes.
    preflight = (
        get_auth_challenge(
            challenge_token,
            purpose=(
                LOGIN_CHALLENGE_PURPOSE
            ),
            now=now,
        )
    )

    if preflight is None:
        raise LoginDenied(
            "Invalid or expired login challenge"
        )

    username = str(
        preflight.get(
            "username",
            "",
        )
    ).strip().lower()

    enforce_auth_rate_limit(
        settings=settings,
        username=username,
        action=MFA_LOGIN,
        client_identifier=(
            client_identifier
        ),
        challenge_token=(
            challenge_token
        ),
        now=now,
    )

    db = SessionLocal()

    try:
        # Serialize the whole MFA completion boundary on SQLite:
        # factor use + challenge consume + session issuance.
        if engine.dialect.name == "sqlite":
            db.execute(
                text(
                    "BEGIN IMMEDIATE"
                )
            )

        challenge = (
            get_auth_challenge_in_session(
                db,
                challenge_token,
                purpose=(
                    LOGIN_CHALLENGE_PURPOSE
                ),
                now=now,
            )
        )

        if challenge is None:
            db.rollback()

            raise LoginDenied(
                "Invalid or expired login challenge"
            )

        metadata = challenge.get(
            "metadata"
        )

        if not isinstance(
            metadata,
            dict,
        ):
            db.rollback()

            raise LoginDenied(
                "Invalid login challenge"
            )

        expected_fingerprint = str(
            metadata.get(
                "credential_fingerprint",
                "",
            )
        )

        allowed_methods = metadata.get(
            "allowed_methods"
        )

        if not isinstance(
            allowed_methods,
            list,
        ):
            db.rollback()

            raise LoginDenied(
                "Invalid login challenge"
            )

        if (
            normalized_method
            not in allowed_methods
        ):
            db.rollback()

            raise LoginDenied(
                "MFA method is not available "
                "for this challenge"
            )

        user = _enabled_file_user(
            username,
            settings=settings,
        )

        if user is None:
            consumed = (
                consume_auth_challenge_in_session(
                    db,
                    challenge_token,
                    purpose=(
                        LOGIN_CHALLENGE_PURPOSE
                    ),
                    now=now,
                )
            )

            if consumed is None:
                db.rollback()

                raise LoginDenied(
                    "Invalid login challenge"
                )

            # Preserve the existing fail-closed behavior: a challenge
            # belonging to an identity that is no longer enabled is
            # permanently invalidated.
            db.commit()

            raise LoginDenied(
                "Invalid login challenge"
            )

        current_fingerprint = (
            _fingerprint(
                user
            )
        )

        if not (
            expected_fingerprint
            and hmac.compare_digest(
                expected_fingerprint,
                current_fingerprint,
            )
        ):
            consumed = (
                consume_auth_challenge_in_session(
                    db,
                    challenge_token,
                    purpose=(
                        LOGIN_CHALLENGE_PURPOSE
                    ),
                    now=now,
                )
            )

            if consumed is None:
                db.rollback()

                raise LoginDenied(
                    "Login challenge is no longer valid"
                )

            # Password-record changes permanently invalidate the
            # password-bound challenge.
            db.commit()

            raise LoginDenied(
                "Login challenge is no longer valid"
            )

        # Do not consume a valid factor or parent challenge
        # when the current network is denied. The user may return
        # to an approved network and complete the same challenge.
        _require_ip_access(
            user=user,
            settings=settings,
            client_identifier=(
                client_identifier
            ),
        )

        if normalized_method == "totp":
            accepted = (
                verify_totp_for_user_in_session(
                    db,
                    username=(
                        user.username
                    ),
                    code=code,
                    settings=settings,
                    now=now,
                )
            )

            auth_method = (
                "password_totp"
            )

        else:
            accepted = (
                consume_recovery_code_in_session(
                    db,
                    username=(
                        user.username
                    ),
                    code=code,
                    now=now,
                )
            )

            auth_method = (
                "password_recovery"
            )

        if not accepted:
            db.rollback()

            raise LoginDenied(
                "Invalid MFA code"
            )

        consumed = (
            consume_auth_challenge_in_session(
                db,
                challenge_token,
                purpose=(
                    LOGIN_CHALLENGE_PURPOSE
                ),
                now=now,
            )
        )

        if consumed is None:
            db.rollback()

            raise LoginDenied(
                "Login challenge is no longer valid"
            )

        token, session = (
            create_auth_session_in_session(
                db,
                username=user.username,
                credential_hash=(
                    current_fingerprint
                ),
                auth_method=auth_method,
                mfa_completed=True,
                ttl_seconds=(
                    settings
                    .dashboard_auth_session_ttl_seconds
                ),
                client_ip=(
                    client_identifier
                ),
                user_agent=(
                    user_agent
                ),
                now=now,
            )
        )

        result = {
            "status":
                "authenticated",
            "token_type":
                "bearer",
            "access_token":
                token,
            "user":
                user.safe_dict(),
            "session":
                session,
        }

        db.commit()

        return result

    except LoginDenied:
        # Safe after either an active transaction rollback or one of
        # the deliberate fail-closed commits above.
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def resolve_bearer_session(
    token: str,
    *,
    settings: Settings,
    client_identifier: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """
    Resolve an opaque Bearer token against current identity
    state.

    Sessions fail closed when the user is disabled/deleted,
    the password record changes, or current MFA state requires
    a completed second factor.
    """

    session = get_auth_session(
        token,
        now=now,
    )

    if session is None:
        return None

    username = str(
        session.get(
            "username",
            "",
        )
    ).strip().lower()

    user = _enabled_file_user(
        username,
        settings=settings,
    )

    if user is None:
        revoke_auth_session(
            token,
            now=now,
        )
        return None

    current_fingerprint = (
        _fingerprint(
            user
        )
    )

    stored_fingerprint = str(
        session.get(
            "credential_fingerprint",
            "",
        )
    )

    if not (
        stored_fingerprint
        and hmac.compare_digest(
            stored_fingerprint,
            current_fingerprint,
        )
    ):
        revoke_auth_session(
            token,
            now=now,
        )
        return None

    factor = totp_status(
        user.username
    )

    passkey_required = False

    if (
        settings
        .dashboard_webauthn_enabled
    ):
        passkey_required = bool(
            passkey_status(
                user.username
            )[
                "available"
            ]
        )

    second_factor_required = bool(
        settings
        .dashboard_mfa_required
        or factor[
            "totp_enabled"
        ]
        or passkey_required
    )

    if (
        second_factor_required
        and not bool(
            session.get(
                "mfa_completed"
            )
        )
    ):
        revoke_auth_session(
            token,
            now=now,
        )
        return None

    # IP denial is deliberately non-destructive. The token
    # remains valid and may be used again from an approved network
    # or after administrator recovery disables the target policy.
    _require_ip_access(
        user=user,
        settings=settings,
        client_identifier=(
            client_identifier
        ),
    )

    touched_session = (
        touch_auth_session(
            token,
            now=now,
        )
    )

    if touched_session is None:
        return None

    return {
        "user":
            user,
        "session":
            touched_session,
    }
