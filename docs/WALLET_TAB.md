# Authenticated Wallet tab

The private Gate account card is displayed in a dedicated **Wallet**
tab instead of the public Overview.

## Visibility

Guests see the existing public navigation only. The Wallet navigation
item is added after successful account login and removed immediately
when the account is locked.

Hiding the tab is a user-interface control only. FastAPI continues to
enforce account-scoped authentication on all private wallet routes.

## Contents

The Wallet tab contains the existing private account functionality:

- total Gate subaccount value;
- spot balances and asset details;
- Gate bot/quant allocation;
- dynamic deposit currency and network selection;
- account-specific deposit addresses and QR codes;
- locally persisted Gate deposit history.

Existing element IDs are preserved, so the balance, deposit and
deposit-history API integrations remain unchanged.

## Navigation behavior

- Successful login opens the Wallet tab.
- Locking the account clears private balances, deposit state and
  deposit history.
- Locking while Wallet is active returns the user to Overview.
- A guest opening `#wallet` directly is redirected to `#overview`.
- The URL fragment tracks the active tab.
- Returning to Wallet refreshes private balance and deposit history.

## Security boundary

The frontend never treats tab visibility as authorization. The
authenticated endpoints remain the security boundary:

- `/api/me/balance`
- `/api/me/deposit/...`
- `/api/me/deposits`
- `/api/me/deposits/sync`
