from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from .demo_auth import DEMO_ACCOUNT_IDS
from .demo_withdrawal import DemoWithdrawalStore
from .demo_withdrawal_flow import DemoWithdrawalFlowStore
from .demo_withdrawal_lifecycle import (
    DemoWithdrawalLifecycleStore,
    demo_withdrawal_confirmation_text,
    demo_withdrawal_execution_confirmation_text,
    demo_withdrawal_jit_execution_confirmation_text,
    demo_withdrawal_jit_preparation_confirmation_text,
    demo_withdrawal_reservation_confirmation_text,
)


class DemoWithdrawalAuthorizationError(
    PermissionError
):
    """Demo withdrawal access escaped the authenticated Wallet scope."""


def _normalize_account_id(
    value: str,
) -> str:
    account_id = str(
        value or ""
    ).strip().lower()

    if account_id not in DEMO_ACCOUNT_IDS:
        raise DemoWithdrawalAuthorizationError(
            "Unknown Demo Wallet account"
        )

    return account_id


def _account_scope(
    account_ids: set[str],
) -> set[str]:
    return {
        _normalize_account_id(
            item
        )
        for item
        in account_ids
    }


class DemoWithdrawalApi:
    """
    Pure response-contract adapter for isolated Demo withdrawals.

    This class deliberately contains no FastAPI, Gate, Treasury,
    production repository, application Settings, or credential
    dependency. Route handlers can later branch to it before any
    production-side withdrawal service is reached.
    """

    def __init__(
        self,
        database_path: Path,
    ) -> None:
        path = Path(
            database_path
        )

        self.registry = DemoWithdrawalStore(
            path
        )

        self.flow = DemoWithdrawalFlowStore(
            path
        )

        self.lifecycle = DemoWithdrawalLifecycleStore(
            path
        )

    @staticmethod
    def _base() -> dict[str, Any]:
        return {
            "source":
                "demo",
            "simulation":
                True,
            "gate_read_performed":
                False,
            "gate_write_performed":
                False,
            "withdrawals_enabled":
                False,
            "demo_withdrawals_enabled":
                True,
        }

    @staticmethod
    def _require_account(
        account_ids: set[str],
        account_id: str,
    ) -> str:
        scope = _account_scope(
            account_ids
        )

        normalized = _normalize_account_id(
            account_id
        )

        if normalized not in scope:
            raise DemoWithdrawalAuthorizationError(
                "Demo Wallet account is outside "
                "the authenticated withdrawal scope"
            )

        return normalized

    def _require_recipient(
        self,
        *,
        account_ids: set[str],
        recipient_id: str,
    ) -> dict[str, Any]:
        scope = _account_scope(
            account_ids
        )

        try:
            return self.registry.get_recipient(
                recipient_id,
                owner_account_ids=scope,
            )

        except KeyError as exc:
            raise DemoWithdrawalAuthorizationError(
                "Demo withdrawal recipient is outside "
                "the authenticated Wallet scope"
            ) from exc

    def _require_destination(
        self,
        *,
        account_ids: set[str],
        destination_id: str,
    ) -> dict[str, Any]:
        scope = _account_scope(
            account_ids
        )

        try:
            return self.registry.get_destination(
                destination_id,
                owner_account_ids=scope,
            )

        except KeyError as exc:
            raise DemoWithdrawalAuthorizationError(
                "Demo withdrawal destination is outside "
                "the authenticated Wallet scope"
            ) from exc

    def _require_request(
        self,
        *,
        account_ids: set[str],
        request_id: str,
    ) -> dict[str, Any]:
        scope = _account_scope(
            account_ids
        )

        try:
            return self.flow.get_request(
                request_id,
                account_ids=scope,
            )

        except KeyError as exc:
            raise DemoWithdrawalAuthorizationError(
                "Demo withdrawal request is outside "
                "the authenticated Wallet scope"
            ) from exc

    def recipients_payload(
        self,
        *,
        account_ids: set[str],
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        scope = _account_scope(
            account_ids
        )

        items = self.registry.list_recipients(
            owner_account_ids=scope,
            status=status,
            limit=limit,
        )

        return {
            **self._base(),
            "items":
                items,
            "recipients":
                items,
            "count":
                len(items),
        }

    def recipient_detail_payload(
        self,
        *,
        account_ids: set[str],
        recipient_id: str,
    ) -> dict[str, Any]:
        recipient = self._require_recipient(
            account_ids=account_ids,
            recipient_id=recipient_id,
        )

        events = self.registry.list_recipient_events(
            recipient[
                "recipient_id"
            ]
        )

        return {
            **self._base(),
            "item":
                recipient,
            "recipient":
                recipient,
            "events":
                events,
        }

    def create_recipient_payload(
        self,
        *,
        account_ids: set[str],
        owner_account_id: str,
        address: str,
        label: str = "",
        username: str = "demo",
    ) -> dict[str, Any]:
        owner = self._require_account(
            account_ids,
            owner_account_id,
        )

        result = self.registry.create_recipient(
            owner_account_id=owner,
            address=address,
            label=label,
            username=username,
        )

        return {
            **self._base(),
            **result,
            "recipient":
                result["item"],
        }

    def rename_recipient_payload(
        self,
        *,
        account_ids: set[str],
        recipient_id: str,
        label: str,
        username: str = "demo",
    ) -> dict[str, Any]:
        self._require_recipient(
            account_ids=account_ids,
            recipient_id=recipient_id,
        )

        result = self.registry.rename_recipient(
            recipient_id=recipient_id,
            label=label,
            username=username,
        )

        return {
            **self._base(),
            **result,
            "recipient":
                result["item"],
        }

    def archive_recipient_payload(
        self,
        *,
        account_ids: set[str],
        recipient_id: str,
        username: str = "demo",
        reason: str = "",
    ) -> dict[str, Any]:
        self._require_recipient(
            account_ids=account_ids,
            recipient_id=recipient_id,
        )

        result = self.registry.archive_recipient(
            recipient_id=recipient_id,
            username=username,
            reason=reason,
        )

        return {
            **self._base(),
            **result,
            "recipient":
                result["item"],
        }

    def restore_recipient_payload(
        self,
        *,
        account_ids: set[str],
        recipient_id: str,
        username: str = "demo",
        reason: str = "",
    ) -> dict[str, Any]:
        self._require_recipient(
            account_ids=account_ids,
            recipient_id=recipient_id,
        )

        result = self.registry.restore_recipient(
            recipient_id=recipient_id,
            username=username,
            reason=reason,
        )

        return {
            **self._base(),
            **result,
            "recipient":
                result["item"],
        }

    def prepare_destination_payload(
        self,
        *,
        account_ids: set[str],
        recipient_id: str,
        currency: str,
        chain: str,
        memo: str = "",
        username: str = "demo",
    ) -> dict[str, Any]:
        self._require_recipient(
            account_ids=account_ids,
            recipient_id=recipient_id,
        )

        result = (
            self.registry
            .create_destination_from_recipient(
                recipient_id=recipient_id,
                currency=currency,
                chain=chain,
                memo=memo,
                username=username,
            )
        )

        return {
            **self._base(),
            **result,
            "destination":
                result["item"],
        }

    def destinations_payload(
        self,
        *,
        account_ids: set[str],
        status: str | None = None,
        currency: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        scope = _account_scope(
            account_ids
        )

        items = self.registry.list_destinations(
            owner_account_ids=scope,
            status=status,
            currency=currency,
            limit=limit,
        )

        return {
            **self._base(),
            "items":
                items,
            "destinations":
                items,
            "count":
                len(items),
        }

    def destination_detail_payload(
        self,
        *,
        account_ids: set[str],
        destination_id: str,
    ) -> dict[str, Any]:
        destination = self._require_destination(
            account_ids=account_ids,
            destination_id=destination_id,
        )

        events = self.registry.list_destination_events(
            destination[
                "destination_id"
            ]
        )

        return {
            **self._base(),
            "item":
                destination,
            "destination":
                destination,
            "events":
                events,
        }

    def capabilities_payload(
        self,
        *,
        account_ids: set[str],
        account_id: str,
        currency: str,
    ) -> dict[str, Any]:
        owner = self._require_account(
            account_ids,
            account_id,
        )

        capabilities = self.registry.capabilities(
            account_id=owner,
            currency=currency,
        )

        return {
            **self._base(),
            **capabilities,
        }

    def preflight_payload(
        self,
        *,
        account_ids: set[str],
        account_id: str,
        destination_id: str,
        currency: str,
        amount: Decimal | str | int,
    ) -> dict[str, Any]:
        owner = self._require_account(
            account_ids,
            account_id,
        )

        destination = self._require_destination(
            account_ids=account_ids,
            destination_id=destination_id,
        )

        if (
            destination[
                "owner_account_id"
            ]
            != owner
        ):
            raise DemoWithdrawalAuthorizationError(
                "Demo withdrawal destination does not "
                "belong to the selected Wallet account"
            )

        preflight = self.flow.preflight(
            owner_account_id=owner,
            destination_id=destination_id,
            currency=currency,
            amount=amount,
        )

        return {
            **self._base(),
            **preflight,
        }

    def simulate_request_payload(
        self,
        *,
        account_ids: set[str],
        request_id: str,
        account_id: str,
        destination_id: str,
        currency: str,
        amount: Decimal | str | int,
        username: str = "demo",
    ) -> dict[str, Any]:
        owner = self._require_account(
            account_ids,
            account_id,
        )

        destination = self._require_destination(
            account_ids=account_ids,
            destination_id=destination_id,
        )

        if (
            destination[
                "owner_account_id"
            ]
            != owner
        ):
            raise DemoWithdrawalAuthorizationError(
                "Demo withdrawal destination does not "
                "belong to the selected Wallet account"
            )

        result = self.flow.create_request(
            request_id=request_id,
            owner_account_id=owner,
            destination_id=destination_id,
            currency=currency,
            amount=amount,
            username=username,
        )

        required_confirmation = None

        if (
            result.get(
                "audit_recorded"
            )
            and result.get(
                "audit"
            )
        ):
            audit = dict(
                result["audit"]
            )

            if (
                audit.get(
                    "status"
                )
                == "simulated"
            ):
                required_confirmation = (
                    demo_withdrawal_reservation_confirmation_text(
                        audit[
                            "request_id"
                        ]
                    )
                )

        return {
            **self._base(),
            **result,
            "required_confirmation":
                required_confirmation,
            "next_action": (
                "reserve"
                if required_confirmation
                else None
            ),
        }

    def requests_payload(
        self,
        *,
        account_ids: set[str],
        limit: int = 50,
    ) -> dict[str, Any]:
        scope = _account_scope(
            account_ids
        )

        items = self.flow.list_requests(
            account_ids=scope,
            limit=limit,
        )

        return {
            **self._base(),
            "items":
                items,
            "requests":
                items,
            "count":
                len(items),
        }

    @staticmethod
    def _workflow_payload(
        request: dict[str, Any],
    ) -> dict[str, Any]:
        status = str(
            request.get(
                "status"
            )
            or ""
        ).strip()

        request_id = str(
            request[
                "request_id"
            ]
        )

        required_confirmation = None
        next_action = None

        if status == "simulated":
            next_action = "reserve"
            required_confirmation = (
                demo_withdrawal_reservation_confirmation_text(
                    request_id
                )
            )

        elif status == "reserved":
            next_action = "confirm"
            required_confirmation = (
                demo_withdrawal_confirmation_text(
                    request
                )
            )

        elif status == "confirmed_ready":
            next_action = "jit_prepare"
            required_confirmation = (
                demo_withdrawal_jit_preparation_confirmation_text(
                    request_id
                )
            )

        elif status == "jit_prepared":
            next_action = "jit_execute"
            required_confirmation = (
                demo_withdrawal_jit_execution_confirmation_text(
                    request
                )
            )

        elif status == "jit_ready":
            next_action = "execute"
            required_confirmation = (
                demo_withdrawal_execution_confirmation_text(
                    request
                )
            )

        terminal = (
            status
            == "withdrawal_settled"
        )

        return {
            "status":
                status,
            "terminal":
                terminal,
            "next_action":
                next_action,
            "required_confirmation":
                required_confirmation,
            "can_reserve":
                status == "simulated",
            "can_confirm":
                status == "reserved",
            "can_prepare_jit":
                status == "confirmed_ready",
            "can_execute_jit":
                status == "jit_prepared",
            "can_execute":
                status == "jit_ready",
            "can_reconcile":
                False,
            "can_settle":
                False,
            "can_abandon":
                False,
            "can_hold_on_main":
                False,
            "can_cancel":
                False,
        }

    def request_detail_payload(
        self,
        *,
        account_ids: set[str],
        request_id: str,
    ) -> dict[str, Any]:
        request = self._require_request(
            account_ids=account_ids,
            request_id=request_id,
        )

        events = self.flow.list_request_events(
            request[
                "request_id"
            ]
        )

        lock = self.lifecycle.get_lock(
            request[
                "request_id"
            ]
        )

        workflow = self._workflow_payload(
            request
        )

        return {
            **self._base(),
            "item":
                request,
            "request":
                request,
            "events":
                events,
            "operation_lock":
                lock,
            "workflow":
                workflow,
            "required_confirmation":
                workflow[
                    "required_confirmation"
                ],
            "next_action":
                workflow[
                    "next_action"
                ],
        }

    def locks_payload(
        self,
        *,
        account_ids: set[str],
    ) -> dict[str, Any]:
        scope = _account_scope(
            account_ids
        )

        items = [
            item
            for item
            in self.lifecycle.list_locks()
            if item[
                "owner_account_id"
            ] in scope
        ]

        return {
            **self._base(),
            "items":
                items,
            "locks":
                items,
            "count":
                len(items),
        }

    def reserve_payload(
        self,
        *,
        account_ids: set[str],
        request_id: str,
        confirmation: str,
        username: str = "demo",
    ) -> dict[str, Any]:
        self._require_request(
            account_ids=account_ids,
            request_id=request_id,
        )

        result = self.lifecycle.reserve(
            request_id=request_id,
            confirmation=confirmation,
            username=username,
        )

        return {
            **self._base(),
            **result,
            "detail":
                self.request_detail_payload(
                    account_ids=account_ids,
                    request_id=request_id,
                ),
        }

    def confirm_payload(
        self,
        *,
        account_ids: set[str],
        request_id: str,
        confirmation: str,
        username: str = "demo",
    ) -> dict[str, Any]:
        self._require_request(
            account_ids=account_ids,
            request_id=request_id,
        )

        result = self.lifecycle.confirm(
            request_id=request_id,
            confirmation=confirmation,
            username=username,
        )

        return {
            **self._base(),
            **result,
            "detail":
                self.request_detail_payload(
                    account_ids=account_ids,
                    request_id=request_id,
                ),
        }

    def prepare_jit_payload(
        self,
        *,
        account_ids: set[str],
        request_id: str,
        confirmation: str,
        username: str = "demo",
    ) -> dict[str, Any]:
        self._require_request(
            account_ids=account_ids,
            request_id=request_id,
        )

        result = self.lifecycle.prepare_jit(
            request_id=request_id,
            confirmation=confirmation,
            username=username,
        )

        return {
            **self._base(),
            **result,
            "detail":
                self.request_detail_payload(
                    account_ids=account_ids,
                    request_id=request_id,
                ),
        }

    def execute_jit_payload(
        self,
        *,
        account_ids: set[str],
        request_id: str,
        confirmation: str,
        username: str = "demo",
    ) -> dict[str, Any]:
        self._require_request(
            account_ids=account_ids,
            request_id=request_id,
        )

        result = self.lifecycle.execute_jit(
            request_id=request_id,
            confirmation=confirmation,
            username=username,
        )

        return {
            **self._base(),
            **result,
            "detail":
                self.request_detail_payload(
                    account_ids=account_ids,
                    request_id=request_id,
                ),
        }

    def execute_payload(
        self,
        *,
        account_ids: set[str],
        request_id: str,
        confirmation: str,
        username: str = "demo",
    ) -> dict[str, Any]:
        self._require_request(
            account_ids=account_ids,
            request_id=request_id,
        )

        result = self.lifecycle.execute(
            request_id=request_id,
            confirmation=confirmation,
            username=username,
        )

        return {
            **self._base(),
            **result,
            "detail":
                self.request_detail_payload(
                    account_ids=account_ids,
                    request_id=request_id,
                ),
        }
