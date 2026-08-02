# Security notes

## Gate credentials

Use one dedicated read-only Gate API v4 key per account or subaccount. Store the real values only in `secrets/gate_accounts.json` on Ubuntu.

The complete `secrets/` directory is mounted read-only at `/run/config`. At container start, a short root entrypoint copies `gate_accounts.json` into `/run/secrets/gate_accounts.json`, changes ownership to the unprivileged `dashboard` user, and then drops privileges before starting FastAPI.

The application cannot modify the host Gate-credential file. API responses expose only safe account metadata. Keys and secrets are never serialized by the application.

## Required Gate permissions

For native Gate bot monitoring, use only the read permissions needed by the account. The current onboarding defaults are:

```text
quant, wallet, spot, account
```

Keep Withdraw and subaccount administration disabled. Keep `ALLOW_BOT_STOP=false` until separate, narrowly scoped management keys are configured.

## Public monitoring and protected actions

Normal monitoring routes are public. Sensitive reads and state-changing actions require an account-specific dashboard login.

Each dashboard user is assigned one or more Gate account IDs. The backend loads the target resource and checks its stored `account_id`; it never trusts a browser-supplied account ID as proof of ownership.

An account operator can manage only assigned accounts. A `super_admin` can manage all configured accounts. Legacy `.env` credentials are supported only as an optional super administrator for protected actions.

## Dashboard password storage

Dashboard users are stored in `secrets/dashboard_users.json` with PBKDF2-SHA256 password hashes. Plaintext passwords are never stored.

Only this one file is bind-mounted writable at `/run/secrets/dashboard_users.json` to support self-service password changes. Gate API credentials remain read-only. The container entrypoint keeps the user file mode `600` and makes it writable by the unprivileged `dashboard` process.

A password change:

- requires the currently authenticated Basic credentials,
- requires the current password to be entered again,
- can change only the authenticated username,
- requires at least 12 characters,
- creates a persistent backup under `/data/dashboard-user-backups`, and
- invalidates the old password immediately.

See [`USER_PASSWORD_CHANGE.md`](USER_PASSWORD_CHANGE.md).

## Browser credentials

The frontend keeps the Basic Authorization value only in JavaScript memory. It is not written to local storage, session storage, cookies, URLs, or GitHub Pages. Refreshing the page or selecting **Lock admin** clears it.

## Network

The production Compose file binds FastAPI to the Ubuntu LAN address used by the internal Nginx proxy. Do not add a public router/NAT rule for port 8080. Expose only HTTPS through Nginx on `192.168.1.111`.

CORS is handled by FastAPI and restricted with `CORS_ORIGINS`. Do not duplicate CORS headers in Nginx.

## Recommended host permissions

```bash
chmod 600 .env
chmod 700 secrets
chmod 600 secrets/gate_accounts.json
chmod 600 secrets/dashboard_users.json
```

The entrypoint may change `dashboard_users.json` ownership to the container's unprivileged dashboard UID so the bind-mounted file can be updated. The parent `secrets/` directory remains mode `700`.

Never commit probe output, databases, backups, `.env`, `gate_accounts.json`, or `dashboard_users.json`.
