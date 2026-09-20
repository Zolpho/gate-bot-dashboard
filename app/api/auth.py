from __future__ import annotations

import base64
import io
from typing import Annotated, Any

import segno
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from ..account_action_policy import (
    CAPABILITIES,
    AccountActionPolicyError,
    list_account_action_policies,
    list_account_action_policy_events,
    update_account_action_policy,
)
from ..accounts import AccountConfigError, enabled_gate_accounts
from ..auth_login import (
    LoginDenied,
    MfaEnrollmentRequired,
    begin_passkey_mfa_login,
    begin_password_login,
    complete_mfa_login,
    complete_passkey_mfa_login,
)
from ..auth_mfa import (
    MfaAdminError,
    complete_totp_enrollment_with_recovery,
    reset_user_mfa,
)
from ..auth_passkey import (
    PasskeyConfigurationError,
    PasskeyStateError,
    PasskeyVerificationError,
    passkey_status,
    revoke_passkey_credential,
    set_passkey_enabled,
)
from ..auth_passkey_flow import (
    PASSKEY_REGISTRATION_PURPOSE,
    PasskeyChallengeError,
    begin_passkey_registration,
    complete_passkey_registration,
)
from ..auth_rate_limit import (
    SECURITY_REAUTH,
    AuthRateLimitExceeded,
    enforce_auth_rate_limit,
)
from ..auth_state import (
    AuthEncryptionKeyError,
    AuthStateError,
    get_auth_challenge,
    revoke_auth_session,
)
from ..auth_totp import (
    TotpEnrollmentError,
    TotpSecretError,
    begin_totp_enrollment,
    totp_status,
)
from ..bot_control import (
    BotControlConfigError,
    enabled_bot_control_accounts,
)
from ..config import Settings, get_settings
from ..security import (
    DashboardUser,
    PasswordChangeError,
    UserConfigError,
    change_dashboard_user_password,
    require_super_admin,
    require_user,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    username: str = Field(
        min_length=1,
        max_length=64,
    )

    password: str = Field(
        min_length=1,
        max_length=1024,
    )


class MfaLoginRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    challenge_token: str = Field(
        min_length=1,
        max_length=512,
    )

    method: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^(totp|recovery)$",
    )

    code: str = Field(
        min_length=1,
        max_length=128,
    )


class PasskeyLoginBeginRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    challenge_token: str = Field(
        min_length=1,
        max_length=512,
    )


class PasskeyLoginCompleteRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    challenge_token: str = Field(
        min_length=1,
        max_length=512,
    )

    passkey_challenge_token: str = Field(
        min_length=1,
        max_length=512,
    )

    credential: dict[str, Any]


class PasskeyRegistrationBeginRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    current_password: str = Field(
        min_length=1,
        max_length=1024,
    )


class PasskeyRegistrationCompleteRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    challenge_token: str = Field(
        min_length=1,
        max_length=512,
    )

    credential: dict[str, Any]

    label: str = Field(
        default="Passkey",
        min_length=1,
        max_length=128,
    )


class PasskeyEnabledRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    enabled: StrictBool

    current_password: str = Field(
        min_length=1,
        max_length=1024,
    )


class PasskeyRevokeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    credential_id: str = Field(
        min_length=1,
        max_length=2048,
    )

    current_password: str = Field(
        min_length=1,
        max_length=1024,
    )


class TotpEnrollmentRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    current_password: str = Field(
        min_length=1,
        max_length=1024,
    )


class TotpConfirmRequest(BaseModel):
    code: str = Field(
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
    )



class MfaResetRequest(BaseModel):
    reason: str = Field(
        min_length=1,
        max_length=1000,
    )


def _totp_qr_data_uri(
    provisioning_uri: str,
) -> str:
    output = io.BytesIO()

    qr = segno.make_qr(
        provisioning_uri,
        error="m",
    )

    qr.save(
        output,
        kind="png",
        scale=6,
        border=2,
    )

    encoded = base64.b64encode(
        output.getvalue()
    ).decode(
        "ascii"
    )

    return (
        "data:image/png;base64,"
        + encoded
    )


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)
    confirm_password: str = Field(min_length=12, max_length=1024)

    @model_validator(mode="after")
    def passwords_match(self) -> PasswordChangeRequest:
        if self.new_password != self.confirm_password:
            raise ValueError("New password and confirmation do not match")
        return self


