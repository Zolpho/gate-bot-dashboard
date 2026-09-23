from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select

from .db import session_scope
from .models import (
    DashboardAuthIpAllowlistEntry,
    DashboardAuthIpPolicy,
)


class AuthIpRestrictionError(
    RuntimeError
):
    """Invalid or inconsistent IP-restriction state."""


def _normalize_username(
    value: str,
) -> str:
    normalized = str(
        value or ""
    ).strip().lower()

    if (
        not normalized
        or len(normalized) > 64
    ):
        raise AuthIpRestrictionError(
            "Invalid dashboard username"
        )

    return normalized


def _utc_iso(
    value: datetime | None,
) -> str | None:
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=UTC
        )
    else:
        value = value.astimezone(
            UTC
        )

    return value.isoformat()


def normalize_ip_network(
    value: str,
) -> str:
    """
    Normalize one IPv4/IPv6 host or CIDR.

    Bare addresses become host networks:
      192.0.2.10 -> 192.0.2.10/32
      2001:db8::1 -> 2001:db8::1/128

    Host bits in an entered CIDR are canonicalized to the
    actual network boundary. Interface-scoped IPv6 values are
    rejected because they are not meaningful as remote-client
    allowlist identities.
    """

    normalized = str(
        value or ""
    ).strip()

    if (
        not normalized
        or len(normalized) > 64
        or "%" in normalized
    ):
        raise AuthIpRestrictionError(
            "Invalid IP network"
        )

    try:
        network = ipaddress.ip_network(
            normalized,
            strict=False,
        )
    except ValueError as exc:
        raise AuthIpRestrictionError(
            "Invalid IP network"
        ) from exc

    return network.with_prefixlen


def normalize_ip_allowlist(
    values: Iterable[str],
) -> list[str]:
    canonical = {
        normalize_ip_network(
            value
        )
        for value in values
    }

    networks = [
        ipaddress.ip_network(
            value,
            strict=True,
        )
        for value in canonical
    ]

    networks.sort(
        key=lambda network: (
            network.version,
            int(
                network.network_address
            ),
            network.prefixlen,
        )
    )

    return [
        network.with_prefixlen
        for network in networks
    ]


def client_ip_matches_allowlist(
    client_ip: str,
    networks: Iterable[str],
) -> bool:
    """
    Pure matcher for later enforcement work.

    This function is deliberately NOT wired into login,
    Bearer-session validation, or any request dependency in
    A7C490A.
    """

    normalized = str(
        client_ip or ""
    ).strip()

    if (
        not normalized
        or "%" in normalized
    ):
        raise AuthIpRestrictionError(
            "Invalid client IP"
        )

    try:
        address = ipaddress.ip_address(
            normalized
        )
    except ValueError as exc:
        raise AuthIpRestrictionError(
            "Invalid client IP"
        ) from exc

    for value in normalize_ip_allowlist(
        networks
    ):
        network = ipaddress.ip_network(
            value,
            strict=True,
        )

        if (
            network.version
            == address.version
            and address in network
        ):
            return True

    return False


def get_ip_restriction_policy(
    *,
    username: str,
) -> dict[str, object]:
    """
    Return a safe durable-policy snapshot.

    No row is created for a missing user policy. Missing state
    is intentionally equivalent to enabled=False.
    """

    normalized_username = (
        _normalize_username(
            username
        )
    )

    with session_scope() as db:
        policy = db.get(
            DashboardAuthIpPolicy,
            normalized_username,
        )

        if policy is None:
            return {
                "username":
                    normalized_username,
                "enabled":
                    False,
                "updated_by":
                    "",
                "created_at":
                    None,
                "updated_at":
                    None,
                "allowlist":
                    [],
            }

        entries = list(
            db.scalars(
                select(
                    DashboardAuthIpAllowlistEntry
                )
                .where(
                    DashboardAuthIpAllowlistEntry
                    .username
                    == normalized_username
                )
                .order_by(
                    DashboardAuthIpAllowlistEntry
                    .network,
                    DashboardAuthIpAllowlistEntry
                    .id,
                )
            )
        )

        return {
            "username":
                normalized_username,
            "enabled":
                bool(
                    policy.enabled
                ),
            "updated_by":
                policy.updated_by,
            "created_at":
                _utc_iso(
                    policy.created_at
                ),
            "updated_at":
                _utc_iso(
                    policy.updated_at
                ),
            "allowlist": [
                {
                    "id":
                        entry.id,
                    "network":
                        entry.network,
                    "label":
                        entry.label,
                    "created_at":
                        _utc_iso(
                            entry.created_at
                        ),
                }
                for entry in entries
            ],
        }
