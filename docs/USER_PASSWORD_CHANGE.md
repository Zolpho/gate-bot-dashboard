# Dashboard user password changes

Dashboard account operators and file-backed super administrators can change their own dashboard password from the web interface. They cannot select another username or modify another user's password, role, enabled state, or Gate-account assignments.

## Security model

The password-change request requires both:

1. the currently unlocked HTTP Basic credentials in the `Authorization` header, and
2. the current password entered again in the change-password dialog.

The backend derives the username from the authenticated identity. The request body contains no username, so changing another user's password is not an available operation.

The backend then:

1. locks `dashboard_users.json` exclusively,
2. reloads the authenticated user's current record,
3. verifies the current password again,
4. rejects a password shorter than 12 characters or equal to the old password,
5. creates a persistent backup in the Docker data volume,
6. stores a new PBKDF2-SHA256 hash, and
7. flushes the updated file to disk before returning success.

Other browser sessions using the old password fail on their next protected API request. The browser that performed the change replaces its in-memory Basic Authorization value with the new password and remains unlocked.

Passwords are never stored in local storage, session storage, cookies, URLs, logs, or Git.

## Required writable mount

Gate API credentials remain read-only. Only the dashboard user file is bind-mounted writable:

```yaml
volumes:
  - gate_bot_data:/data
  - ./secrets:/run/config:ro
  - ./secrets/dashboard_users.json:/run/secrets/dashboard_users.json
```

The entrypoint changes the mounted file ownership to the unprivileged `dashboard` container user and keeps mode `600`. The host `secrets/` directory should remain mode `700`, so other host users cannot traverse it.

Before recreating the container, verify that the source is a regular file. Docker must not create a directory at this path:

```bash
cd /opt/gate-bot-dashboard

test -f secrets/dashboard_users.json \
  && echo "dashboard user file exists" \
  || { echo "ERROR: secrets/dashboard_users.json is missing"; exit 1; }

chmod 700 secrets
chmod 600 secrets/dashboard_users.json
```

## Environment settings

Defaults:

```env
DASHBOARD_USERS_FILE=/run/secrets/dashboard_users.json
DASHBOARD_USERS_BACKUP_DIR=/data/dashboard-user-backups
DASHBOARD_USERS_BACKUP_KEEP=20
```

Backups live inside the persistent `gate_bot_data` Docker volume. They contain password hashes and account assignments, so treat them as secrets.

## Deployment

Back up the host user file first:

```bash
cd /opt/gate-bot-dashboard
install -d -m 700 /root/gate-bot-dashboard-auth-backups
cp -a secrets/dashboard_users.json \
  "/root/gate-bot-dashboard-auth-backups/dashboard_users.$(date -u +%Y%m%dT%H%M%SZ).json"
```

Validate and recreate the service:

```bash
docker compose config >/dev/null
docker compose up -d --build --force-recreate
docker compose ps
docker compose logs --tail=100
```

Confirm that the file is writable by the application but Gate credentials remain read-only:

```bash
docker compose exec -T gate-bot-dashboard sh -lc '
  id
  test -r /run/secrets/gate_accounts.json && echo "Gate accounts readable"
  test ! -w /run/config/gate_accounts.json && echo "Gate accounts source read-only"
  test -r /run/secrets/dashboard_users.json && echo "Dashboard users readable"
  test -w /run/secrets/dashboard_users.json && echo "Dashboard users writable"
'
```

## Web interface

1. Open the public dashboard.
2. Select **Admin unlock**.
3. Sign in with the account-specific dashboard username and password.
4. Select **Change password**.
5. Enter the current password and the new password twice.
6. Submit the form.

A successful change closes the dialog and displays `Password changed successfully.` The browser remains unlocked with the new in-memory credentials.

The following errors are shown inside the dialog:

- current password incorrect,
- new password shorter than 12 characters,
- new password and confirmation do not match,
- new password equal to the current password,
- user disabled or removed,
- user file not writable,
- backup creation failure.

A legacy super administrator configured with `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` cannot change that `.env` password through the dashboard. Update `.env` on the server and recreate the container instead.

## API

Endpoint:

```text
POST /api/auth/change-password
```

Authentication:

```text
Authorization: Basic <current dashboard credentials>
```

Request body:

```json
{
  "current_password": "current password",
  "new_password": "new password with at least 12 characters",
  "confirm_password": "new password with at least 12 characters"
}
```

Example local test:

```bash
curl -u zolnode \
  -H 'Content-Type: application/json' \
  -d '{
    "current_password": "CURRENT_PASSWORD",
    "new_password": "NEW_PASSWORD_AT_LEAST_12_CHARS",
    "confirm_password": "NEW_PASSWORD_AT_LEAST_12_CHARS"
  }' \
  http://192.168.1.221:8080/api/auth/change-password | jq
```

Avoid putting real passwords directly in shell history. The browser UI is the recommended method.

## Recovery

List backups in the persistent volume:

```bash
docker compose exec -T gate-bot-dashboard \
  find /data/dashboard-user-backups -maxdepth 1 -type f -printf '%TY-%Tm-%Td %TH:%TM:%TS %p\n' | sort
```

To restore a backup, stop the container, copy the selected backup to the host user file, restore permissions, and start the service again. Do not overwrite the file while FastAPI is running.