class AccountActionPolicyUpdateRequest(BaseModel):
    transfers_enabled: StrictBool | None = None
    withdrawals_enabled: StrictBool | None = None
    trading_enabled: StrictBool | None = None
    reason: str = Field(
        default="",
        max_length=1000,
    )

    @model_validator(mode="after")
    def at_least_one_capability(
        self,
    ) -> AccountActionPolicyUpdateRequest:
        if (
            self.transfers_enabled is None
            and self.withdrawals_enabled is None
            and self.trading_enabled is None
        ):
            raise ValueError(
                "At least one account policy capability "
                "must be provided"
            )

        return self


def _policy_account_or_404(
    account_id: str,
) -> str:
    normalized = str(
        account_id or ""
    ).strip().lower()

    if not normalized:
        raise HTTPException(
            status_code=404,
            detail="Gate account not found",
        )

    known = {
        item["account_id"]
        for item in list_account_action_policies()
    }

    if normalized not in known:
        raise HTTPException(
            status_code=404,
            detail="Gate account not found",
        )

    return normalized


def _request_client_identifier(
    request: Request,
) -> str | None:
    """
    Return only Starlette's normalized socket/client identity.

    The application never parses X-Forwarded-For or X-Real-IP.
    Uvicorn may replace request.client only when the socket peer is
    inside its explicitly trusted proxy list.
    """

    client = request.client

    if client is None:
        return None

    value = str(
        client.host or ""
    ).strip()

    return value or None


def _request_bearer_token(
    request: Request,
) -> str | None:
    """
    Return the raw Bearer token from the current request only.

    The value is used solely to revoke the caller's own durable
    session. It is never persisted or returned to the client.
    """

    authorization = str(
        request.headers.get(
            "authorization",
            "",
        )
    ).strip()

    scheme, separator, token = (
        authorization.partition(
            " "
        )
    )

    if (
        not separator
        or scheme.lower()
        != "bearer"
    ):
        return None

    normalized = token.strip()

    return normalized or None


def _passkey_service_available(
    settings: Settings,
) -> bool:
    return bool(
        settings.dashboard_webauthn_enabled
        and str(
            settings.dashboard_webauthn_rp_id
            or ""
        ).strip()
        and str(
            settings.dashboard_webauthn_origin
            or ""
        ).strip()
        and str(
            settings.dashboard_webauthn_rp_name
            or ""
        ).strip()
    )


def _require_passkey_service(
    settings: Settings,
) -> None:
    if not _passkey_service_available(
        settings
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Passkey service is not available"
            ),
        )


def _confirm_current_password(
    user: DashboardUser,
    current_password: str,
    *,
    settings: Settings,
    client_identifier: str | None,
) -> None:
    try:
        enforce_auth_rate_limit(
            settings=settings,
            username=user.username,
            action=SECURITY_REAUTH,
            client_identifier=(
                client_identifier
            ),
        )

    except AuthRateLimitExceeded as exc:
        _raise_auth_rate_limit(
            exc
        )

    if (
        user.auth_source
        != "file"
        or not user.password_hash
        or not verify_password(
            current_password,
            user.password_hash,
        )
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Current password confirmation failed"
            ),
        )


def _raise_auth_rate_limit(
    exc: AuthRateLimitExceeded,
) -> None:
    raise HTTPException(
        status_code=429,
        detail=exc.detail(),
        headers={
            "Retry-After":
                str(
                    exc.retry_after_seconds
                ),
        },
    ) from exc


def _public_authenticated_login(
    result: dict,
    *,
    settings: Settings,
) -> dict:
    """
    Strip internal durable-session fields from a public response.
    """

    session = result[
        "session"
    ]

    return {
        "status":
            "authenticated",
        "token_type":
            "bearer",
        "access_token":
            result[
                "access_token"
            ],
        "user":
            result[
                "user"
            ],
        "session": {
            "auth_method":
                session[
                    "auth_method"
                ],
            "mfa_completed":
                bool(
                    session[
                        "mfa_completed"
                    ]
                ),
            "created_at":
                session[
                    "created_at"
                ],
            "expires_at":
                session[
                    "expires_at"
                ],
        },
        "mfa_required":
            settings
            .dashboard_mfa_required,
        "gate_write_performed":
            False,
    }


