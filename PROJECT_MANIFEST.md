# Project Manifest

## Runtime

- `app/main.py` — FastAPI application and background collection loop
- `app/gate_client.py` — Gate API v4 HMAC-SHA512 client
- `app/bot_adapter.py` — strategy response normalisation with raw-map preservation
- `app/collector.py` — pagination, detail collection, persistence, missing-bot handling
- `app/metrics.py` — portfolio aggregates, history and drawdown
- `app/alerts.py` — local rule evaluation
- `app/demo.py` — deterministic sample bots and history
- `app/security.py` — optional whole-application HTTP Basic Auth
- `app/api/` — dashboard, bot, alert and system routes

## Frontend

- `frontend/index.html` — responsive dashboard interface
- `frontend/styles.css` — dark Gate-inspired layout
- `frontend/app.js` — API client, filters, charts, details, alerts, export and inspector

## Operations

- `Dockerfile`
- `docker-compose.yml`
- `.env.example`
- `Makefile`
- `scripts/probe_gate.py`
- `scripts/backup_db.py`
- `scripts/export_snapshots.py`

## Documentation and validation

- `README.md`
- `docs/API_CAPABILITIES.md`
- `docs/SECURITY.md`
- `tests/test_signature.py`
- `tests/test_adapter.py`
- `tests/test_api.py`
