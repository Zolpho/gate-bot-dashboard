from __future__ import annotations

from datetime import timedelta
from typing import Any

from .accounts import GateAccountConfig
from .bot_adapter import (
    decimal_or_none,
    normalize_status,
    parse_datetime,
)
from .config import Settings
from .gate_client import (
    GateAPIError,
    GateClient,
)


def _safe_strategy_id(
    record: dict[str, Any],
) -> str:
    direct = str(
        record.get("strategy_id")
        or ""
    ).strip()

    if direct:
        return direct

    response = (
        record.get("response")
        or {}
    )

    strategy = (
        response.get("strategy")
        if isinstance(response, dict)
        else {}
    )

    if isinstance(strategy, dict):
        return str(
            strategy.get("strategy_id")
            or ""
        ).strip()

    return ""


def _gate_payload(
    record: dict[str, Any],
) -> dict[str, Any]:
    request = (
        record.get("request")
        or {}
    )

    if not isinstance(request, dict):
        return {}

    payload = request.get(
        "gate_payload"
    )

    return (
        payload
        if isinstance(payload, dict)
        else {}
    )


def match_spot_grid_candidates(
    record: dict[str, Any],
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payload = _gate_payload(record)

    market = str(
        payload.get("market")
        or ""
    ).upper()

    strategy_type = str(
        payload.get("strategy_type")
        or "spot_grid"
    )

    params = (
        payload.get("create_params")
        or {}
    )

    expected_money = decimal_or_none(
        params.get("money")
        if isinstance(params, dict)
        else None
    )

    request_time = parse_datetime(
        record.get("created_at")
    )

    matches: list[
        dict[str, Any]
    ] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        if (
            str(
                item.get("market")
                or ""
            ).upper()
            != market
        ):
            continue

        if (
            str(
                item.get("strategy_type")
                or ""
            )
            != strategy_type
        ):
            continue

        candidate_money = (
            decimal_or_none(
                item.get("invest_amount")
            )
        )

        if (
            expected_money is not None
            and candidate_money
            != expected_money
        ):
            continue

        candidate_time = parse_datetime(
            item.get("created_at")
        )

        time_match = None

        if (
            request_time is not None
            and candidate_time is not None
        ):
            earliest = (
                request_time
                - timedelta(seconds=90)
            )

            latest = (
                request_time
                + timedelta(minutes=10)
            )

            time_match = (
                earliest
                <= candidate_time
                <= latest
            )

            if not time_match:
                continue

        matches.append({
            "strategy_id": str(
                item.get("strategy_id")
                or ""
            ),
            "strategy_type": str(
                item.get("strategy_type")
                or ""
            ),
            "strategy_name": str(
                item.get("strategy_name")
                or ""
            ),
            "market": str(
                item.get("market")
                or ""
            ),
            "status": str(
                item.get("status")
                or ""
            ),
            "invest_amount": (
                str(candidate_money)
                if candidate_money
                is not None
                else None
            ),
            "created_at": (
                candidate_time.isoformat()
                if candidate_time
                else None
            ),
            "time_match": time_match,
        })

    return matches


def classify_stop_status(
    status: str,
) -> tuple[str, str, str]:
    raw = str(
        status or ""
    ).strip()

    lowered = raw.lower()

    if lowered == "stopping":
        return (
            "stop_in_progress",
            "high",
            (
                "Gate currently reports the strategy "
                "as stopping."
            ),
        )

    normalized = normalize_status(
        raw
    )

    if normalized == "stopped":
        return (
            "confirmed_stopped",
            "definitive",
            (
                "Gate currently reports the strategy "
                "as stopped."
            ),
        )

    if normalized == "running":
        return (
            "observed_running",
            "high",
            (
                "Gate currently reports the strategy "
                "as running. Do not automatically "
                "retry the Stop operation."
            ),
        )

    return (
        "observed_status",
        "high",
        (
            "Gate currently reports strategy status "
            f"'{raw or 'unknown'}'. Manual review "
            "is required."
        ),
    )


async def _running_candidates(
    *,
    client: GateClient,
    strategy_type: str,
    market: str,
    max_pages: int = 5,
) -> list[dict[str, Any]]:
    result: list[
        dict[str, Any]
    ] = []

    for page in range(
        1,
        max_pages + 1,
    ):
        response = (
            await client.list_running_bots(
                strategy_type=strategy_type,
                market=market,
                page=page,
                page_size=50,
            )
        )

        data = (
            response.data
            if isinstance(
                response.data,
                dict,
            )
            else {}
        )

        items = (
            data.get("items")
            if isinstance(data, dict)
            else []
        )

        if not isinstance(
            items,
            list,
        ):
            items = []

        result.extend(
            item
            for item in items
            if isinstance(item, dict)
        )

        total = data.get(
            "total",
            len(result),
        )

        try:
            total = int(total)
        except (
            TypeError,
            ValueError,
        ):
            total = len(result)

        if (
            not items
            or len(result) >= total
            or len(items) < 50
        ):
            break

    return result


async def reconcile_request_against_gate(
    *,
    record: dict[str, Any],
    monitor_account: GateAccountConfig,
    settings: Settings,
) -> dict[str, Any]:
    action = str(
        record.get("action")
        or ""
    )

    response = (
        record.get("response")
        or {}
    )

    status = str(
        record.get("status")
        or ""
    )

    # Simulation never reached Gate's write endpoint.
    if (
        status == "simulated"
        or (
            isinstance(response, dict)
            and response.get(
                "simulation"
            )
        )
    ):
        return {
            "outcome": "not_applicable",
            "confidence": "definitive",
            "strategy_id": (
                _safe_strategy_id(
                    record
                )
            ),
            "gate_status": "",
            "summary": (
                "This was a simulation. The write "
                "path returned before a Gate Create "
                "or Stop request was sent."
            ),
            "gate_read_performed": False,
            "gate_write_performed": False,
            "retry_advice": "not_applicable",
            "details": {},
        }

    # Explicit Gate rejection is already terminal.
    if status == "rejected":
        return {
            "outcome": "already_rejected",
            "confidence": "definitive",
            "strategy_id": (
                _safe_strategy_id(
                    record
                )
            ),
            "gate_status": "",
            "summary": (
                "The original operation already "
                "contains an explicit Gate rejection."
            ),
            "gate_read_performed": False,
            "gate_write_performed": False,
            "retry_advice": "manual_review",
            "details": {
                "original_error": (
                    record.get("error")
                    or ""
                ),
                "gate_status_code": (
                    record.get(
                        "gate_status_code"
                    )
                ),
                "gate_label": (
                    record.get(
                        "gate_label"
                    )
                ),
            },
        }

    payload = _gate_payload(
        record
    )

    strategy_type = str(
        payload.get("strategy_type")
        or "spot_grid"
    )

    market = str(
        payload.get("market")
        or ""
    ).upper()

    strategy_id = _safe_strategy_id(
        record
    )

    try:
        async with GateClient(
            settings,
            monitor_account,
        ) as client:

            if action == "spot_grid_create":
                if strategy_id:
                    detail_response = (
                        await client.get_bot_detail(
                            strategy_id,
                            strategy_type,
                        )
                    )

                    detail = (
                        detail_response.data
                        if isinstance(
                            detail_response.data,
                            dict,
                        )
                        else {}
                    )

                    gate_status = str(
                        detail.get("status")
                        or ""
                    )

                    return {
                        "outcome": (
                            "confirmed_created"
                        ),
                        "confidence": (
                            "definitive"
                        ),
                        "strategy_id": (
                            strategy_id
                        ),
                        "gate_status": (
                            gate_status
                        ),
                        "summary": (
                            "Gate returned strategy "
                            "details for the recorded "
                            "strategy ID."
                        ),
                        "gate_read_performed": True,
                        "gate_write_performed": False,
                        "retry_advice": (
                            "do_not_retry"
                        ),
                        "details": {
                            "gate_detail": detail,
                        },
                    }

                items = (
                    await _running_candidates(
                        client=client,
                        strategy_type=(
                            strategy_type
                        ),
                        market=market,
                    )
                )

                candidates = (
                    match_spot_grid_candidates(
                        record,
                        items,
                    )
                )

                if len(candidates) == 1:
                    candidate = (
                        candidates[0]
                    )

                    confidence = (
                        "high"
                        if candidate.get(
                            "time_match"
                        ) is True
                        else "medium"
                    )

                    return {
                        "outcome": (
                            "probable_created"
                        ),
                        "confidence": (
                            confidence
                        ),
                        "strategy_id": (
                            candidate.get(
                                "strategy_id"
                            )
                            or ""
                        ),
                        "gate_status": (
                            candidate.get(
                                "status"
                            )
                            or ""
                        ),
                        "summary": (
                            "Exactly one running Gate "
                            "strategy matches the market, "
                            "investment and available "
                            "creation-time evidence. "
                            "Because the original response "
                            "did not contain a strategy "
                            "ID, this remains a probable "
                            "rather than definitive match."
                        ),
                        "gate_read_performed": True,
                        "gate_write_performed": False,
                        "retry_advice": (
                            "do_not_retry"
                        ),
                        "details": {
                            "candidates": (
                                candidates
                            ),
                        },
                    }

                if len(candidates) > 1:
                    return {
                        "outcome": "ambiguous",
                        "confidence": "low",
                        "strategy_id": "",
                        "gate_status": "",
                        "summary": (
                            "Multiple running Gate "
                            "strategies match the original "
                            "Create request. No automatic "
                            "conclusion is safe."
                        ),
                        "gate_read_performed": True,
                        "gate_write_performed": False,
                        "retry_advice": (
                            "manual_review"
                        ),
                        "details": {
                            "candidates": candidates,
                        },
                    }

                return {
                    "outcome": "not_found",
                    "confidence": (
                        "inconclusive"
                    ),
                    "strategy_id": "",
                    "gate_status": "",
                    "summary": (
                        "No matching running Gate "
                        "strategy was found. This does "
                        "NOT prove that the original "
                        "Create request failed; the "
                        "strategy may no longer appear "
                        "in the running portfolio."
                    ),
                    "gate_read_performed": True,
                    "gate_write_performed": False,
                    "retry_advice": (
                        "manual_review"
                    ),
                    "details": {
                        "candidate_count": 0,
                    },
                }

            if action == "bot_stop":
                if not strategy_id:
                    strategy_id = str(
                        payload.get(
                            "strategy_id"
                        )
                        or ""
                    )

                if not strategy_id:
                    return {
                        "outcome": (
                            "inconclusive"
                        ),
                        "confidence": (
                            "inconclusive"
                        ),
                        "strategy_id": "",
                        "gate_status": "",
                        "summary": (
                            "The Stop audit record does "
                            "not contain a strategy ID."
                        ),
                        "gate_read_performed": False,
                        "gate_write_performed": False,
                        "retry_advice": (
                            "manual_review"
                        ),
                        "details": {},
                    }

                detail_response = (
                    await client.get_bot_detail(
                        strategy_id,
                        strategy_type,
                    )
                )

                detail = (
                    detail_response.data
                    if isinstance(
                        detail_response.data,
                        dict,
                    )
                    else {}
                )

                gate_status = str(
                    detail.get("status")
                    or ""
                )

                (
                    outcome,
                    confidence,
                    summary,
                ) = classify_stop_status(
                    gate_status
                )

                return {
                    "outcome": outcome,
                    "confidence": confidence,
                    "strategy_id": (
                        strategy_id
                    ),
                    "gate_status": (
                        gate_status
                    ),
                    "summary": summary,
                    "gate_read_performed": True,
                    "gate_write_performed": False,
                    "retry_advice": (
                        "do_not_retry"
                        if outcome in {
                            "confirmed_stopped",
                            "stop_in_progress",
                        }
                        else "manual_review"
                    ),
                    "details": {
                        "gate_detail": detail,
                    },
                }

            return {
                "outcome": "unsupported_action",
                "confidence": "inconclusive",
                "strategy_id": strategy_id,
                "gate_status": "",
                "summary": (
                    "This Bot Control action does not "
                    "have a reconciliation handler."
                ),
                "gate_read_performed": False,
                "gate_write_performed": False,
                "retry_advice": "manual_review",
                "details": {},
            }

    except GateAPIError as exc:
        return {
            "outcome": "inconclusive",
            "confidence": "inconclusive",
            "strategy_id": strategy_id,
            "gate_status": "",
            "summary": (
                "The read-only Gate reconciliation "
                "request failed. The original operation "
                "must remain unresolved."
            ),
            "gate_read_performed": True,
            "gate_write_performed": False,
            "retry_advice": "manual_review",
            "details": {
                "gate_error": str(exc),
                "gate_status_code": (
                    exc.status_code
                ),
                "gate_label": exc.label,
                "gate_response": (
                    exc.response
                ),
            },
        }
