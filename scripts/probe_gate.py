#!/usr/bin/env python3
"""Probe every configured Gate account without modifying any strategy."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.accounts import AccountConfigError, enabled_gate_accounts
from app.config import get_settings
from app.gate_client import GateAPIError, GateClient


async def probe_account(account, settings) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    output: dict[str, Any] = {
        "account": account.safe_dict(),
        "server_time": None,
        "running": None,
        "first_detail": None,
        "errors": [],
    }
    async with GateClient(settings, account) as client:
        try:
            output["server_time"] = await client.server_time()
        except GateAPIError as exc:
            output["errors"].append({"endpoint": "/spot/time", "error": str(exc)})
        try:
            items, pages = await client.list_all_running_bots()
            output["running"] = {"items": items, "pages": pages, "count": len(items)}
            if items:
                first = items[0]
                detail = await client.get_bot_detail(
                    str(first.get("strategy_id", "")),
                    str(first.get("strategy_type", "")),
                )
                output["first_detail"] = detail.raw
        except GateAPIError as exc:
            output["errors"].append(
                {
                    "endpoint": "/bot/portfolio/*",
                    "error": str(exc),
                    "response": exc.response,
                }
            )
    return output


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", action="append", default=[], help="Probe only this account ID; repeatable")
    parser.add_argument("--output", default="gate_probe_output.json")
    args = parser.parse_args()

    settings = get_settings()
    try:
        accounts = enabled_gate_accounts()
    except AccountConfigError as exc:
        print(f"Gate account configuration error: {exc}")
        return 2

    requested = {value.strip().lower() for value in args.account if value.strip()}
    if requested:
        accounts = tuple(account for account in accounts if account.id in requested)
        missing = sorted(requested - {account.id for account in accounts})
        if missing:
            print(f"Unknown, disabled, or unconfigured account(s): {', '.join(missing)}")
            return 2

    if not accounts:
        print(
            "No enabled Gate accounts found. Create secrets/gate_accounts.json "
            "or configure the legacy GATE_API_KEY and GATE_API_SECRET values."
        )
        return 2

    results = list(await asyncio.gather(*(probe_account(account, settings) for account in accounts)))
    output = {
        "account_count": len(results),
        "accounts": results,
        "error_count": sum(len(item["errors"]) for item in results),
    }
    path = Path(args.output)
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print(f"Probe finished. Wrote {path.resolve()}")
    for item in results:
        account = item["account"]
        running = item.get("running") or {}
        print(
            f"- {account['id']}: {running.get('count', 0)} running bots, "
            f"{len(item['errors'])} errors"
        )
        for error in item["errors"]:
            print(f"  {error['endpoint']}: {error['error']}")
    return 1 if output["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
