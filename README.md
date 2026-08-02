# Gate Bot Dashboard

A self-hosted dashboard for monitoring Gate native trading bots across multiple Gate accounts and subaccounts.

The application keeps Gate credentials on the Ubuntu server, signs API v4 requests in FastAPI, stores periodic snapshots in SQLite, and serves the dashboard from the same HTTPS origin.

## Multi-account features

- Separate API key and secret for every Gate account or subaccount
- Combined portfolio overview across all accounts
- Global account selector for overview, bots, history, alerts, and sync runs
- Per-account connection state, last successful sync, errors, bot count, PnL, and ROI
- Bot identity keyed by `(account_id, strategy_id, strategy_type)`
- Per-account API client and per-account sync audit records
- Account name included in bot details, alert messages, CSV exports, and snapshot exports
- Manual sync for all accounts or one selected account
- Read-only account snapshot inspection for one or all configured accounts
- Backward-compatible support for a single API key in `.env`
- Automatic in-place migration of the original SQLite schema

## Architecture

```text
Browser
   │ HTTPS
   ▼
Caddy or Nginx
   │
   ▼
FastAPI + static dashboard on 127.0.0.1:8080
   ├── Gate client: zolnode credentials
   ├── Gate client: arnold credentials
   ├── background collector
   ├── analytics and alerts
   └── SQLite in Docker volume
```

GitHub stores source code only. These stay on Ubuntu and are ignored by Git:

- `.env`
- `secrets/gate_accounts.json`
- SQLite database and backups
- probe output

## Documentation

Detailed project documentation is available in [`docs/`](docs/):

| Document | Purpose |
|---|---|
| [`API_CAPABILITIES.md`](docs/API_CAPABILITIES.md) | Gate bot API endpoints, tested capabilities, and current limitations |
| [`SECURITY.md`](docs/SECURITY.md) | Secret handling, API-key isolation, CORS, reverse-proxy, and deployment security |
| [`UPGRADE_MULTI_ACCOUNT.md`](docs/UPGRADE_MULTI_ACCOUNT.md) | Migration from the original single-account setup to multiple Gate accounts |
| [`UPGRADE_ACCOUNT_SCOPED_AUTH.md`](docs/UPGRADE_ACCOUNT_SCOPED_AUTH.md) | Public monitoring with authenticated, account-scoped administrative actions |
| [`ONBOARD_GATE_SUBACCOUNT.md`](docs/ONBOARD_GATE_SUBACCOUNT.md) | Complete onboarding of an existing Gate subaccount, its API key, and its dashboard user |
| [`PRIVATE_ACCOUNT_BALANCE.md`](docs/PRIVATE_ACCOUNT_BALANCE.md) | Authenticated, account-scoped Gate balances, asset valuation, and bot allocation |

For a newly created Gate subaccount, start with [`ONBOARD_GATE_SUBACCOUNT.md`](docs/ONBOARD_GATE_SUBACCOUNT.md).

## Quick start in demo mode

```bash
cp .env.example .env
chmod 600 .env
mkdir -p secrets

docker compose up -d --build
docker compose logs --tail=100
curl -s http://127.0.0.1:8080/api/health
```

The supplied deployment binds the backend to `192.168.1.221:8080` for the internal Nginx proxy at `192.168.1.111`. Adjust this private address for another network.

## Configure `zolnode` and `arnold`

Create the local secret file:

```bash
install -d -m 700 secrets
cp secrets/gate_accounts.example.json secrets/gate_accounts.json
nano secrets/gate_accounts.json
chmod 600 secrets/gate_accounts.json
jq empty secrets/gate_accounts.json
```

Structure:

```json
{
  "accounts": [
    {
      "id": "zolnode",
      "name": "zolnode",
      "account_type": "subaccount",
      "gate_uid": "",
      "api_key": "ZOLNODE_API_KEY",
      "api_secret": "ZOLNODE_API_SECRET",
      "enabled": true
    },
    {
      "id": "arnold",
      "name": "arnold",
      "account_type": "subaccount",
      "gate_uid": "",
      "api_key": "ARNOLD_API_KEY",
      "api_secret": "ARNOLD_API_SECRET",
      "enabled": true
    }
  ]
}
```

The host file can remain `root:root` with mode `600`. The container entrypoint copies it into an internal runtime secret owned by the unprivileged `dashboard` user before FastAPI starts.

Confirm Git ignores it:

```bash
git check-ignore -v secrets/gate_accounts.json
git ls-files secrets/gate_accounts.json
```

The second command must return nothing.

## Probe both accounts safely

Keep `DEMO_MODE=true` while testing credentials. Build and start the new image, then run:

```bash
docker compose run --rm --no-deps \
  gate-bot-dashboard \
  python scripts/probe_gate.py \
  --output /data/gate_probe_output.json
```

Show a safe summary without printing strategy details:

```bash
docker compose run --rm --no-deps \
  gate-bot-dashboard \
  python - <<'PY'
import json
from pathlib import Path
p = Path('/data/gate_probe_output.json')
data = json.loads(p.read_text())
print('error_count:', data['error_count'])
for item in data['accounts']:
    running = item.get('running') or {}
    print(item['account']['id'], 'bots=', running.get('count', 0), 'errors=', len(item['errors']))
PY
```

Probe only one account when necessary:

```bash
docker compose run --rm --no-deps \
  gate-bot-dashboard \
  python scripts/probe_gate.py \
  --account zolnode \
  --output /data/gate_probe_zolnode.json
```

The probe is read-only. Its output can contain bot IDs, balances, positions, and raw Gate responses; do not commit or publish it.

## Switch to live collection

After both probes return zero errors:

