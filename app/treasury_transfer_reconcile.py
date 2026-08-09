from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TransferStatusDecision:
    outcome: str
    request_status: str
    confidence: str
    gate_status: str
    tx_id: str
    terminal: bool
    release_lock: bool
    summary: str


def interpret_transfer_order_status(
    payload: Any,
) -> TransferStatusDecision:
    data = (
        payload
        if isinstance(payload, dict)
        else {}
    )

    gate_status = str(
        data.get("status") or ""
    ).strip().upper()

    tx_id = str(
        data.get("tx_id") or ""
    ).strip()

    if gate_status == "SUCCESS":
        return TransferStatusDecision(
            outcome="success",
            request_status="success",
            confidence="definitive",
            gate_status=gate_status,
            tx_id=tx_id,
            terminal=True,
            release_lock=True,
            summary=(
                "Gate confirmed Treasury transfer "
                "success."
            ),
        )

    if gate_status == "FAIL":
        return TransferStatusDecision(
            outcome="failed",
            request_status="failed",
            confidence="definitive",
            gate_status=gate_status,
            tx_id=tx_id,
            terminal=True,
            release_lock=True,
            summary=(
                "Gate confirmed Treasury transfer "
                "failure."
            ),
        )

    if gate_status == "PENDING":
        return TransferStatusDecision(
            outcome="pending",
            request_status="pending",
            confidence="provisional",
            gate_status=gate_status,
            tx_id=tx_id,
            terminal=False,
            release_lock=False,
            summary=(
                "Gate reports Treasury transfer "
                "still processing."
            ),
        )

    if gate_status == "PARTIAL_SUCCESS":
        # Gate documents this for sub-to-sub transfers rather
        # than our main/sub path. Treat it as an attention
        # condition and never release the lock automatically.
        return TransferStatusDecision(
            outcome="partial_success",
            request_status="attention",
            confidence="definitive",
            gate_status=gate_status,
            tx_id=tx_id,
            terminal=False,
            release_lock=False,
            summary=(
                "Gate reported PARTIAL_SUCCESS. "
                "Manual Treasury review is required."
            ),
        )

    return TransferStatusDecision(
        outcome="unknown",
        request_status="uncertain",
        confidence="inconclusive",
        gate_status=gate_status,
        tx_id=tx_id,
        terminal=False,
        release_lock=False,
        summary=(
            "Gate transfer status could not be "
            "classified. The Treasury lock remains held."
        ),
    )
