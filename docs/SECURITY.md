# Security notes

## Gate credentials

Use one dedicated read-only Gate API v4 key per account or subaccount. Store the real values only in `secrets/gate_accounts.json` on Ubuntu.

The JSON file is ignored by Git and excluded from the Docker build context. At container start, a short root entrypoint copies the host-mounted file into `/run/secrets/gate_accounts.json`, changes ownership to the unprivileged `dashboard` user, then drops privileges before starting FastAPI.

API responses expose only safe account metadata. Keys and secrets are never serialized by the application.

## Required permissions

Enable only the read permissions needed by that account's bots. Keep Withdraw and subaccount administration disabled. Keep `ALLOW_BOT_STOP=false` for monitoring.

## Network

Compose binds FastAPI to `127.0.0.1:8080`. Use Caddy or Nginx for HTTPS. Do not publish port 8080 directly.

## Authentication

Set both `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` to enable HTTP Basic Authentication. All routes except `/api/health` then require authentication.

## Local files

Recommended host permissions:

```bash
chmod 600 .env
chmod 700 secrets
chmod 600 secrets/gate_accounts.json
```

Never commit probe output, databases, backups, `.env`, or the real accounts file.
