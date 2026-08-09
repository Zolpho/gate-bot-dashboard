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

prepare_dashboard_users
chown dashboard:dashboard /data
exec gosu dashboard "$@"
