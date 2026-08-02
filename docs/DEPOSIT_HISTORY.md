# Persisted Gate deposit history

The dashboard stores Gate-confirmed deposits in SQLite. Opening the deposit-address dialog does **not** create a deposit record. A record is stored only after Gate returns it from `GET /wallet/deposits`.

## Data model

- `deposit_addresses` stores the last verified account/currency/network address and memo. QR images are not stored.
- `deposit_records` stores Gate deposit records and status changes.
- `deposit_sync_states` stores the last successful sync, reconciliation time, query window and error.

Deposit amounts use a high-precision decimal database column and are serialized to the API as strings.

## Synchronization

The existing background bot collector also synchronizes deposits for each enabled Gate account. Deposit failures are recorded separately and do not make a successful bot synchronization fail.

- Initial sync: previous 30 days.
- Incremental sync: from the last success minus a one-hour overlap.
- Reconciliation: full 30-day window once every 24 hours.
- Gate query windows never exceed 30 days.
- Pagination is capped at 500 records per synchronization, matching Gate's documented query limit.

## API

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/me/deposits` | Account-scoped deposit list and sync state |
| `GET` | `/api/me/deposits/{id}` | One account-scoped deposit including stored raw Gate data |
| `POST` | `/api/me/deposits/sync` | Incremental manual sync |
| `POST` | `/api/me/deposits/sync?full=true` | Full 30-day reconciliation |

Filters include `currency`, `status`, `limit`, and `offset`.

## Permissions

The Gate subaccount key needs **Wallet read-only**. Withdrawal permission is not needed.

## Withdrawal scope

Withdrawal execution is intentionally not included. Gate documents that a subaccount API key cannot call `POST /withdrawals`. A future withdrawal design therefore needs a separate main-account signing service, stronger approval controls, address allowlisting, limits, audit logs and a separate write-enabled key. Read-only withdrawal history can later use `GET /wallet/withdrawals` under Wallet read-only permission.
