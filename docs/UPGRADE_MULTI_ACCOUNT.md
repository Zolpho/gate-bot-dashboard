# Upgrade an existing Ubuntu installation to multi-account support

These commands assume the existing installation is `/opt/gate-bot-dashboard` and the updated archive is `/tmp/gate-bot-dashboard-multi-account.zip`.

## 1. Back up the current database and local configuration

```bash
cd /opt/gate-bot-dashboard

mkdir -p /root/gate-bot-dashboard-upgrade-backup
cp -a .env /root/gate-bot-dashboard-upgrade-backup/.env
[ ! -f secrets/gate_accounts.json ] || cp -a secrets/gate_accounts.json /root/gate-bot-dashboard-upgrade-backup/

backup_path=$(docker compose exec -T gate-bot-dashboard python scripts/backup_db.py | tr -d '\r')
docker cp "gate-bot-dashboard:${backup_path}" /root/gate-bot-dashboard-upgrade-backup/
ls -lh /root/gate-bot-dashboard-upgrade-backup
```

## 2. Extract the updated source separately

```bash
rm -rf /tmp/gate-bot-dashboard-multi-account
mkdir -p /tmp/gate-bot-dashboard-multi-account
unzip -q /tmp/gate-bot-dashboard-multi-account.zip -d /tmp/gate-bot-dashboard-multi-account
```

## 3. Replace source while preserving runtime secrets and Git history

```bash
rsync -a --delete \
  --exclude='.git/' \
  --exclude='.env' \
  --exclude='secrets/gate_accounts.json' \
  --exclude='backups/' \
  --exclude='gate_probe_output*.json' \
  /tmp/gate-bot-dashboard-multi-account/gate-bot-dashboard/ \
  /opt/gate-bot-dashboard/

cd /opt/gate-bot-dashboard
```

## 4. Create the two-account secret

```bash
install -d -m 700 secrets
cp -n secrets/gate_accounts.example.json secrets/gate_accounts.json
nano secrets/gate_accounts.json
chmod 600 secrets/gate_accounts.json
jq empty secrets/gate_accounts.json
git check-ignore -v secrets/gate_accounts.json
```

Insert the `zolnode` and `arnold` API key/secret pairs. Do not print the file afterward.

## 5. Keep demo mode on for the first rebuild

```bash
sed -i 's/^DEMO_MODE=.*/DEMO_MODE=true/' .env

grep -q '^GATE_ACCOUNTS_FILE=' .env \
  && sed -i 's#^GATE_ACCOUNTS_FILE=.*#GATE_ACCOUNTS_FILE=/run/secrets/gate_accounts.json#' .env \
  || echo 'GATE_ACCOUNTS_FILE=/run/secrets/gate_accounts.json' >> .env

grep -q '^PURGE_DEMO_DATA_ON_LIVE=' .env \
  || echo 'PURGE_DEMO_DATA_ON_LIVE=true' >> .env
```

## 6. Build and start

```bash
docker compose config
docker compose up -d --build --force-recreate
docker compose ps
docker compose logs --tail=150
curl -s http://127.0.0.1:8080/api/health | jq
```

## 7. Probe both real Gate accounts

```bash
docker compose run --rm --no-deps \
  gate-bot-dashboard \
  python scripts/probe_gate.py \
  --output /data/gate_probe_output.json

docker compose run --rm --no-deps \
  gate-bot-dashboard \
  python - <<'PY'
import json
from pathlib import Path
data = json.loads(Path('/data/gate_probe_output.json').read_text())
print('error_count:', data['error_count'])
for item in data['accounts']:
    print(item['account']['id'], (item.get('running') or {}).get('count', 0), len(item['errors']))
PY
```

Do not continue until `error_count: 0`.

## 8. Enable live mode

```bash
sed -i 's/^DEMO_MODE=.*/DEMO_MODE=false/' .env
docker compose up -d --build --force-recreate
docker compose logs -f --tail=200
```

Stop following logs with `Ctrl+C`.

## 9. Verify both accounts

```bash
curl -s http://127.0.0.1:8080/api/health | jq
```

When Basic Auth is configured:

```bash
curl -u lorenzo -s http://127.0.0.1:8080/api/accounts | jq
curl -u lorenzo -s http://127.0.0.1:8080/api/overview | jq '.accounts[] | {id,name,sync_status,last_error,portfolio}'
curl -u lorenzo -s 'http://127.0.0.1:8080/api/bots?account_id=zolnode' | jq '.items | length'
curl -u lorenzo -s 'http://127.0.0.1:8080/api/bots?account_id=arnold' | jq '.items | length'
```

## 10. Commit and push source changes

```bash
cd /opt/gate-bot-dashboard
git status
git add .
git status
```

Confirm `.env` and `secrets/gate_accounts.json` are not staged, then:

```bash
git commit -m "Add multi-account Gate bot monitoring"
git push
```
