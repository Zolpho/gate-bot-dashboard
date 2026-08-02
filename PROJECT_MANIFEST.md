# Project manifest

## Runtime

- `app/accounts.py`: validates and loads multi-account secret configuration
- `app/gate_client.py`: account-scoped Gate API v4 signing and requests
- `app/security.py`: hashed dashboard users and account-scoped authorization
- `app/api/auth.py`: in-memory Basic-auth identity check for protected actions
- `app/collector.py`: aggregate and per-account collection
- `app/models.py`: account-aware database schema
- `app/migrations.py`: automatic SQLite v1 to v2 migration
- `app/metrics.py`: account-aware totals, history, and serialization
- `app/api/`: FastAPI routes
- `frontend/`: static multi-account dashboard
- `docker-entrypoint.sh`: secure runtime secret copy and privilege drop

## Local-only runtime files

- `.env`
- `secrets/gate_accounts.json`
- `secrets/dashboard_users.json`
- `/data/gate_bots.db` in the Docker volume
- probe output and backups

## Validation

- Python compilation
- API and adapter tests
- account configuration and account-authorization tests
- SQLite migration test
- JavaScript syntax validation
