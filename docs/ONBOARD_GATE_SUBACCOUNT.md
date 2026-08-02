# Gate Subaccount Onboarding

This document describes `scripts/onboard_gate_subaccount.py`, the guided onboarding tool for adding an **existing Gate subaccount** to the EQTY Gate Bot Dashboard.

The Gate subaccount itself must already exist before running the script.

## What the script does

The script performs the complete local dashboard onboarding flow:

1. Authenticates to Gate with a temporary main-account API key.
2. Lists existing Gate subaccounts and lets the operator select one.
3. Creates a new read-only API key for the selected subaccount.
4. Restricts the new key to the supplied public egress IP address.
5. Tests the key against Gate's native bot portfolio endpoint.
6. Adds the subaccount to `secrets/gate_accounts.json`.
7. Creates an account-scoped dashboard login in `secrets/dashboard_users.json`.
8. Creates timestamped backups and writes both JSON files atomically.
9. Restarts only the `gate-bot-dashboard` Compose service when `--restart` is used.

The resulting dashboard user may perform protected actions only for the Gate account assigned to that user.

Example mapping:

```text
Dashboard user: reserves
Assigned account: reserves
Allowed scope: account_id=reserves only
```

## Prerequisites

Run the script from the project directory:

```bash
cd /opt/gate-bot-dashboard
```

The following must already be available:

- Python 3.
- Docker Compose for the dashboard restart step.
- An existing Gate subaccount in normal state.
- A main-account Gate API key with **Subaccount: Read and Write** permission.
- The public egress/NAT IP address used by the dashboard server when it connects to Gate.
- The selected subaccount must have access to Gate native Trading Bots/Quant functionality.

The parent/main-account API key does not need Spot, Wallet, Futures, or Withdrawal permissions for this onboarding flow.

## Main-account API key

Create a temporary or tightly restricted API v4 key on the Gate main account with:

```text
Subaccount: Read and Write
All trading and withdrawal permissions: Disabled
IP whitelist: Public egress IP of the onboarding server
```

The parent credentials are used to:

- List Gate subaccounts.
- Create a child API key for the selected subaccount.
- Delete the newly created key if onboarding fails before local configuration is committed.

The script prompts for the parent key and secret without displaying them. They are used only in memory and are not written to the dashboard configuration.

## Default child API-key permissions

The created subaccount key uses these read-only permissions:

```text
quant, wallet, spot, account
```

| Permission | Purpose |
|---|---|
| `quant` | Required for Gate native bot portfolio endpoints. |
| `wallet` | Allows aggregate wallet and estimated-balance information. |
| `spot` | Allows spot available and locked balance information. |
| `account` | Allows account metadata needed by account-level monitoring. |

The default key does **not** include:

- Futures access.
- Withdrawal access.
- Read-write trading access.
- Bot stop/create permissions.

Protected bot-management actions should later use a separate management key with only the minimum required write permissions.

## Interactive onboarding

Run:

```bash
python3 scripts/onboard_gate_subaccount.py --restart
```

The script prompts for:

```text
Main-account Gate API key
Main-account Gate API secret
Gate subaccount selection
Public egress IP address
Dashboard password
Confirmation
```

Example plan:

```text
Onboarding plan:
  Gate sub-account: Reserves
  Gate user ID: 52535639
  Local account ID: reserves
  Display name: Reserves
  Dashboard username: reserves
  Dashboard role: account_operator
  API source: create
  Gate key name: eqty-dashboard-read
  Gate key mode: 1
  Read-only permissions: quant, wallet, spot, account
  IP whitelist: Public egress IP of the onboarding server
  Accounts file: secrets/gate_accounts.json
  Users file: secrets/dashboard_users.json
```

Review the plan carefully before entering `y` at the confirmation prompt.

## Select a subaccount directly

To avoid the interactive account-selection menu:

