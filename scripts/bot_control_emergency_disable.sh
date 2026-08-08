#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${BOT_CONTROL_ENV_FILE:-.env}"
RESTART=true

case "${1:-}" in
  "") ;;
  --no-restart) RESTART=false ;;
  *) echo "Usage: $0 [--no-restart]" >&2; exit 2 ;;
esac

[[ -f "$ENV_FILE" ]] || {
  echo "ERROR: env file not found: $ENV_FILE" >&2
  exit 1
}

python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import os, stat, sys, tempfile

path = Path(sys.argv[1])
safe = {
    "ALLOW_BOT_CREATE": "false",
    "BOT_CREATE_SIMULATION": "true",
    "ALLOW_BOT_STOP": "false",
    "BOT_STOP_SIMULATION": "true",
    "BOT_CONTROL_LIVE_ARMED": "false",
}

lines = path.read_text(encoding="utf-8").splitlines()
seen = {k: 0 for k in safe}

for line in lines:
    s = line.strip()
    if s and not s.startswith("#") and "=" in s:
        key = s.split("=", 1)[0].strip()
        if key in seen:
            seen[key] += 1

dupes = [k for k, count in seen.items() if count > 1]
if dupes:
    raise SystemExit(
        "REFUSED: duplicate managed variables: " + ", ".join(dupes)
    )

out = []
found = set()

for line in lines:
    s = line.strip()
    if s and not s.startswith("#") and "=" in s:
        key = s.split("=", 1)[0].strip()
        if key in safe:
            out.append(f"{key}={safe[key]}")
            found.add(key)
            continue
    out.append(line)

missing = [k for k in safe if k not in found]
if missing:
    if out and out[-1].strip():
        out.append("")
    out.append("# Emergency-safe Bot Control state")
    out.extend(f"{k}={safe[k]}" for k in missing)

new_text = "\n".join(out).rstrip() + "\n"
mode = stat.S_IMODE(path.stat().st_mode)

fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent, text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(new_text)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)
finally:
    if os.path.exists(tmp):
        os.unlink(tmp)

print("Bot Control environment forced to safe state:")
for k, v in safe.items():
    print(f"  {k}={v}")
PY

if [[ "$RESTART" != true ]]; then
  echo "Environment updated; service restart skipped."
  exit 0
fi

echo "Recreating dashboard service..."
docker compose up -d --no-deps --force-recreate gate-bot-dashboard

echo "Waiting for dashboard health..."
healthy=false
for _ in $(seq 1 30); do
  if curl -fsS http://192.168.1.221:8080/api/health >/dev/null 2>&1; then
    healthy=true
    break
  fi
  sleep 1
done

[[ "$healthy" == true ]] || {
  echo "ERROR: dashboard did not become healthy" >&2
  docker compose ps gate-bot-dashboard
  exit 1
}

echo "Runtime safety state:"
curl -fsS http://192.168.1.221:8080/api/health |
jq '{
  status,
  allow_bot_create,
  bot_create_simulation,
  allow_bot_stop,
  bot_stop_simulation
}'

echo "EMERGENCY DISABLE COMPLETE"
