#!/usr/bin/env python3

import getpass
import hashlib
import hmac
import json
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


HOST = "https://api.gateio.ws"
PREFIX = "/api/v4"

ACCOUNT_ID = "zolnode"
EXPECTED_UID = "13079163"
EXPECTED_IP = "5.183.0.204"
EXPECTED_NAME = "eqty-dashboard-bot-control"

CONTROL_FILE = Path("secrets/gate_bot_control.json")


def gate_request(key, secret, method, endpoint, query=None):
    method = method.upper()
    query_string = urllib.parse.urlencode(query or [])

    body = b""
    timestamp = str(int(time.time()))

    body_hash = hashlib.sha512(body).hexdigest()

    sign_string = "\n".join([
        method,
        PREFIX + endpoint,
        query_string,
        body_hash,
        timestamp,
    ])

    signature = hmac.new(
        secret.encode(),
        sign_string.encode(),
        hashlib.sha512,
    ).hexdigest()

    url = HOST + PREFIX + endpoint

    if query_string:
        url += "?" + query_string

    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Accept": "application/json",
            "KEY": key,
            "Timestamp": timestamp,
            "SIGN": signature,
            "User-Agent": "EQTY-Bot-Control-Importer/1.0",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            raw = response.read()

            if not raw:
                return None

            return json.loads(raw)

    except urllib.error.HTTPError as exc:
        body = exc.read().decode(
            errors="replace",
        )

        raise RuntimeError(
            f"Gate HTTP {exc.code}: {body}"
        ) from exc


def load_control_file():
    if not CONTROL_FILE.exists():
        return {"accounts": []}

    data = json.loads(
        CONTROL_FILE.read_text(encoding="utf-8")
    )

    if not isinstance(data, dict):
        raise RuntimeError(
            "Bot Control file must contain a JSON object"
        )

    if not isinstance(data.get("accounts"), list):
        raise RuntimeError(
            "Bot Control file must contain an accounts array"
        )

    return data


def save_atomic(data):
    CONTROL_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    os.chmod(
        CONTROL_FILE.parent,
        0o700,
    )

    if CONTROL_FILE.exists():
        stamp = datetime.now(
            timezone.utc
        ).strftime("%Y%m%dT%H%M%SZ")

        backup = CONTROL_FILE.with_name(
            f"{CONTROL_FILE.name}.bak.{stamp}"
        )

        shutil.copy2(
            CONTROL_FILE,
            backup,
        )

        os.chmod(
            backup,
            0o600,
        )

        print(
            f"Backup created: {backup}"
        )

    fd, temp_name = tempfile.mkstemp(
        prefix=".gate_bot_control.",
        dir=CONTROL_FILE.parent,
    )

    temp_path = Path(temp_name)

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                data,
                handle,
                indent=2,
            )

            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.chmod(
            temp_path,
            0o600,
        )

        os.replace(
            temp_path,
            CONTROL_FILE,
        )

        os.chmod(
            CONTROL_FILE,
            0o600,
        )

    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def permission_map(item):
    result = {}

    for perm in item.get("perms") or []:
        if not isinstance(perm, dict):
            continue

        name = str(
            perm.get("name", "")
        ).strip().lower()

        if name:
            result[name] = bool(
                perm.get("read_only")
            )

    return result


def key_matches(item, api_key):
    remote_key = str(
        item.get("key", "")
    ).strip()

    # Gate may return the full key or a masked representation.
    if remote_key == api_key:
        return True

    visible_prefix = remote_key.split("*", 1)[0]

    if visible_prefix and api_key.startswith(
        visible_prefix
    ):
        return True

    return False


print("=== Import zolnode Bot Control key ===")
print()
print(
    "Credentials are entered invisibly and "
    "will not be printed."
)

api_key = getpass.getpass(
    "New zolnode Bot Control API key: "
).strip()

api_secret = getpass.getpass(
    "New zolnode Bot Control API secret: "
).strip()

if not api_key or not api_secret:
    raise SystemExit(
        "API key and secret are required."
    )


# ------------------------------------------------------------
# 1. Authenticate new key and confirm account identity
# ------------------------------------------------------------

detail = gate_request(
    api_key,
    api_secret,
    "GET",
    "/account/detail",
)

uid = str(
    detail.get("user_id", "")
)

if uid != EXPECTED_UID:
    raise SystemExit(
        f"ERROR: credential belongs to Gate UID {uid}, "
        f"expected {EXPECTED_UID}"
    )

print(
    f"Gate identity:     OK ({uid})"
)


# ------------------------------------------------------------
# 2. Verify IP whitelist
# ------------------------------------------------------------

whitelist = [
    str(item)
    for item in (
        detail.get("ip_whitelist")
        or []
    )
]