```bash
nano .env
```

Set:

```env
DEMO_MODE=false
GATE_ACCOUNTS_FILE=/run/secrets/gate_accounts.json
ALLOW_BOT_STOP=false
```

Recreate the service:

```bash
docker compose up -d --build --force-recreate
docker compose logs -f --tail=200
```

The first live startup automatically:

1. upgrades an original single-account SQLite schema,
2. preserves existing IDs, snapshots, alert references, and sync history,
3. removes generated demo bots when `PURGE_DEMO_DATA_ON_LIVE=true`, and
4. starts separate collection for `zolnode` and `arnold`.

## Safe API-key permissions

For the complete setup and onboarding procedure, see [`docs/ONBOARD_GATE_SUBACCOUNT.md`](docs/ONBOARD_GATE_SUBACCOUNT.md).

For monitoring, use a separate read-only key on each subaccount:

- Bots: Read Only
- Account: Read Only
- Wallets: Read Only
- Spot Trading: Read Only when used
- Perpetual Futures: Read Only when used
- Withdraw: disabled
- Subaccount administration: disabled
- IP whitelist: Ubuntu server public IP

Keep `ALLOW_BOT_STOP=false`. A later Telegram management service should use separate narrowly scoped write-enabled keys rather than expanding these monitoring keys.

## Dashboard API

See [`docs/API_CAPABILITIES.md`](docs/API_CAPABILITIES.md) for the detailed Gate API capability review.

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/health` | Safe configuration and account count |
| `GET` | `/api/accounts` | Per-account sync and portfolio status |
| `GET` | `/api/overview?account_id=` | Combined or selected-account totals |
| `GET` | `/api/portfolio/history?account_id=` | Combined or selected history |
| `POST` | `/api/sync?account_id=` | Sync every account or one account |
| `GET` | `/api/sync-runs?account_id=` | Aggregate or per-account audit trail |
| `GET` | `/api/bots?account_id=` | Account-aware bot list |
| `GET` | `/api/bots/{id}` | Bot detail, analytics, account, and raw maps |
| `GET` | `/api/bots/{id}/history` | Bot snapshot history and drawdown |
| `GET` | `/api/alerts/events?account_id=` | Alert events scoped by account |
| `GET` | `/api/account?account_id=` | Gate account snapshot; all accounts when omitted |
| `GET` | `/api/recommendations?account_id=` | Recommendation response using the selected account |

## Upgrade an existing installation

See [`docs/UPGRADE_MULTI_ACCOUNT.md`](docs/UPGRADE_MULTI_ACCOUNT.md).

Back up the database before upgrading:

```bash
backup_path=$(docker compose exec -T gate-bot-dashboard python scripts/backup_db.py | tr -d '\r')
mkdir -p backups
docker cp "gate-bot-dashboard:${backup_path}" backups/
chmod 600 backups/*.db
```

Never run `docker compose down -v` unless you intentionally want to delete the persistent database volume.

## Development and validation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
PYTHONPATH=. pytest -q
node --check frontend/app.js
```

## Public dashboard and account-scoped actions

See [`docs/UPGRADE_ACCOUNT_SCOPED_AUTH.md`](docs/UPGRADE_ACCOUNT_SCOPED_AUTH.md) for the implementation and upgrade procedure.

All normal monitoring `GET` routes are public so GitHub Pages can display the portfolio without a login. State-changing or sensitive routes require HTTP Basic credentials from `secrets/dashboard_users.json`.

Each account operator is assigned one or more Gate account IDs. The backend loads the target bot or rule from SQLite and verifies its `account_id` against the authenticated user's assignments. A browser-supplied account ID is never trusted as proof of ownership.

Create the two initial users on Ubuntu:

```bash
install -d -m 700 secrets

python3 scripts/manage_dashboard_users.py add \
  --username zolnode \
  --account zolnode

python3 scripts/manage_dashboard_users.py add \
  --username arnold \
  --account arnold

chmod 600 secrets/dashboard_users.json
python3 scripts/manage_dashboard_users.py list
```

Optional global administrator:

```bash
python3 scripts/manage_dashboard_users.py add \
  --username lorenzo \
  --role super_admin
```

The generated file contains PBKDF2-SHA256 password hashes, never plaintext passwords. After creating it, recreate the container so the entrypoint copies it into `/run/secrets/dashboard_users.json`:

```bash
docker compose up -d --build --force-recreate
```

The frontend keeps the Basic Authorization value only in JavaScript memory. It is not written to local storage, session storage, cookies, URLs, or GitHub Pages. Refreshing the page or choosing **Lock admin** clears it.

Public routes include overview, bot lists, normalized bot details, history, alerts, and sync history. Protected routes include manual sync, raw Gate details, account snapshots, recommendations, alert mutations, and bot stop. `zolnode` receives `403 Forbidden` when attempting an action against an `arnold` resource, and vice versa.

## Security

See [`docs/SECURITY.md`](docs/SECURITY.md) for the complete security guidance.

- Gate API secrets and dashboard password hashes remain only on Ubuntu.
- Public account representations omit Gate UID and internal error details.
- Public bot details omit Gate raw responses; raw data requires the matching account login.
- Real secret files are excluded from Git and Docker build context.
- FastAPI runs as the unprivileged `dashboard` user after the entrypoint copies both secret files.
- CORS is restricted by `CORS_ORIGINS`; initially use `https://zolpho.github.io`.
- Existing `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` values are supported only as an optional legacy super-admin for protected actions. Clear them after creating per-account users if no global administrator is required.
- Keep `ALLOW_BOT_STOP=false` until separate minimum-permission Gate management keys are configured.