def _public_mfa_challenge(
    result: dict,
    *,
    settings: Settings,
) -> dict:
    """
    Return the opaque challenge without its durable metadata.
    """

    challenge = result[
        "challenge"
    ]

    return {
        "status":
            "mfa_required",
        "challenge_token":
            result[
                "challenge_token"
            ],
        "methods":
            result[
                "methods"
            ],
        "challenge_expires_at":
            challenge[
                "expires_at"
            ],
        "user":
            result[
                "user"
            ],
        "mfa_required":
            settings
            .dashboard_mfa_required,
        "gate_write_performed":
            False,
    }


@router.post("/login")
def password_login(
    request: Request,
    payload: LoginRequest,
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):  # type: ignore[no-untyped-def]
    """
    Password-first Bearer login.

    Client throttling uses request.client.host only. Forwarding-header
    trust belongs exclusively to the Uvicorn deployment boundary.
    """

    client_identifier = (
        _request_client_identifier(
            request
        )
    )

    try:
        result = begin_password_login(
            username=payload.username,
            password=payload.password,
            settings=settings,
            client_identifier=(
                client_identifier
            ),
        )

    except AuthRateLimitExceeded as exc:
        _raise_auth_rate_limit(
            exc
        )

    except MfaEnrollmentRequired as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc

    except LoginDenied as exc:
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid username or password"
            ),
        ) from exc

    except (
        AuthStateError,
        UserConfigError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Authentication service is "
                "not available"
            ),
        ) from exc

    status = result.get(
        "status"
    )

    if status == "mfa_required":
        return _public_mfa_challenge(
            result,
            settings=settings,
        )

    if status != "authenticated":
        raise HTTPException(
            status_code=503,
            detail=(
                "Authentication service returned "
                "an invalid state"
            ),
        )

    return _public_authenticated_login(
        result,
        settings=settings,
    )


@router.post("/login/mfa")
def mfa_login(
    request: Request,
    payload: MfaLoginRequest,
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):  # type: ignore[no-untyped-def]
    """
    Complete a password-authenticated MFA challenge.

    Username, challenge and real-client buckets are enforced by the
    durable authentication limiter.
    """

    client_identifier = (
        _request_client_identifier(
            request
        )
    )

    try:
        result = complete_mfa_login(
            challenge_token=(
                payload.challenge_token
            ),
            method=payload.method,
            code=payload.code,
            settings=settings,
            client_identifier=(
                client_identifier
            ),
        )

    except AuthRateLimitExceeded as exc:
        _raise_auth_rate_limit(
            exc
        )

    except LoginDenied as exc:
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid or expired MFA "
                "challenge or code"
            ),
        ) from exc

    except (
        AuthEncryptionKeyError,
        AuthStateError,
        TotpSecretError,
        UserConfigError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "MFA service is not available"
            ),
        ) from exc

    if (
        result.get(
            "status"
        )
        != "authenticated"
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Authentication service returned "
                "an invalid state"
            ),
        )

    return _public_authenticated_login(
        result,
        settings=settings,
    )


@router.post("/login/passkey")
def begin_passkey_login(
    payload: PasskeyLoginBeginRequest,
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):  # type: ignore[no-untyped-def]
    """
    Start the WebAuthn child challenge for an existing
    password-authenticated login challenge.

    The parent login challenge remains authoritative. Its raw token
    is never stored in the child challenge.
    """

    _require_passkey_service(
        settings
    )

    try:
        result = (
            begin_passkey_mfa_login(
                challenge_token=(
                    payload.challenge_token
                ),
                settings=settings,
            )
        )

    except LoginDenied as exc:
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid or expired passkey "
                "login challenge"
            ),
        ) from exc

    except PasskeyConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Passkey service is not available"
            ),
        ) from exc

    except (
        AuthStateError,
        UserConfigError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Authentication service is "
                "not available"
            ),
        ) from exc

    if (
        result.get(
            "status"
        )
        != "passkey_authentication_required"
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Authentication service returned "
                "an invalid state"
            ),
        )

    return {
        "status":
            result[
                "status"
            ],
        "challenge_token":
            result[
                "challenge_token"
            ],
        "challenge_expires_at":
            result[
                "challenge_expires_at"
            ],
        "options":
            result[
                "options"
            ],
        "gate_write_performed":
            False,
    }


