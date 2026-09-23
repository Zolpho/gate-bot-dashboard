from __future__ import annotations

import ipaddress
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from .db import (
    SessionLocal,
    engine,
    session_scope,
    utcnow,
)
from .models import (
    DashboardAuthEvent,
    DashboardAuthIpAllowlistEntry,
    DashboardAuthIpPolicy,
)

MAX_IP_ALLOWLIST_ENTRIES = 64
MAX_IP_ALLOWLIST_LABEL_LENGTH = 128
MAX_IP_RESTRICTION_REASON_LENGTH = 1000


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


def _as_utc(
    value: datetime,
) -> datetime:
    if value.tzinfo is None:
        return value.replace(
            tzinfo=UTC
        )

    return value.astimezone(
        UTC
    )


def _now(
    value: datetime | None,
) -> datetime:
    return _as_utc(
        value
        if value is not None
        else utcnow()
    )


def _utc_iso(
    value: datetime | None,
) -> str | None:
    if value is None:
        return None

    return _as_utc(
        value
    ).isoformat()


def normalize_client_ip(
    value: str,
) -> str:
    """
    Return one canonical IPv4/IPv6 address.

    Interface-scoped IPv6 strings are deliberately rejected:
    a remote dashboard client identity must not depend on a
    server-local interface name.
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

    return address.compressed


def client_ip_host_network(
    value: str,
) -> str:
    """
    Convert one client address into its exact host network.

    IPv4 -> /32
    IPv6 -> /128
    """

    address = ipaddress.ip_address(
        normalize_client_ip(
            value
        )
    )

    network = ipaddress.ip_network(
        (
            f"{address.compressed}/"
            f"{address.max_prefixlen}"
        ),
        strict=True,
    )

    return network.with_prefixlen


def normalize_ip_network(
    value: str,
) -> str:
    """
    Normalize one IPv4/IPv6 host or CIDR.

    Bare addresses become host networks:
      192.0.2.10 -> 192.0.2.10/32
      2001:db8::1 -> 2001:db8::1/128

    Host bits in an entered CIDR are canonicalized to the
    actual network boundary.
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


def _normalize_label(
    value: object,
) -> str:
    normalized = " ".join(
        str(
            value or ""
        )
        .replace(
            "\x00",
            " ",
        )
        .split()
    )

    if (
        len(normalized)
        > MAX_IP_ALLOWLIST_LABEL_LENGTH
    ):
        raise AuthIpRestrictionError(
            "IP allowlist label is too long"
        )

    return normalized


def normalize_ip_allowlist_entries(
    values: Iterable[
        dict[str, object]
    ],
) -> list[dict[str, str]]:
    raw = list(
        values
    )

    if (
        len(raw)
        > MAX_IP_ALLOWLIST_ENTRIES
    ):
        raise AuthIpRestrictionError(
            "IP allowlist contains too many entries"
        )

    prepared: list[
        dict[str, str]
    ] = []

    seen: set[str] = set()

    for item in raw:
        if not isinstance(
            item,
            dict,
        ):
            raise AuthIpRestrictionError(
                "Invalid IP allowlist entry"
            )

        network = normalize_ip_network(
            str(
                item.get(
                    "network",
                    "",
                )
            )
        )

        if network in seen:
            raise AuthIpRestrictionError(
                "Duplicate IP network after normalization"
            )

        seen.add(
            network
        )

        prepared.append(
            {
                "network":
                    network,
                "label":
                    _normalize_label(
                        item.get(
                            "label",
                            "",
                        )
                    ),
            }
        )

    prepared.sort(
        key=lambda item: (
            ipaddress.ip_network(
                item[
                    "network"
                ],
                strict=True,
            ).version,
            int(
                ipaddress.ip_network(
                    item[
                        "network"
                    ],
                    strict=True,
                ).network_address
            ),
            ipaddress.ip_network(
                item[
                    "network"
                ],
                strict=True,
            ).prefixlen,
        )
    )

    return prepared


def client_ip_matches_allowlist(
    client_ip: str,
    networks: Iterable[str],
) -> bool:
    """
    Pure matcher.

    A7C490B1 deliberately does not call this function from
    login or Bearer-session authorization. It is used only to
    validate that a user cannot stage an enabled policy which
    excludes the connection currently configuring it.
    """

    address = ipaddress.ip_address(
        normalize_client_ip(
            client_ip
        )
    )

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


