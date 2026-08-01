#!/bin/sh
set -eu

umask 077

mkdir -p /run/secrets
rm -f /run/secrets/gate_accounts.json

if [ -f /run/config/gate_accounts.json ]; then
  cp \
    /run/config/gate_accounts.json \
    /run/secrets/gate_accounts.json

  chmod 600 /run/secrets/gate_accounts.json
  chown dashboard:dashboard /run/secrets/gate_accounts.json
fi

chown dashboard:dashboard /data

exec gosu dashboard "$@"