@router.post("/login/passkey/complete")
def complete_passkey_login(
    request: Request,
    payload: PasskeyLoginCompleteRequest,
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):  # type: ignore[no-untyped-def]
    """
    Complete password + passkey authentication.

    Passkey verification, child challenge consumption, parent login
    challenge consumption and Bearer-session issuance are atomic in
    the login service. MFA attempt throttling uses the same durable
    limiter as TOTP/recovery completion.
    """

    _require_passkey_service(
        settings
    )

    client_identifier = (
        _request_client_identifier(
            request
        )
    )

    try:
        result = (
            complete_passkey_mfa_login(
                challenge_token=(
                    payload.challenge_token
                ),
                passkey_challenge_token=(
                    payload.passkey_challenge_token
                ),
                credential=(
                    payload.credential
                ),
                settings=settings,
                client_identifier=(
                    client_identifier
                ),
            )
        )

    except AuthRateLimitExceeded as exc:
        _raise_auth_rate_limit(
            exc
        )

    except (
        LoginDenied,
        PasskeyChallengeError,
        PasskeyStateError,
        PasskeyVerificationError,
    ) as exc:
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid or expired passkey "
                "challenge or credential"
            ),
        ) from exc

    except PasskeyConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Passkey service is not available"
            ),
        ) from exc

    except (
        AuthStateError,
        UserConfigError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Authentication service is "
                "not available"
            ),
        ) from exc

    if (
        result.get(
            "status"
        )
        != "authenticated"
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Authentication service returned "
                "an invalid state"
            ),
        )

    return _public_authenticated_login(
        result,
        settings=settings,
    )


@router.get("/me")
def current_user(user: Annotated[DashboardUser, Depends(require_user)]):  # type: ignore[no-untyped-def]
    return {"user": user.safe_dict()}


@router.post("/logout")
def logout_current_session(
    request: Request,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):  # type: ignore[no-untyped-def]
    """
    Revoke the caller's current Bearer session.

    Basic authentication remains available during migration, but
    Basic credentials do not represent a durable server session and
    therefore cannot be logged out through this endpoint.
    """

    token = _request_bearer_token(
        request
    )

    if token is None:
        raise HTTPException(
            status_code=400,
            detail="Bearer session required",
        )

    if not revoke_auth_session(
        token
    ):
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid or expired "
                "bearer token"
            ),
            headers={
                "WWW-Authenticate":
                    "Bearer",
            },
        )

    return {
        "status": "revoked",
        "user": user.safe_dict(),
        "gate_write_performed": False,
    }


@router.get("/capabilities")
def capabilities(
    user: Annotated[DashboardUser, Depends(require_user)],
):  # type: ignore[no-untyped-def]
    try:
        monitor_accounts = enabled_gate_accounts()
        control_accounts = enabled_bot_control_accounts()
    except (AccountConfigError, BotControlConfigError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Credential configuration error: {exc}",
        ) from exc

    control_ids = {
        account.id
        for account in control_accounts
    }

    visible_accounts = [
        account
        for account in monitor_accounts
        if (
            user.is_super_admin
            or user.can_manage(account.id)
        )
    ]

    settings = get_settings()

    account_capabilities = [
        {
            "account_id": account.id,
            "account_name": account.name,
            "monitor": True,
            "bot_control": account.id in control_ids,
            "bot_control_live": bool(
                account.id in control_ids
                and settings.bot_control_live_armed
                and settings.bot_control_live_account_allowed(
                    account.id
                )
            ),
            "treasury": False,
        }
        for account in visible_accounts
    ]

    return {
        "user": user.safe_dict(),
        "modes": {
            "monitor": bool(account_capabilities),
            "bot_control": any(
                item["bot_control"]
                for item in account_capabilities
            ),
            "treasury": False,
        },
        "accounts": account_capabilities,
    }


