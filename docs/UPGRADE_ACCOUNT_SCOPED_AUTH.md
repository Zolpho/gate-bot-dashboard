# Upgrade: public dashboard with account-scoped action authentication

This release changes authentication from a global dashboard wall to a split model:

- public monitoring views require no login;
- disruptive and sensitive actions require a dashboard user;
- each account operator can act only on assigned Gate account IDs;
- an optional `super_admin` can act across all accounts.

## New local secret

Create `/opt/gate-bot-dashboard/secrets/dashboard_users.json` using the included manager. Passwords are prompted securely and stored only as PBKDF2-SHA256 hashes.

```bash
cd /opt/gate-bot-dashboard
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

Optional super administrator:

```bash
python3 scripts/manage_dashboard_users.py add \
  --username lorenzo \
  --role super_admin
```

## Environment

Add or confirm:

```env
DASHBOARD_USERS_FILE=/run/secrets/dashboard_users.json
CORS_ORIGINS=https://zolpho.github.io
ALLOW_BOT_STOP=false
```

The old variables remain an optional protected-action super-admin fallback:

```env
DASHBOARD_USERNAME=
DASHBOARD_PASSWORD=
```

Leave them empty when only per-account users should exist.

## Protected routes

- `GET /api/auth/me`
- `GET /api/bots/{id}/raw`
- `GET /api/account`
- `GET /api/recommendations`
- `POST /api/sync`
- `POST /api/bots/{id}/stop`
- alert-rule create/update/delete
- alert-event acknowledgement

The backend loads the actual database resource and checks its account ownership. An operator cannot gain access by altering `account_id` in a request.

## Nginx

Nginx should proxy all `/api/` methods and preserve the `Authorization` header. FastAPI handles CORS and account authorization. Do not place global `auth_basic` on the virtual host.

```nginx
location /api/ {
    proxy_pass http://192.168.1.221:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
}
```

## Deploy

```bash
cd /opt/gate-bot-dashboard
docker compose up -d --build --force-recreate
docker compose logs --tail=150
```

Verify public access:

```bash
curl -sS http://192.168.1.221:8080/api/overview | jq '.counts'
```

Verify an action is protected:

```bash
curl -i -X POST http://192.168.1.221:8080/api/sync
```

Expected: `401 Unauthorized`.

Verify account identity:

```bash
curl -u zolnode -sS http://192.168.1.221:8080/api/auth/me | jq
```

Verify cross-account denial by using a bot ID that belongs to `arnold`:

```bash
curl -u zolnode -i \
  http://192.168.1.221:8080/api/bots/ARNOLD_BOT_ID/raw
```

Expected: `403 Forbidden`.
