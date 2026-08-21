#!/bin/sh
set -eu

umask 077
mkdir -p /run/secrets

copy_secret() {
  source_path="$1"
  target_path="$2"

  rm -f "$target_path"
  if [ -f "$source_path" ]; then
    cp "$source_path" "$target_path"
    chmod 600 "$target_path"
    chown dashboard:dashboard "$target_path"
  fi
}

copy_secret /run/config/gate_accounts.json /run/secrets/gate_accounts.json
copy_secret /run/config/gate_bot_control.json /run/secrets/gate_bot_control.json
copy_secret /run/config/gate_treasury.json /run/secrets/gate_treasury.json
copy_secret /run/config/gate_trading.json /run/secrets/gate_trading.json

prepare_dashboard_users() {
  source_path="/run/config/dashboard_users.json"
  target_path="/run/secrets/dashboard_users.json"

  # In the normal Compose deployment target_path is a writable bind mount of
  # the host dashboard_users.json. Do not remove or replace the mount point.
  if [ ! -f "$target_path" ] && [ -f "$source_path" ]; then
    cp "$source_path" "$target_path"
  fi

  if [ -f "$target_path" ]; then
    chmod 600 "$target_path"
    chown dashboard:dashboard "$target_path"
  fi
}

prepare_frontend_config() {
  target_path="/app/frontend/config.js"
  api_base_url="${DASHBOARD_FRONTEND_API_BASE_URL:-}"

  # Docker-hosted frontends default to same-origin API access.
  # JSON encoding prevents an environment value from breaking
  # the generated JavaScript string.
  python - "$target_path" "$api_base_url" <<'PYCODE'
import json
import os
import sys

target_path = sys.argv[1]
api_base_url = sys.argv[2].rstrip("/")

content = (
    "window.GATE_DASHBOARD_CONFIG = Object.freeze({\n"
    f"  apiBaseUrl: {json.dumps(api_base_url)},\n"
    "});\n"
)

temporary_path = f"{target_path}.tmp"

with open(
    temporary_path,
    "w",
    encoding="utf-8",
) as handle:
    handle.write(content)

os.replace(
    temporary_path,
    target_path,
)
PYCODE

  chmod 644 "$target_path"
  chown dashboard:dashboard "$target_path"
}

prepare_dashboard_users
prepare_frontend_config

chown dashboard:dashboard /data
exec gosu dashboard "$@"