@router.get("/mfa/passkeys")
def current_passkey_status(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):  # type: ignore[no-untyped-def]
    """
    Return only the authenticated user's public passkey state.

    Credential public keys, user handles, challenge metadata and
    private authenticator material are never returned.
    """

    return {
        "factor":
            passkey_status(
                user.username
            ),
        "service_available":
            _passkey_service_available(
                settings
            ),
        "mfa_required":
            settings.dashboard_mfa_required,
        "gate_write_performed":
            False,
    }


@router.post("/mfa/passkeys/register")
def begin_current_user_passkey_registration(
    request: Request,
    payload: PasskeyRegistrationBeginRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):  # type: ignore[no-untyped-def]
    """
    Begin passkey registration for the authenticated user.

    A fresh current-password confirmation is required before the
    one-time WebAuthn registration challenge is issued.
    """

    _require_passkey_service(
        settings
    )

    _confirm_current_password(
        user,
        payload.current_password,
        settings=settings,
        client_identifier=(
            _request_client_identifier(
                request
            )
        ),
    )

    try:
        result = (
            begin_passkey_registration(
                username=user.username,
                settings=settings,
                display_name=(
                    user.username
                ),
            )
        )

    except PasskeyConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Passkey service is not available"
            ),
        ) from exc

    except (
        PasskeyChallengeError,
        PasskeyStateError,
    ) as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Passkey registration could not "
                "be started"
            ),
        ) from exc

    return {
        "status":
            result[
                "status"
            ],
        "challenge_token":
            result[
                "challenge_token"
            ],
        "challenge_expires_at":
            result[
                "challenge_expires_at"
            ],
        "options":
            result[
                "options"
            ],
        "gate_write_performed":
            False,
    }


@router.post(
    "/mfa/passkeys/register/complete"
)
def complete_current_user_passkey_registration(
    payload: PasskeyRegistrationCompleteRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):  # type: ignore[no-untyped-def]
    """
    Complete only the authenticated user's pending passkey
    registration.

    The registration challenge was created only after fresh password
    confirmation. The new credential remains disabled until a later
    explicit enable operation.
    """

    _require_passkey_service(
        settings
    )

    preflight = (
        get_auth_challenge(
            payload.challenge_token,
            purpose=(
                PASSKEY_REGISTRATION_PURPOSE
            ),
        )
    )

    if preflight is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid or expired passkey "
                "registration challenge"
            ),
        )

    challenge_username = str(
        preflight.get(
            "username",
            "",
        )
    ).strip().lower()

    if (
        challenge_username
        != user.username
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Passkey registration challenge "
                "does not belong to this user"
            ),
        )

    try:
        completed = (
            complete_passkey_registration(
                challenge_token=(
                    payload.challenge_token
                ),
                credential=(
                    payload.credential
                ),
                settings=settings,
                label=payload.label,
            )
        )

    except PasskeyConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Passkey service is not available"
            ),
        ) from exc

    except (
        PasskeyChallengeError,
        PasskeyStateError,
        PasskeyVerificationError,
    ) as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Passkey registration could not "
                "be completed"
            ),
        ) from exc

    return {
        "status":
            "registered",
        "credential":
            completed[
                "credential"
            ],
        "factor":
            passkey_status(
                user.username
            ),
        "gate_write_performed":
            False,
    }


@router.post("/mfa/passkeys/enabled")
def set_current_user_passkey_enabled(
    request: Request,
    payload: PasskeyEnabledRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):  # type: ignore[no-untyped-def]
    """
    Enable or disable passkey MFA for the authenticated user.

    Enabling requires an operational WebAuthn configuration and at
    least one active registered credential. Disabling remains
    available if the rollout gate is later turned off.
    """

    _confirm_current_password(
        user,
        payload.current_password,
        settings=settings,
        client_identifier=(
            _request_client_identifier(
                request
            )
        ),
    )

    if payload.enabled:
        _require_passkey_service(
            settings
        )

    current = (
        passkey_status(
            user.username
        )
    )

    if (
        not payload.enabled
        and settings.dashboard_mfa_required
        and current[
            "enabled"
        ]
        and not totp_status(
            user.username
        )[
            "totp_enabled"
        ]
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot disable the only enabled "
                "MFA factor while MFA is required"
            ),
        )

    try:
        factor = (
            set_passkey_enabled(
                user.username,
                bool(
                    payload.enabled
                ),
            )
        )

    except PasskeyStateError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(
                exc
            ),
        ) from exc

    return {
        "status": (
            "enabled"
            if factor[
                "enabled"
            ]
            else "disabled"
        ),
        "factor":
            factor,
        "gate_write_performed":
            False,
    }