if EXPECTED_IP not in whitelist:
    raise SystemExit(
        "ERROR: expected IP whitelist "
        f"{EXPECTED_IP}, got {whitelist}"
    )

if len(whitelist) != 1:
    print(
        "WARNING: key contains additional "
        f"whitelisted IPs: {whitelist}"
    )
else:
    print(
        f"IP whitelist:      OK ({EXPECTED_IP})"
    )


# ------------------------------------------------------------
# 3. Inspect main-account key inventory
# ------------------------------------------------------------

main_keys = gate_request(
    api_key,
    api_secret,
    "GET",
    "/account/main_keys",
)

if not isinstance(main_keys, list):
    raise SystemExit(
        "ERROR: unexpected /account/main_keys response"
    )

matching = [
    item
    for item in main_keys
    if isinstance(item, dict)
    and key_matches(item, api_key)
]

if len(matching) != 1:
    # Fall back to the unique expected key name.
    matching = [
        item
        for item in main_keys
        if isinstance(item, dict)
        and str(
            item.get("name", "")
        ).strip().lower()
        == EXPECTED_NAME.lower()
    ]

if len(matching) != 1:
    print()
    print(
        "Could not uniquely identify the key "
        "inside /account/main_keys."
    )
    print(
        "Authentication is valid, but refusing "
        "to persist without key metadata verification."
    )
    raise SystemExit(1)

remote = matching[0]

print(
    "Key name:          "
    + str(remote.get("name"))
)

if int(remote.get("state", 0)) != 1:
    raise SystemExit(
        "ERROR: Gate key is not in normal state: "
        f"{remote.get('state')}"
    )

print(
    "Key state:         OK (normal)"
)

remote_ips = [
    str(item)
    for item in (
        remote.get("ip_whitelist")
        or []
    )
]

if EXPECTED_IP not in remote_ips:
    raise SystemExit(
        "ERROR: key inventory does not contain "
        f"expected IP {EXPECTED_IP}"
    )


# ------------------------------------------------------------
# 4. Inspect permission metadata
# ------------------------------------------------------------

perms = permission_map(remote)

print()
print("Permissions returned by Gate:")

for name in sorted(perms):
    mode = (
        "READ-ONLY"
        if perms[name]
        else "READ-WRITE"
    )

    print(
        f"  {name:<14} {mode}"
    )

errors = []

# These must never be read/write for Bot Control.
for name in ("wallet", "spot", "account"):
    if name in perms and perms[name] is False:
        errors.append(
            f"{name} unexpectedly READ-WRITE"
        )

# Gate's published generic permission schema does not
# currently document quant consistently, but live Gate
# responses may contain it.
if "quant" in perms:
    if perms["quant"] is True:
        errors.append(
            "quant is READ-ONLY; Bot Control "
            "requires READ-WRITE"
        )
    else:
        print(
            "\nQuant permission:  OK (READ-WRITE)"
        )
else:
    print()
    print(
        "WARNING: Gate did not expose 'quant' in "
        "/account/main_keys metadata."
    )
    print(
        "We will verify Bot API authentication now; "
        "the first Bot Control write will provide "
        "the definitive write-permission test."
    )

if errors:
    raise SystemExit(
        "ERROR: " + "; ".join(errors)
    )


# ------------------------------------------------------------
# 5. Read-only Bot API test
# ------------------------------------------------------------

bots = gate_request(
    api_key,
    api_secret,
    "GET",
    "/bot/portfolio/running",
    query=[
        ("page", 1),
        ("page_size", 1),
    ],
)

print(
    "Bot API read test: OK"
)


# ------------------------------------------------------------
# 6. Persist separately from Monitor credentials
# ------------------------------------------------------------

data = load_control_file()

existing = [
    item
    for item in data["accounts"]
    if str(
        item.get("id", "")
    ).strip().lower() == ACCOUNT_ID
]

if existing:
    raise SystemExit(
        f"ERROR: {ACCOUNT_ID} already exists in "
        f"{CONTROL_FILE}; refusing to overwrite it."
    )

print()
confirmation = input(
    "Type zolnode to save this Bot Control credential: "
).strip().lower()

if confirmation != ACCOUNT_ID:
    raise SystemExit(
        "Cancelled."
    )

data["accounts"].append({
    "id": ACCOUNT_ID,
    "name": "zolnode",
    "account_type": "main",
    "gate_uid": EXPECTED_UID,
    "api_key": api_key,
    "api_secret": api_secret,
    "enabled": True,
})

save_atomic(data)

print()
print(
    f"Saved:             {CONTROL_FILE}"
)

print(
    "File mode:         "
    + oct(
        CONTROL_FILE.stat().st_mode
        & 0o777
    )
)

print()
print(
    "SUCCESS: zolnode Bot Control credential imported."
)
