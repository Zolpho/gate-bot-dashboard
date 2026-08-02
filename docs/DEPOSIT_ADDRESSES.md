# Account-scoped Gate deposit addresses

The authenticated private-balance panel includes a Gate-style **Deposit**
dialog. It loads Gate's currency catalogue dynamically, lets the user search
API-supported currencies, and requires an explicit network selection before
revealing the assigned subaccount's address and QR code.

## API routes

| Route | Authentication | Purpose |
|---|---|---|
| `GET /api/deposit/currencies` | Public | Cached searchable Gate currency catalogue |
| `GET /api/me/deposit/{currency}/networks` | Account login | Current networks and deposit status |
| `GET /api/me/deposit/{currency}?chain=...` | Account login | Selected account/network address, memo and QR |

The backend derives the Gate account from the authenticated dashboard user.
An account operator cannot request another user's subaccount address.

## Gate API calls

- `GET /spot/currencies` for the public catalogue.
- `GET /wallet/currency_chains` for current network and deposit status.
- `GET /wallet/deposit_address` for the authenticated subaccount address.

Gate may omit very low-liquidity or extremely low-value tokens from wallet
APIs. Such assets may need to be handled through Gate Web or App.

## QR and memo handling

QR codes are generated locally in FastAPI with Segno and returned as SVG data
URIs. No address is sent to a third-party QR service. The QR contains only the
address. A Gate payment ID, memo, or tag is displayed separately and must also
be copied when Gate requires it.

## Permissions

The subaccount API key requires **Wallet read-only**. It does not require
withdrawals or Wallet read-write. Existing `quant`, `spot`, and `account`
read-only permissions remain useful for bot monitoring and balances.

## Safety behavior

- Networks are never automatically selected.
- Disabled networks remain visible but cannot be selected.
- An address is requested only after the user explicitly selects a network.
- Address and QR data are kept only in process/browser memory.
- The data is cleared when the account is locked or the deposit dialog closes.
- The user is warned to send only the selected asset on the selected network.

## Cache settings

```env
DEPOSIT_CATALOG_CACHE_SECONDS=900
DEPOSIT_ADDRESS_CACHE_SECONDS=300
DEPOSIT_FAVORITES=USDT,EQTY,BTC,ETH
```
