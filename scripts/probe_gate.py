#!/usr/bin/env python3
"""Probe Gate's native bot endpoints without modifying any strategy."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.config import get_settings
from app.gate_client import GateAPIError, GateClient


async def main() -> int:
    settings = get_settings()
    if not settings.gate_configured:
        print("Set GATE_API_KEY and GATE_API_SECRET in .env before running this probe.")
        return 2

    output: dict = {"server_time": None, "running": None, "first_detail": None, "errors": []}
    async with GateClient(settings) as client:
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
                    str(first.get("strategy_id", "")), str(first.get("strategy_type", ""))
                )
                output["first_detail"] = detail.raw
        except GateAPIError as exc:
            output["errors"].append({"endpoint": "/bot/portfolio/*", "error": str(exc), "response": exc.response})

    path = Path("gate_probe_output.json")
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"Probe finished. Wrote {path.resolve()}")
    print(f"Running bots found: {output.get('running', {}).get('count', 0) if output.get('running') else 0}")
    if output["errors"]:
        print("Errors:")
        for error in output["errors"]:
            print(f"- {error['endpoint']}: {error['error']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
