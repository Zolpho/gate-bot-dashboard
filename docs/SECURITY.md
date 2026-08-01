# Security Checklist

## Gate key

- Create a dedicated key for this service.
- Keep it read-only during monitoring validation.
- Never enable withdrawals.
- Restrict it by server IP where possible.
- Do not put credentials in `docker-compose.yml`, source control, frontend files, screenshots, or support messages.
- Rotate the key after any suspected disclosure.

## Dashboard

- Set `DASHBOARD_USERNAME` and a strong `DASHBOARD_PASSWORD` before exposing port 8080 beyond a trusted network.
- Prefer a TLS reverse proxy such as Caddy, Traefik, or nginx.
- Firewall the service to known administration networks where practical.
- Keep `ALLOW_BOT_STOP=false` until monitoring data has been reconciled.

## Host

- Keep Docker and the operating system patched.
- Back up `/data/gate_bots.db`.
- Protect `.env` with owner-only permissions:

```bash
chmod 600 .env
```

- Review container logs for repeated authentication or Gate API errors.
- The supplied container drops Linux capabilities and sets `no-new-privileges`.

## Telegram phase

When Telegram is added, it should read `alert_events` or call the dashboard API. Bot-management commands must use an administrator allowlist, replay protection, explicit confirmations, and separate read/write Gate keys.
