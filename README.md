# Gate Bot Dashboard

A self-hosted dashboard for Gate.io's **native trading bots**. It polls Gate API v4, stores snapshots locally, calculates portfolio history and drawdown, exposes raw strategy-specific fields, and evaluates local alert rules. Telegram can later consume the same alert/event API without changing the collector.

![Status](https://img.shields.io/badge/status-ready_to_deploy-17d39a)

## Included

- Native Gate bot discovery through `GET /bot/portfolio/running`
- Per-strategy detail through `GET /bot/portfolio/detail`
- Dynamic preservation of Gate's `base_info`, `metrics`, and `position` maps
- Spot Grid, Futures Grid, Margin Grid, Infinite Grid, Spot Martingale, and Futures/Contract Martingale labels
- Portfolio totals, 24-hour/7-day changes, current value, PnL, ROI, grid profit, and floating PnL
- Local equity/PnL history and per-bot history
- Current and maximum drawdown calculated from saved snapshots
- Strategy table, search, filters, sorting, CSV export, and raw API inspector
- Local alert rules for PnL, ROI, drawdown, floating PnL, current value, liquidation distance, and stale data
- Optional account snapshot from wallet/spot/USDT-futures endpoints
- Strategy recommendations endpoint inspector
- Optional native stop action, **disabled by default**
- Docker Compose, health check, API probe, SQLite backup, snapshot export, and tests
- Demo mode with realistic sample history, requiring no Gate credentials

## Start in demo mode

```bash
cp .env.example .env
docker compose up -d --build
```

Open:

```text
http://SERVER_IP:8080
```

The example environment starts with `DEMO_MODE=true`. This is intentional: inspect the dashboard before adding any API credential.

## Connect Gate

1. Create a dedicated API v4 key in Gate.
2. Give it only the read permissions needed by the Bot, Wallet, Spot, and Futures endpoints you plan to use.
3. Do **not** enable withdrawals.
4. Restrict the API key to the server's public IP when Gate offers that option.
5. Put the key and secret in `.env`.
6. Run the read-only probe before switching the dashboard to live mode.

```bash
# .env
DEMO_MODE=false
GATE_API_KEY=your_key
GATE_API_SECRET=your_secret
ALLOW_BOT_STOP=false
```

Run the probe from a local Python environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/probe_gate.py
```

It writes `gate_probe_output.json` with the running-bot response and the first bot detail. It does not create, change, or stop a bot.

Then deploy:

```bash
docker compose up -d --build
docker compose logs -f --tail=200
```

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `DEMO_MODE` | `false` in code / `true` in example | Use generated bots without calling Gate |
| `GATE_API_KEY` | empty | Gate API v4 key |
| `GATE_API_SECRET` | empty | Gate API v4 secret |
| `POLL_SECONDS` | `60` | Collection interval; minimum 15 seconds |
| `DATABASE_URL` | `sqlite:////data/gate_bots.db` | SQLAlchemy database URL |
| `SNAPSHOT_RETENTION_DAYS` | `365` | Snapshot retention |
| `MISSING_BOT_GRACE_SYNCS` | `2` | Successful missing cycles before a locally tracked bot is marked stopped |
| `DASHBOARD_USERNAME` | empty | Optional HTTP Basic Auth username |
| `DASHBOARD_PASSWORD` | empty | Optional HTTP Basic Auth password |
| `ALLOW_BOT_STOP` | `false` | Enables the server-side stop route |
| `BOT_STOP_CONFIRMATION_TEXT` | `STOP` | Confirmation required by the stop route |

The API secret never reaches the browser. Signed Gate requests are made only by the FastAPI backend.

## Dashboard API

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/health` | Mode and safe configuration status |
| `GET` | `/api/overview` | Portfolio totals, periods, counts, leaders, latest sync |
| `GET` | `/api/portfolio/history` | Locally recorded portfolio series |
| `POST` | `/api/sync` | Trigger a collection immediately |
| `GET` | `/api/bots` | Filtered normalized bot list |
| `GET` | `/api/bots/{id}` | Bot detail, analytics, and raw Gate maps |
| `GET` | `/api/bots/{id}/history` | Bot snapshots and drawdown |
| `POST` | `/api/bots/{id}/stop` | Optional Gate native stop request |
| `GET/POST` | `/api/alerts/rules` | List/create alert rules |
| `PATCH/DELETE` | `/api/alerts/rules/{id}` | Update/delete a rule |
| `GET` | `/api/alerts/events` | Alert event history |
| `POST` | `/api/alerts/events/{id}/acknowledge` | Acknowledge an event |
| `GET` | `/api/account` | On-demand account endpoint snapshot |
| `GET` | `/api/recommendations` | Gate strategy recommendation response |
| `GET` | `/api/sync-runs` | Collector history |

Interactive FastAPI documentation is available at `/docs`, and the generated OpenAPI schema is available at `/openapi.json`. For an internet-facing deployment, protect the whole service with the included Basic Auth or a reverse proxy with stronger authentication.

## Data model

The collector keeps four important layers:

1. `bots`: latest normalized state for each `(strategy_id, strategy_type)`.
2. `bot_snapshots`: time-series values captured on every successful poll.
3. `sync_runs`: success/error audit trail.
4. `alert_rules` and `alert_events`: reusable for the later Telegram integration.

Gate changed bot detail data to strategy-specific string maps. The adapter maps known fields into stable columns while preserving the complete response in `raw_detail_json`. New Gate fields therefore remain visible in the dashboard even before a new adapter release.

## Current Gate limitations handled by the project

- The public native portfolio-list endpoint is specifically a **running strategies** endpoint. A bot that disappears is retained locally and marked stopped after a configurable grace period, but the dashboard cannot reconstruct old bots that Gate never returns and that were stopped before the first collection.
- Gate does not document a native bot WebSocket stream in the current Bot API. The project polls REST endpoints.
- `base_info`, `metrics`, and `position` vary by bot type. Empty values are normal for strategies where a metric does not apply.
- Marketplace/copied strategies appear only when Gate returns them through the authenticated portfolio endpoint. The project does not scrape mobile-app/private endpoints.
- Local 24-hour performance, equity curves, and drawdown become more accurate after the collector has accumulated snapshots.
- Gate's application may calculate display PnL or annualised values differently from the generic fields returned for a specific strategy. Raw data is always retained for reconciliation.

## Stop action

Monitoring is the default. To expose the stop button:

```bash
ALLOW_BOT_STOP=true
```

The UI then requires typed confirmation and the server verifies that Gate's detail response reports `stop_supported=true`. One stop policy is submitted per request. Keep this disabled until the read-only dashboard has been validated against the Gate app.

## Backup and export

For Docker, create a consistent online SQLite backup inside the persistent volume and copy it to the host:

```bash
backup_path=$(docker compose exec -T gate-bot-dashboard python scripts/backup_db.py | tr -d '\r')
mkdir -p backups
docker cp "gate-bot-dashboard:${backup_path}" backups/
```

For a local non-Docker run:

```bash
python scripts/backup_db.py --source data/gate_bots.db --directory backups
python scripts/export_snapshots.py
```

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
make demo
```

Tests and lint:

```bash
make test
make lint
```

## Architecture

```text
Browser (HTML/CSS/JS)
        │
        ▼
FastAPI REST API
        ├── Gate API v4 signer/client
        ├── strategy adapter (known fields + raw maps)
        ├── asyncio background collector
        ├── alert evaluator
        └── SQLAlchemy
                │
                ▼
             SQLite
```

## Official references

- Gate API v4 documentation: https://www.gate.com/docs/developers/apiv4/en/
- Official Gate Python SDK and generated BotApi: https://github.com/gate/gateapi-python

See [`docs/API_CAPABILITIES.md`](docs/API_CAPABILITIES.md) for the endpoint and model audit used by this implementation.
