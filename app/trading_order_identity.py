from __future__ import annotations

import hashlib
import re


GATE_TEXT_PATTERN = re.compile(
    r"^t-[0-9A-Za-z_.-]+$"
)


def gate_text_for_request_id(
    request_id: str,
) -> str:
    """
    Build a deterministic Gate Spot custom order ID.

    Gate requires:
    - t- prefix
    - <= 28 bytes after t-
    - only 0-9 A-Z a-z _ - .

    We hash the dashboard request ID so arbitrary client
    request IDs can never violate Gate's character rules.
    """
    normalized = request_id.strip()

    if not normalized:
        raise ValueError(
            "request_id cannot be empty"
        )

    digest = hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()[:25]

    value = f"t-eq-{digest}"

    if len(
        value[2:].encode("utf-8")
    ) > 28:
        raise RuntimeError(
            "Generated Gate text exceeds "
            "the documented limit"
        )

    if not GATE_TEXT_PATTERN.fullmatch(
        value
    ):
        raise RuntimeError(
            "Generated Gate text contains "
            "invalid characters"
        )

    return value