@router.post("/mfa/passkeys/revoke")
def revoke_current_user_passkey(
    request: Request,
    payload: PasskeyRevokeRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):  # type: ignore[no-untyped-def]
    """
    Soft-revoke one active credential belonging to the
    authenticated user.

    Removing the final active credential automatically disables the
    user's passkey factor. The last required factor is protected when
    global MFA enforcement is active.
    """

    _confirm_current_password(
        user,
        payload.current_password,
        settings=settings,
        client_identifier=(
            _request_client_identifier(
                request
            )
        ),
    )

    current = (
        passkey_status(
            user.username
        )
    )

    target_exists = any(
        str(
            credential.get(
                "credential_id",
                "",
            )
        )
        == payload.credential_id
        for credential
        in current[
            "credentials"
        ]
    )

    if not target_exists:
        raise HTTPException(
            status_code=404,
            detail=(
                "Passkey credential not found"
            ),
        )

    if (
        settings.dashboard_mfa_required
        and current[
            "enabled"
        ]
        and current[
            "credential_count"
        ]
        <= 1
        and not totp_status(
            user.username
        )[
            "totp_enabled"
        ]
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot revoke the only enabled "
                "MFA factor while MFA is required"
            ),
        )

    try:
        revoked = (
            revoke_passkey_credential(
                user.username,
                payload.credential_id,
            )
        )

    except PasskeyVerificationError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid passkey credential ID"
            ),
        ) from exc

    if not revoked:
        raise HTTPException(
            status_code=404,
            detail=(
                "Passkey credential not found"
            ),
        )

    return {
        "status":
            "revoked",
        "factor":
            passkey_status(
                user.username
            ),
        "gate_write_performed":
            False,
    }


@router.get("/mfa/totp")
def current_totp_status(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):  # type: ignore[no-untyped-def]
    """
    Read only the authenticated user's TOTP state.

    No secret or ciphertext is returned.
    MFA enforcement remains independently disabled until
    the later rollout phase.
    """

    return {
        "factor": totp_status(
            user.username
        ),
        "mfa_required": (
            settings.dashboard_mfa_required
        ),
        "gate_write_performed": False,
    }


@router.post("/mfa/totp/enroll")
def enroll_totp(
    request: Request,
    payload: TotpEnrollmentRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):  # type: ignore[no-untyped-def]
    """
    Begin TOTP enrollment for the authenticated user only.

    Fresh current-password confirmation is required before
    a new authenticator secret is generated. The plaintext
    seed is returned only as part of this enrollment response.
    Durable state stores ciphertext.
    """

    _confirm_current_password(
        user,
        payload.current_password,
        settings=settings,
        client_identifier=(
            _request_client_identifier(
                request
            )
        ),
    )

    try:
        enrollment = (
            begin_totp_enrollment(
                username=user.username,
                settings=settings,
            )
        )
    except TotpEnrollmentError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except (
        AuthEncryptionKeyError,
        TotpSecretError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "TOTP service is not available"
            ),
        ) from exc

    return {
        "status": "pending",
        "secret": enrollment[
            "secret"
        ],
        "provisioning_uri": enrollment[
            "provisioning_uri"
        ],
        "qr_data_uri": (
            _totp_qr_data_uri(
                enrollment[
                    "provisioning_uri"
                ]
            )
        ),
        "factor": enrollment[
            "factor"
        ],
        "mfa_required": (
            settings.dashboard_mfa_required
        ),
        "gate_write_performed": False,
    }


