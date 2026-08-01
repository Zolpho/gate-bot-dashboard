# Gate Native Bot API Audit — 2026

This project uses only public, authenticated Gate API v4 endpoints documented in Gate's current API/official generated SDK. It deliberately does not depend on reverse-engineered mobile endpoints.

## Native BotApi operations documented by Gate

| Operation | Method and path | Dashboard usage |
|---|---|---|
| Strategy recommendations | `GET /bot/strategy/recommend` | On-demand raw inspector |
| Running portfolio | `GET /bot/portfolio/running` | Main collector |
| Portfolio detail | `GET /bot/portfolio/detail` | Detail collector |
| Stop a portfolio strategy | `POST /bot/portfolio/stop` | Implemented but locked by configuration |
| Create Spot Grid | `POST /bot/spot-grid/create` | Not exposed by this monitoring dashboard |
| Create Margin Grid | `POST /bot/margin-grid/create` | Not exposed |
| Create Infinite Grid | `POST /bot/infinite-grid/create` | Not exposed |
| Create Futures Grid | `POST /bot/futures-grid/create` | Not exposed |
| Create Spot Martingale | `POST /bot/spot-martingale/create` | Not exposed |
| Create Contract Martingale | `POST /bot/contract-martingale/create` | Not exposed |

Bot creation was intentionally excluded from the browser. It deploys capital and belongs in a separate, explicitly write-enabled workflow after monitoring has been reconciled with the Gate application.

## Running-list request

Documented filters:

- `strategy_type`
- `market`
- `page` (default 1)
- `page_size` (default 20, maximum 50)

The collector requests 50 per page and follows pagination until all returned running strategies have been collected.

## Running-list item

Known fields mapped by the project:

- `strategy_id`
- `strategy_type`
- `strategy_name`
- `market`
- `status`
- `pnl`
- `pnl_rate`
- `invest_amount`
- `created_at`

## Detail request

Required query parameters:

- `strategy_id`
- `strategy_type`

Known top-level response fields:

- `strategy_id`
- `strategy_type`
- `market`
- `status`
- `base_info`
- `metrics`
- `position`
- `stop_supported`

## Flexible maps

Gate's April 2026 SDK changelog records `base_info`, `metrics`, and `position` as loose string-key maps. The API's documented known values include:

### `base_info`

- `strategy_name`
- `created_at`
- `running_duration`
- `invest_amount`
- `total_profit`
- `profit_rate`

### `metrics`

- `grid_profit`
- `floating_pnl`
- `arbitrage_count`
- `price_range`
- `grid_count`
- `estimated_liquidation_price`
- `price_floor`
- `grid_profit_rate`
- `realized_pnl`
- `finished_rounds`
- `avg_cost`
- `take_profit_price`
- `maintenance_margin_ratio`

### `position`

- `amount`
- `entry_price`
- `quote_amount`
- `position_value`
- `margin`
- `side`

The dashboard maps these known keys and several harmless aliases, while always storing the unmodified maps. This is important because Spot Grid, Futures Grid, and Martingale strategies do not necessarily return the same metrics.

## What is calculated locally

These are not assumed to be direct Gate fields:

- portfolio history
- per-bot equity history
- 24-hour and 7-day changes
- peak value
- current and maximum drawdown
- stale-data duration
- liquidation-distance percentage based on entry and estimated liquidation prices
- local rule/event history

## Account reconciliation endpoints

The optional account inspector calls:

- `GET /wallet/total_balance`
- `GET /spot/accounts`
- `GET /futures/usdt/accounts`
- `GET /futures/usdt/positions`

Failures are isolated per endpoint so one unavailable permission does not hide the others.

## Not claimed

The implementation does not claim that Gate returns:

- every historic/stopped strategy
- every public Marketplace strategy
- all mobile-app leaderboard data
- a native bot WebSocket stream
- identical metrics for every strategy type
- a complete daily equity curve before local snapshots exist

Official references:

- https://www.gate.com/docs/developers/apiv4/en/
- https://github.com/gate/gateapi-python
