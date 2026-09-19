from __future__ import annotations

import base64
import io
from typing import Annotated

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
    begin_password_login,
    complete_mfa_login,
)
from ..auth_mfa import (
    MfaAdminError,
    complete_totp_enrollment_with_recovery,
    reset_user_mfa,
)
from ..auth_rate_limit import AuthRateLimitExceeded
from ..auth_state import AuthEncryptionKeyError, AuthStateError
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


@router.get("/me")
def current_user(user: Annotated[DashboardUser, Depends(require_user)]):  # type: ignore[no-untyped-def]
    return {"user": user.safe_dict()}


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

    The plaintext seed is returned only as part of this
    enrollment response. Durable state stores ciphertext.
    """

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