@router.post("/mfa/totp/confirm")
def confirm_totp(
    payload: TotpConfirmRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):  # type: ignore[no-untyped-def]
    """
    Atomically confirm the authenticated user's pending TOTP
    enrollment and create a fresh recovery-code set.

    Recovery codes are returned only in this successful
    confirmation response. Durable storage contains hashes.
    """

    try:
        completed = (
            complete_totp_enrollment_with_recovery(
                username=user.username,
                code=payload.code,
                settings=settings,
            )
        )
    except TotpEnrollmentError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except (
        AuthEncryptionKeyError,
        TotpSecretError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "TOTP service is not available"
            ),
        ) from exc

    if completed is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid TOTP code",
        )

    return {
        "status": "enabled",
        "factor": totp_status(
            user.username
        ),
        "recovery_codes": (
            completed[
                "recovery_codes"
            ]
        ),
        "recovery_code_count": (
            completed[
                "recovery_code_count"
            ]
        ),
        "mfa_required": (
            settings.dashboard_mfa_required
        ),
        "gate_write_performed": False,
    }


@router.post(
    "/mfa/users/{target_username}/reset"
)
def administrator_reset_mfa(
    target_username: str,
    payload: MfaResetRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_super_admin),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):  # type: ignore[no-untyped-def]
    """
    Reset one file-backed dashboard user's MFA state.

    This is local authentication state only. It never performs
    a Gate operation.
    """

    try:
        result = reset_user_mfa(
            actor_username=user.username,
            target_username=(
                target_username
            ),
            reason=payload.reason,
            settings=settings,
        )
    except MfaAdminError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except UserConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    return {
        **result,
        "gate_write_performed": False,
    }


@router.post("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    user: Annotated[DashboardUser, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):  # type: ignore[no-untyped-def]
    try:
        change_dashboard_user_password(
            user,
            payload.current_password,
            payload.new_password,
            settings=settings,
        )
    except PasswordChangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "changed",
        "message": "Password changed successfully",
        "user": user.safe_dict(),
    }

@router.get("/account-policies")
def account_action_policies(
    user: Annotated[
        DashboardUser,
        Depends(require_super_admin),
    ],
):  # type: ignore[no-untyped-def]
    """
    Rootadmin read model for all Wallet-account policies.

    This is local authorization state only. Reading it never
    performs a Gate write.
    """

    return {
        "capabilities": list(CAPABILITIES),
        "items": list_account_action_policies(),
        "gate_write_performed": False,
    }


@router.get(
    "/account-policies/{account_id}/events"
)
def account_action_policy_history(
    account_id: str,
    user: Annotated[
        DashboardUser,
        Depends(require_super_admin),
    ],
    limit: int = Query(
        default=200,
        ge=1,
        le=1000,
    ),
):  # type: ignore[no-untyped-def]
    """
    Rootadmin-only immutable policy history.
    """

    normalized = _policy_account_or_404(
        account_id
    )

    return {
        "account_id": normalized,
        "items": (
            list_account_action_policy_events(
                normalized,
                limit=limit,
            )
        ),
        "limit": limit,
        "gate_write_performed": False,
    }


@router.patch(
    "/account-policies/{account_id}"
)
def change_account_action_policy(
    account_id: str,
    payload: AccountActionPolicyUpdateRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_super_admin),
    ],
):  # type: ignore[no-untyped-def]
    """
    Rootadmin-only local policy mutation.

    This changes durable dashboard authorization state only.
    It does not call Gate and does not itself enable any Gate
    write.
    """

    normalized = _policy_account_or_404(
        account_id
    )

    try:
        result = update_account_action_policy(
            normalized,
            username=user.username,
            transfers_enabled=(
                payload.transfers_enabled
            ),
            withdrawals_enabled=(
                payload.withdrawals_enabled
            ),
            trading_enabled=(
                payload.trading_enabled
            ),
            reason=payload.reason.strip(),
            metadata={
                "source": "rootadmin_policy_api",
                "auth_source": user.auth_source,
            },
        )
    except AccountActionPolicyError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "status": (
            "updated"
            if result["changed"]
            else "unchanged"
        ),
        **result,
        "gate_write_performed": False,
    }
