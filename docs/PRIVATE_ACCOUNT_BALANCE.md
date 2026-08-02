# Private Subaccount Balance Panel

The dashboard keeps normal monitoring public and reveals private Gate account balances only after an account operator signs in.

## User experience

Before login, the browser does not request private balance data and the panel is hidden.

After a successful **Account login**, the Overview page shows **My subaccount balance** below the public portfolio KPI cards. The panel is scoped to the authenticated user's assigned Gate account.

Selecting **Lock account** clears the authorization value and private balance payload from browser memory and hides the panel.

## Information shown

The panel displays:

- total Gate account value in USDT;
- available, locked, total, and estimated value of spot USDT;
- available, locked, total, price, and estimated value of spot EQTY;
- the Gate `quant` account value used by native trading bots;
- other non-zero spot tokens and their estimated USDT values;
- tracked bot initial capital, current value, PnL, and running/tracked counts;
- a per-account-type balance breakdown returned by Gate;
- an expandable spot-asset table.

The Gate wallet total is authoritative for the total account value. Quant/bot funds and individual spot-token values are shown as components and are not added to that total again.

## Access control

The protected route is:

```http
GET /api/me/balance
```

For an account operator assigned to one account, no account ID is required. The backend derives ownership from the authenticated dashboard user.

A user assigned to multiple accounts, or a super administrator, may select one authorized account:

```http
GET /api/me/balance?account_id=zolnode
```

The selected account must appear in the authenticated user's `account_ids`, unless the user is a super administrator. A cross-account request returns `403 Forbidden`.

A forced refresh bypasses the dashboard's short local cache:

```http
GET /api/me/balance?refresh=true
```

## Gate endpoints

The backend reads:

```text
GET /api/v4/wallet/total_balance?currency=USDT
GET /api/v4/spot/accounts
GET /api/v4/spot/tickers
```

The subaccount monitoring key requires these read-only permissions:

```text
quant
wallet
spot
account
```

`quant` is required for native Gate bot data. `wallet` supplies the estimated total and account-type breakdown. `spot` supplies per-token available and locked balances. `account` remains useful for account metadata elsewhere in the dashboard.

## Valuation

Spot tokens are valued in this order:

1. fixed `1 USDT` for USDT;
2. direct `TOKEN_USDT` ticker;
3. inverse `USDT_TOKEN` ticker;
4. a bridge through BTC, ETH, or USDC when matching Gate markets exist.

Assets without a supported price path remain visible with their quantity and an unvalued marker. They are excluded from calculated spot-token subtotals, but the Gate wallet total remains visible.

## Cache settings

Configure the dashboard cache in `.env`:

```env
BALANCE_CACHE_SECONDS=30
BALANCE_DUST_USDT=0.01
```

- `BALANCE_CACHE_SECONDS` accepts `0` through `300`.
- `BALANCE_DUST_USDT` marks very small asset values as dust for presentation purposes.
- Gate may independently cache its total-balance result.

The browser also avoids repeating a private-balance request for approximately 25 seconds unless the user selects **Refresh balance**.

## Files

The feature is implemented in:

```text
app/api/me.py
app/balances.py
app/gate_client.py
app/config.py
app/main.py
frontend/index.html
frontend/app.js
frontend/private-balance.css
tests/test_balances.py
tests/test_api.py
```

## Verification

Unauthenticated requests must fail:

```bash
curl -i https://gatebots-api.eqty.pro/api/me/balance
```

Expected:

```text
HTTP/2 401
```

An account operator can read only their own account:

```bash
curl -u zolnode \
  -sS \
  https://gatebots-api.eqty.pro/api/me/balance |
jq '{account_id,total_value,quant_value,summary,bot_allocation}'
```

A cross-account request must fail:

```bash
curl -u zolnode \
  -i \
  'https://gatebots-api.eqty.pro/api/me/balance?account_id=arnold'
```

Expected:

```text
HTTP/2 403
```

## Security notes

- The endpoint never returns API keys or secrets.
- The browser sends no private-balance request before login.
- Account ownership is derived and verified on the backend.
- Private data is cleared from JavaScript memory when the account session is locked.
- The monitoring key remains read-only.
