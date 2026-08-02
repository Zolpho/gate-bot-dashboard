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
copy_secret /run/config/dashboard_users.json /run/secrets/dashboard_users.json

chown dashboard:dashboard /data
exec gosu dashboard "$@"