def _policy_snapshot_in_session(
    db: Session,
    username: str,
) -> dict[str, Any]:
    policy = db.get(
        DashboardAuthIpPolicy,
        username,
    )

    if policy is None:
        return {
            "username":
                username,
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
                == username
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
            username,
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


def get_ip_restriction_policy(
    *,
    username: str,
) -> dict[str, Any]:
    """
    Return a safe durable-policy snapshot.

    Missing policy rows remain equivalent to disabled and are
    never created by a read.
    """

    normalized_username = (
        _normalize_username(
            username
        )
    )

    with session_scope() as db:
        return (
            _policy_snapshot_in_session(
                db,
                normalized_username,
            )
        )


def _event_snapshot(
    row: DashboardAuthEvent,
) -> dict[str, Any]:
    try:
        metadata = json.loads(
            row.metadata_json
            or "{}"
        )
    except (
        TypeError,
        json.JSONDecodeError,
    ):
        metadata = {}

    return {
        "id":
            row.id,
        "actor_username":
            row.actor_username,
        "target_username":
            row.target_username,
        "action":
            row.action,
        "reason":
            row.reason,
        "metadata":
            metadata,
        "created_at":
            _utc_iso(
                row.created_at
            ),
    }


def update_ip_restriction_policy(
    *,
    username: str,
    actor_username: str,
    enabled: bool,
    allowlist: Iterable[
        dict[str, object]
    ],
    observed_client_ip: str | None,
    reason: str = "",
    source: str = (
        "security_ip_restrictions"
    ),
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Atomically replace one user's durable IP policy.

    Enabling requires:
      - at least one allowlist entry
      - a valid request.client.host-derived client address
      - that observed address to match the requested allowlist

    This service only mutates local dashboard security state.
    It does not enforce the policy against login/session traffic.
    """

    target = _normalize_username(
        username
    )

    actor = _normalize_username(
        actor_username
    )

    if not isinstance(
        enabled,
        bool,
    ):
        raise AuthIpRestrictionError(
            "IP restriction enabled value must be true or false"
        )

    entries = (
        normalize_ip_allowlist_entries(
            allowlist
        )
    )

    normalized_client_ip = None

    if observed_client_ip is not None:
        normalized_client_ip = (
            normalize_client_ip(
                observed_client_ip
            )
        )

    if enabled:
        if not entries:
            raise AuthIpRestrictionError(
                "At least one IP allowlist entry is required before enabling IP restrictions"
            )

        if normalized_client_ip is None:
            raise AuthIpRestrictionError(
                "Trusted observed client IP is unavailable"
            )

        if not client_ip_matches_allowlist(
            normalized_client_ip,
            (
                item[
                    "network"
                ]
                for item in entries
            ),
        ):
            raise AuthIpRestrictionError(
                "Current observed client IP must be included in the allowlist before enabling IP restrictions"
            )

    selected_reason = str(
        reason or ""
    ).strip()

    if not selected_reason:
        selected_reason = (
            "Self-service IP restriction policy updated."
        )

    if (
        len(selected_reason)
        > MAX_IP_RESTRICTION_REASON_LENGTH
    ):
        raise AuthIpRestrictionError(
            "IP restriction update reason is too long"
        )

    selected_source = str(
        source or ""
    ).strip()

    if (
        not selected_source
        or len(selected_source) > 64
    ):
        raise AuthIpRestrictionError(
            "Invalid IP restriction update source"
        )

    reference = _now(
        now
    )

    db = SessionLocal()

    try:
        if engine.dialect.name == "sqlite":
            db.execute(
                text(
                    "BEGIN IMMEDIATE"
                )
            )

        current = (
            _policy_snapshot_in_session(
                db,
                target,
            )
        )

        old_enabled = bool(
            current[
                "enabled"
            ]
        )

        old_entries = [
            {
                "network":
                    str(
                        item[
                            "network"
                        ]
                    ),
                "label":
                    str(
                        item[
                            "label"
                        ]
                    ),
            }
            for item
            in current[
                "allowlist"
            ]
        ]

        old_pairs = {
            (
                item[
                    "network"
                ],
                item[
                    "label"
                ],
            )
            for item
            in old_entries
        }

        new_pairs = {
            (
                item[
                    "network"
                ],
                item[
                    "label"
                ],
            )
            for item
            in entries
        }

        allowlist_changed = (
            old_pairs
            != new_pairs
        )

        enabled_changed = (
            old_enabled
            != enabled
        )

        changed = (
            allowlist_changed
            or enabled_changed
        )

        row = db.get(
            DashboardAuthIpPolicy,
            target,
        )

        if not changed:
            db.rollback()

            return {
                "changed":
                    False,
                "created":
                    False,
                "policy":
                    current,
                "event":
                    None,
            }

        created = (
            row is None
        )

        if row is None:
            row = (
                DashboardAuthIpPolicy(
                    username=target,
                    enabled=enabled,
                    updated_by=actor,
                    created_at=reference,
                    updated_at=reference,
                )
            )

            db.add(
                row
            )

            # Ensure the parent exists before inserting
            # allowlist children.
            db.flush()

        else:
            row.enabled = enabled
            row.updated_by = actor
            row.updated_at = reference

        if allowlist_changed:
            db.execute(
                delete(
                    DashboardAuthIpAllowlistEntry
                ).where(
                    DashboardAuthIpAllowlistEntry
                    .username
                    == target
                )
            )

            for item in entries:
                db.add(
                    DashboardAuthIpAllowlistEntry(
                        username=target,
                        network=(
                            item[
                                "network"
                            ]
                        ),
                        label=(
                            item[
                                "label"
                            ]
                        ),
                        created_at=reference,
                    )
                )

        metadata = {
            "source":
                selected_source,
            "observed_client_ip":
                normalized_client_ip,
            "old_enabled":
                old_enabled,
            "new_enabled":
                enabled,
            "old_allowlist":
                old_entries,
            "new_allowlist":
                entries,
        }

        event = DashboardAuthEvent(
            actor_username=actor,
            target_username=target,
            action=(
                "ip_restriction_policy_updated"
            ),
            reason=selected_reason,
            metadata_json=json.dumps(
                metadata,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
            created_at=reference,
        )

        db.add(
            event
        )

        db.flush()

        policy = (
            _policy_snapshot_in_session(
                db,
                target,
            )
        )

        result = {
            "changed":
                True,
            "created":
                created,
            "policy":
                policy,
            "event":
                _event_snapshot(
                    event
                ),
        }

        db.commit()

        return result

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()
