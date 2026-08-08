#!/usr/bin/env python3
from __future__ import annotations

import json

from app.config import get_settings


def main() -> None:
    settings = get_settings()

    create_live = (
        settings.allow_bot_create
        and not settings.bot_create_simulation
    )

    stop_live = (
        settings.allow_bot_stop
        and not settings.bot_stop_simulation
    )

    armed = settings.bot_control_live_armed

    if not armed:
        risk_state = "DISARMED"

    elif create_live:
        risk_state = "LIVE_CREATE_ENABLED"

    elif stop_live:
        risk_state = "LIVE_STOP_ENABLED"

    else:
        risk_state = "ARMED_NO_LIVE_ACTION"

    result = {
        "risk_state": risk_state,
        "live_armed": armed,

        "live_accounts": sorted(
            settings.bot_control_live_account_list
        ),

        "create": {
            "allowed": settings.allow_bot_create,
            "simulation": (
                settings.bot_create_simulation
            ),
            "live": create_live,
            "live_confirmation": (
                settings
                .bot_control_live_create_confirmation_text
            ),
        },

        "stop": {
            "allowed": settings.allow_bot_stop,
            "simulation": (
                settings.bot_stop_simulation
            ),
            "live": stop_live,
            "live_confirmation": (
                settings
                .bot_control_live_stop_confirmation_text
            ),
        },

        "rate_limiting": (
            settings.bot_control_rate_limit_enabled
        ),

        "startup_recovery": (
            settings
            .bot_control_startup_recovery_enabled
        ),

        "permanent_market_restriction": False,
        "static_investment_cap": False,

        "investment_ceiling": (
            "available quote-currency balance"
        ),
    }

    print(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
