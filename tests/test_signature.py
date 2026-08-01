from __future__ import annotations

import hashlib
import hmac

from app.gate_client import GateClient


def test_signature_matches_gate_algorithm() -> None:
    secret = "secret"
    method = "GET"
    path = "/api/v4/bot/portfolio/running"
    query = "page=1&page_size=50"
    payload = b""
    timestamp = "1700000000"
    hashed = hashlib.sha512(payload).hexdigest()
    expected = hmac.new(
        secret.encode(), f"{method}\n{path}\n{query}\n{hashed}\n{timestamp}".encode(), hashlib.sha512
    ).hexdigest()
    assert GateClient.build_signature(secret, method, path, query, payload, timestamp) == expected
