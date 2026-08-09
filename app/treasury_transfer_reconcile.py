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


@dataclass(frozen=True)
class TransferSubmissionErrorDecision:
    request_status: str
    definitive: bool
    release_lock: bool
    summary: str


def interpret_transfer_submission_error(
    status_code: int | None,
) -> TransferSubmissionErrorDecision:
    # An explicit 4xx Gate response means Gate rejected
    # the submitted request. Network failures and 5xx
    # outcomes stay uncertain because the transfer may
    # have reached Gate before the failure was observed.
    if (
        status_code is not None
        and 400 <= status_code < 500
    ):
        return TransferSubmissionErrorDecision(
            request_status="rejected",
            definitive=True,
            release_lock=True,
            summary=(
                "Gate explicitly rejected the Treasury "
                "transfer request."
            ),
        )

    return TransferSubmissionErrorDecision(
        request_status="uncertain",
        definitive=False,
        release_lock=False,
        summary=(
            "Treasury transfer submission outcome is "
            "uncertain. Do not retry automatically."
        ),
    )


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