```bash
python3 scripts/onboard_gate_subaccount.py \
  --subaccount-login Reserves \
  --ip-whitelist Public egress IP of the onboarding server \
  --restart
```

The Gate login match is case-insensitive. The local account ID and dashboard username are normalized to lowercase by default.

## Customize the local account and username

```bash
python3 scripts/onboard_gate_subaccount.py \
  --subaccount-login Reserves \
  --account-id reserves \
  --display-name "EQTY Reserves" \
  --username reserves-operator \
  --ip-whitelist Public egress IP of the onboarding server \
  --restart
```

This creates the mapping:

```text
reserves-operator -> account_id reserves
```

The backend enforces this assignment. Changing `account_id` or a bot ID in the browser does not grant access to another account.

## Override child-key permissions

The defaults are recommended. To specify them explicitly:

```bash
python3 scripts/onboard_gate_subaccount.py \
  --subaccount-login Reserves \
  --permission quant \
  --permission wallet \
  --permission spot \
  --permission account \
  --ip-whitelist Public egress IP of the onboarding server \
  --restart
```

Permissions may also be comma-separated:

```bash
--permission quant,wallet,spot,account
```

## Register an existing subaccount API key

Use this mode when the subaccount API key was created manually in Gate:

```bash
python3 scripts/onboard_gate_subaccount.py \
  --api-source existing \
  --subaccount-login Reserves \
  --subaccount-user-id 52535639 \
  --account-id reserves \
  --username reserves \
  --restart
```

The script securely prompts for the existing child API key and secret.

In `existing` mode, the script does not create or delete a remote Gate key.

## Files written

### `secrets/gate_accounts.json`

Example record:

```json
{
  "id": "reserves",
  "name": "Reserves",
  "account_type": "subaccount",
  "gate_uid": "52535639",
  "api_key": "generated-or-supplied-key",
  "api_secret": "generated-or-supplied-secret",
  "enabled": true
}
```

### `secrets/dashboard_users.json`

Example record:

```json
{
  "username": "reserves",
  "password_hash": "pbkdf2_sha256$600000$...",
  "account_ids": [
    "reserves"
  ],
  "role": "account_operator",
  "enabled": true
}
```

The dashboard password is never stored in plaintext. Only a PBKDF2-SHA256 hash is saved.

## Backups and atomic writes

Unless `--no-backup` is used, the script creates timestamped backups:

```text
secrets/gate_accounts.json.bak.YYYYMMDDTHHMMSSZ
secrets/dashboard_users.json.bak.YYYYMMDDTHHMMSSZ
```

Both JSON files are written atomically with permissions `0600`. The secrets directory is set to `0700`.

If writing either local file fails, the script restores the original local files.

If a new Gate key was created and onboarding fails before the local configuration is committed, the script attempts to delete the new Gate key automatically.

## Restart behavior

With `--restart`, the script runs:

```bash
docker compose restart gate-bot-dashboard
```

A restart is required so the container reloads the updated Gate account configuration.

If the restart fails after the JSON files were saved, onboarding remains committed. Restart manually:

```bash
docker compose restart gate-bot-dashboard
```

## Verification

List dashboard users:

```bash
python3 scripts/manage_dashboard_users.py list
```

Inspect configured accounts without printing secrets:

```bash
jq '
  .accounts[] |
  {
    id,
    name,
    account_type,
    gate_uid,
    enabled,
    api_key_configured: (.api_key | length > 0),
    api_secret_configured: (.api_secret | length > 0)
  }
' secrets/gate_accounts.json
```

Test the new dashboard login:

```bash
curl -u reserves \
  -sS \
  http://192.168.1.221:8080/api/auth/me |
jq
```

Expected scope:

```json
{
  "user": {
    "username": "reserves",
    "role": "account_operator",
    "account_ids": [
      "reserves"
    ],
    "enabled": true
  }
}
```

Check bot collection for the new account:

```bash
curl -sS \
  'http://192.168.1.221:8080/api/bots?account_id=reserves' |
jq
```

An empty bot list is valid when the subaccount has no running or synchronized bots.

## Important command-line options

| Option | Description |
|---|---|
| `--api-source create` | Create a new child key through the Gate parent API. This is the default. |
| `--api-source existing` | Register an already-created child key. |
| `--subaccount-login NAME` | Select an existing Gate subaccount by login name. |
| `--subaccount-user-id ID` | Select or identify a Gate subaccount by numeric user ID. |
| `--account-id ID` | Set the local dashboard account ID. |
| `--display-name NAME` | Set the public account name shown by the dashboard. |
| `--username NAME` | Set the dashboard login username. |
| `--permission NAME` | Add a read-only child-key permission. Repeat or comma-separate. |
| `--ip-whitelist IP` | Add a public egress IP to the child key. Repeat or comma-separate. |
| `--key-mode 1` | Create a classic-account API key. This is the default. |
| `--key-mode 2` | Create a portfolio-account API key. |
| `--skip-key-test` | Skip the Gate bot endpoint test. Use only for troubleshooting. |
| `--allow-shared-account` | Allow more than one enabled account operator to share an account. |
| `--allow-empty-ip-whitelist` | Create a key without an IP restriction. Not recommended. |
| `--allow-non-global-ip` | Permit private or reserved IP addresses. Intended for special testing only. |
| `--no-backup` | Disable local timestamped backups. Not recommended. |
| `--yes` | Skip the final confirmation prompt. |
| `--restart` | Restart the dashboard service after saving. |

Display all options:

```bash
python3 scripts/onboard_gate_subaccount.py --help
```

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Onboarding completed successfully. |
| `1` | Operator cancelled at the confirmation prompt. |
| `2` | Configuration, validation, network, or Gate API failure. |
| `3` | Local onboarding completed, but the Docker Compose restart failed. |

## Troubleshooting

### `Request API key does not have quant permission`

The child key was created without the Gate bot permission.

Confirm the script uses:

```python
DEFAULT_PERMISSIONS = ("quant", "wallet", "spot", "account")
```

Also confirm `quant` is present in `ALLOWED_GATE_PERMISSIONS`.

The selected subaccount must also be allowed to use Gate Trading Bots/Quant.

### `Unsupported Gate permission: quant`

The script's allowed-permissions set is outdated. Add `quant` to `ALLOWED_GATE_PERMISSIONS`.

### `IP whitelist address ... is not a public/global IP`

Use the public egress/NAT address seen by Gate, not the private server address such as `192.168.1.221`.

Determine the public IPv4 address from the dashboard server:

```bash
curl -4 https://api.ipify.org
echo
```

### Account or username already exists

The script is intentionally add-only. It will not replace an existing account or dashboard user.

Inspect the existing records before deciding whether to remove or update them manually.

### Account already assigned to another user

The script prevents multiple active `account_operator` users from sharing the same account by default.

Use `--allow-shared-account` only when shared operation is intentional.

### Remote key created but local onboarding fails

The script attempts to delete the new Gate key automatically. When rollback fails, it prints the final characters of the key so it can be identified and deleted manually in Gate.

## Security notes

- Never commit `secrets/gate_accounts.json` or `secrets/dashboard_users.json`.
- Keep both files readable only by the deployment administrator and container startup process.
- Prefer hidden interactive prompts for parent credentials rather than environment variables.
- Do not give the parent key trading or withdrawal permissions.
- Keep the dashboard monitoring key read-only.
- Use a separate, minimally privileged management key for future stop, pause, resume, or bot-creation operations.
- Bind Gate API keys to the public egress IP of the dashboard server.

## Commit the documentation

After placing this file at `docs/ONBOARD_GATE_SUBACCOUNT.md`:

```bash
cd /opt/gate-bot-dashboard

git add docs/ONBOARD_GATE_SUBACCOUNT.md
git commit -m "Document Gate subaccount onboarding"
git push
```

