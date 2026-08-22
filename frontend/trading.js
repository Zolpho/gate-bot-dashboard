'use strict';

const tradingState = {
  catalog: null,
  accountId: '',
  pair: '',
  interval: '5m',
  snapshot: null,
  trades: [],
  bookInterval: "0",
  marketSideTab: "book",
  loadingTrades: false,
  chart: null,
  series: null,
  volumeSeries: null,
  resizeObserver: null,
  refreshTimer: null,
  candleTimer: null,
  loadingCatalog: false,
  loadingSnapshot: false,
  loadingCandles: false,
  openOrders: [],
  recentOrders: [],
  openOrdersLoaded: false,
  recentOrdersLoaded: false,
  openOrdersError: '',
  recentOrdersError: '',
  loadingOpenOrders: false,
  loadingRecentOrders: false,
  persistentCancelPending: new Set(),
  persistentCancelFrozen: new Set(),
};


function tradingSetError(message = '') {
  const element = $('#tradingError');

  if (!element) return;

  element.textContent = message;

  element.classList.toggle(
    'hidden',
    !message,
  );
}


function tradingNumeric(value) {
  const number = Number(value);

  return Number.isFinite(number)
    ? number
    : null;
}


function tradingBookIntervals() {
  const precision = Number(
    tradingPairDefinition()?.precision
  );

  if (
    !Number.isInteger(precision)
    || precision < 0
    || precision > 12
  ) {
    return [
      {
        value: '0',
        label: 'Exact',
      },
    ];
  }

  const rows = [
    {
      value: '0',
      label: 'Exact',
    },
  ];

  for (
    let offset = 0;
    offset < 4;
    offset += 1
  ) {
    const digits = Math.max(
      0,
      precision - offset,
    );

    const value = (
      10 ** (-digits)
    ).toFixed(digits);

    if (
      !rows.some(item => item.value === value)
    ) {
      rows.push({
        value,
        label: value,
      });
    }
  }

  return rows;
}


function tradingPopulateBookIntervals() {
  const select = $('#tradingBookInterval');

  if (!select) return;

  const options = tradingBookIntervals();

  const allowed = new Set(
    options.map(item => item.value)
  );

  if (
    !allowed.has(
      tradingState.bookInterval
    )
  ) {
    tradingState.bookInterval = '0';
  }

  select.innerHTML = options
    .map(item => (
      `<option value="${escapeHtml(item.value)}">`
      + `${escapeHtml(item.label)}`
      + '</option>'
    ))
    .join('');

  select.value = tradingState.bookInterval;
}


function tradingRenderMarketSideTabs() {
  $$(
    '[data-trading-market-tab]'
  ).forEach(button => {
    button.classList.toggle(
      'active',
      button.dataset.tradingMarketTab
      === tradingState.marketSideTab,
    );
  });

  $('#tradingBookView')?.classList.toggle(
    'hidden',
    tradingState.marketSideTab !== 'book',
  );

  $('#tradingTradesView')?.classList.toggle(
    'hidden',
    tradingState.marketSideTab !== 'trades',
  );
}


function tradingPairDefinition() {
  const pair = String(
    tradingState.pair || ''
  ).toUpperCase();

  return (
    tradingState.catalog?.pairs || []
  ).find(item => item.id === pair) || null;
}


function tradingPriceDigits() {
  const precision = Number(
    tradingPairDefinition()?.precision
  );

  if (
    Number.isInteger(precision)
    && precision >= 0
    && precision <= 12
  ) {
    return precision;
  }

  return 8;
}


function tradingFormatPrice(value) {
  const number = tradingNumeric(value);

  if (number === null) return '—';

  const digits = tradingPriceDigits();

  return new Intl.NumberFormat(
    'en-US',
    {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    },
  ).format(number);
}


function tradingFormatAmount(value) {
  const number = tradingNumeric(value);

  if (number === null) return '—';

  const absolute = Math.abs(number);

  const digits = (
    absolute >= 100_000
      ? 0
      : absolute >= 1_000
        ? 2
        : absolute >= 1
          ? 4
          : 8
  );

  return new Intl.NumberFormat(
    'en-US',
    {
      maximumFractionDigits: digits,
    },
  ).format(number);
}


function tradingFormatVolume(value) {
  const number = tradingNumeric(value);

  if (number === null) return '—';

  return new Intl.NumberFormat(
    'en-US',
    {
      notation: (
        Math.abs(number) >= 100_000
          ? 'compact'
          : 'standard'
      ),
      maximumFractionDigits: 2,
    },
  ).format(number);
}


function tradingSetLoading(
  element,
  loading,
  normalText,
) {
  if (!element) return;

  element.disabled = loading;
  element.textContent = (
    loading
      ? 'Loading…'
      : normalText
  );
}


function tradingAuthorizedAccountIds() {
  return new Set(
    (
      tradingState.catalog?.accounts
      || []
    ).map(
      account => account.id
    ),
  );
}


function tradingPopulateCatalog() {
  const catalog = tradingState.catalog;

  if (!catalog) return;

  const accountSelect = $('#tradingAccount');
  const pairInput = $('#tradingPair');
  const pairOptions = $('#tradingPairOptions');

  const accounts = catalog.accounts || [];
  const pairs = catalog.pairs || [];

  accountSelect.innerHTML = accounts
    .map(account => (
      `<option value="${escapeHtml(account.id)}">`
      + `${escapeHtml(account.name || account.id)}`
      + ` (${escapeHtml(account.id)})`
      + '</option>'
    ))
    .join('');

  const authorizedIds = new Set(
    accounts.map(account => account.id)
  );

  let accountId = tradingState.accountId;

  if (
    state.selectedAccount
    && authorizedIds.has(
      state.selectedAccount
    )
  ) {
    accountId = state.selectedAccount;
  }

  if (!authorizedIds.has(accountId)) {
    accountId = accounts[0]?.id || '';
  }

  tradingState.accountId = accountId;
  accountSelect.value = accountId;

  pairOptions.innerHTML = pairs
    .map(pair => (
      `<option value="${escapeHtml(pair.id)}">`
      + `${escapeHtml(pair.base)} / `
      + `${escapeHtml(pair.quote)}`
      + '</option>'
    ))
    .join('');

  const pairIds = new Set(
    pairs.map(pair => pair.id)
  );

  let pair = String(
    tradingState.pair || ''
  ).toUpperCase();

  if (!pairIds.has(pair)) {
    pair = String(
      catalog.default_pair
      || 'EQTY_USDT'
    ).toUpperCase();
  }

  tradingState.pair = pair;
  pairInput.value = pair;

  tradingRenderIntervalButtons();
  tradingPopulateBookIntervals();
  tradingRenderMarketSideTabs();

  tradingResetPersistentOrders();

  window.renderTradingLimitOrderTicket?.();
}


function tradingRenderIntervalButtons() {
  $$(
    '[data-trading-interval]'
  ).forEach(button => {
    button.classList.toggle(
      'active',
      button.dataset.tradingInterval
      === tradingState.interval,
    );
  });
}


function tradingValidatePair() {
  const input = $('#tradingPair');

  const pair = String(
    input?.value || ''
  )
    .trim()
    .toUpperCase()
    .replace(/[-/]/g, '_');

  const pairs = (
    tradingState.catalog?.pairs
    || []
  );

  if (
    !pairs.some(item => item.id === pair)
  ) {
    throw new Error(
      `Unknown or unavailable Gate spot pair: ${pair}`
    );
  }

  input.value = pair;
  tradingState.pair = pair;

  return pair;
}


function tradingEnsureChart() {
  const container = $('#tradingChart');

  if (!container) return false;

  if (tradingState.chart) {
    return true;
  }

  if (
    !window.LightweightCharts
    || !window.LightweightCharts.createChart
  ) {
    tradingSetError(
      'Trading chart library did not load.'
    );

    return false;
  }

  const css = getComputedStyle(
    document.documentElement
  );

  const textColor = css
    .getPropertyValue('--muted')
    .trim();

  const borderColor = css
    .getPropertyValue('--border')
    .trim();

  const positive = css
    .getPropertyValue('--positive')
    .trim();

  const negative = css
    .getPropertyValue('--negative')
    .trim();

  const chart = window.LightweightCharts
    .createChart(
      container,
      {
        autoSize: true,

        layout: {
          background: {
            type: window.LightweightCharts
              .ColorType.Solid,
            color: 'transparent',
          },
          textColor,
          attributionLogo: false,
        },

        grid: {
          vertLines: {
            color: borderColor,
          },
          horzLines: {
            color: borderColor,
          },
        },

        rightPriceScale: {
          borderColor,
        },

        timeScale: {
          borderColor,
          timeVisible: true,
          secondsVisible: false,
          rightOffset: 5,
        },

        crosshair: {
          mode: window.LightweightCharts
            .CrosshairMode.Normal,
        },
      },
    );

  const series = chart.addSeries(
    window.LightweightCharts.CandlestickSeries,
    {
      upColor: positive,
      downColor: negative,
      borderUpColor: positive,
      borderDownColor: negative,
      wickUpColor: positive,
      wickDownColor: negative,
    },
  );

  const volumeSeries = chart.addSeries(
    window.LightweightCharts.HistogramSeries,
    {
      priceFormat: {
        type: 'volume',
      },

      priceScaleId: '',
    },
  );

  volumeSeries.priceScale().applyOptions({
    scaleMargins: {
      top: 0.78,
      bottom: 0,
    },
  });

  series.priceScale().applyOptions({
    scaleMargins: {
      top: 0.05,
      bottom: 0.25,
    },
  });

  tradingState.chart = chart;
  tradingState.series = series;
  tradingState.volumeSeries = volumeSeries;

  tradingState.resizeObserver = (
    new ResizeObserver(() => {
      chart.timeScale().scrollToRealTime();
    })
  );

  tradingState.resizeObserver.observe(
    container
  );

  return true;
}


function tradingUpdateChartPrecision() {
  if (!tradingState.series) return;

  const digits = tradingPriceDigits();

  const minMove = 10 ** (-digits);

  tradingState.series.applyOptions({
    priceFormat: {
      type: 'price',
      precision: digits,
      minMove,
    },
  });
}


function tradingRenderCandles(candles) {
  const message = $('#tradingChartMessage');

  if (!tradingEnsureChart()) {
    if (message) {
      message.textContent = (
        'Unable to initialize chart.'
      );

      message.classList.remove('hidden');
    }

    return;
  }

  const sourceRows = (
    Array.isArray(candles)
      ? candles
      : []
  );

  const rows = sourceRows
    .map(item => ({
      time: Number(item.time),
      open: Number(item.open),
      high: Number(item.high),
      low: Number(item.low),
      close: Number(item.close),
    }))
    .filter(item => (
      Number.isFinite(item.time)
      && Number.isFinite(item.open)
      && Number.isFinite(item.high)
      && Number.isFinite(item.low)
      && Number.isFinite(item.close)
    ));

  const css = getComputedStyle(
    document.documentElement
  );

  const positive = css
    .getPropertyValue('--positive')
    .trim();

  const negative = css
    .getPropertyValue('--negative')
    .trim();

  const volumeRows = sourceRows
    .map(item => {
      const time = Number(item.time);
      const open = Number(item.open);
      const close = Number(item.close);
      const volume = Number(
        item.base_volume ?? 0
      );

      if (
        !Number.isFinite(time)
        || !Number.isFinite(open)
        || !Number.isFinite(close)
        || !Number.isFinite(volume)
      ) {
        return null;
      }

      return {
        time,
        value: Math.max(0, volume),
        color: (
          close >= open
            ? positive
            : negative
        ),
      };
    })
    .filter(Boolean);

  tradingUpdateChartPrecision();

  tradingState.series.setData(rows);

  tradingState.volumeSeries?.setData(
    volumeRows
  );

  const latestVolume = (
    volumeRows.length
      ? volumeRows[
          volumeRows.length - 1
        ].value
      : null
  );

  const volumeValue = $(
    '#tradingVolumeValue'
  );

  if (volumeValue) {
    volumeValue.textContent = (
      latestVolume === null
        ? '—'
        : tradingFormatVolume(
            latestVolume
          )
    );
  }

  if (!rows.length) {
    tradingState.volumeSeries?.setData([]);

    const volumeValue = $(
      '#tradingVolumeValue'
    );

    if (volumeValue) {
      volumeValue.textContent = '—';
    }

    if (message) {
      message.textContent = (
        'No candlestick data returned '
        + 'for this market and interval.'
      );

      message.classList.remove('hidden');
    }

    return;
  }

  message?.classList.add('hidden');

  tradingState.chart
    .timeScale()
    .fitContent();
}


function tradingBookRows(
  rows,
  side,
) {
  const normalized = (
    Array.isArray(rows)
      ? rows
      : []
  );

  if (!normalized.length) {
    return (
      '<div class="empty-state">'
      + 'No order-book levels'
      + '</div>'
    );
  }

  const amounts = normalized
    .map(item => Number(item.amount))
    .filter(Number.isFinite);

  const maxAmount = Math.max(
    1,
    ...amounts,
  );

  return normalized
    .map(item => {
      const amount = Number(
        item.amount
      );

      const depth = (
        Number.isFinite(amount)
          ? Math.max(
              2,
              Math.min(
                100,
                amount / maxAmount * 100,
              ),
            )
          : 2
      );

      const price = Number(
        item.price
      );

      const total = (
        Number.isFinite(price)
        && Number.isFinite(amount)
          ? price * amount
          : null
      );

      return `
        <button
          type="button"
          class="trading-book-row ${side}"
          data-trading-book-price="${escapeHtml(
            String(item.price)
          )}"
          data-trading-book-side="${escapeHtml(side)}"
          title="Copy this price to the limit order"
        >
          <i
            class="trading-book-depth"
            style="width:${depth.toFixed(2)}%"
            aria-hidden="true"
          ></i>

          <span class="trading-book-price">
            ${escapeHtml(
              tradingFormatPrice(
                item.price
              )
            )}
          </span>

          <span>
            ${escapeHtml(
              tradingFormatAmount(
                item.amount
              )
            )}
          </span>

          <span>
            ${escapeHtml(
              total === null
                ? '—'
                : tradingFormatAmount(
                    total
                  )
            )}
          </span>
        </button>
      `;
    })
    .join('');
}


function tradingRenderSnapshot() {
  const data = tradingState.snapshot;

  if (!data) return;

  const ticker = data.ticker || {};
  const book = data.order_book || {};

  const pair = data.pair || {};
  const base = pair.base || '';
  const quote = pair.quote || '';

  const last = (
    ticker.last
    ?? book.best_bid
    ?? book.best_ask
  );

  $('#tradingMarketTitle').textContent = (
    `${base} / ${quote}`
  );

  $('#tradingLastPrice').textContent = (
    tradingFormatPrice(last)
  );

  const change = tradingNumeric(
    ticker.change_percentage
  );

  const changeElement = $('#tradingChange');

  changeElement.textContent = (
    change === null
      ? '—'
      : `${change > 0 ? '+' : ''}${change.toFixed(2)}%`
  );

  changeElement.classList.remove(
    'positive',
    'negative',
  );

  if (change !== null) {
    if (change > 0) {
      changeElement.classList.add(
        'positive'
      );
    } else if (change < 0) {
      changeElement.classList.add(
        'negative'
      );
    }
  }

  $('#tradingBestBid').textContent = (
    tradingFormatPrice(
      book.best_bid
      ?? ticker.highest_bid
    )
  );

  $('#tradingBestAsk').textContent = (
    tradingFormatPrice(
      book.best_ask
      ?? ticker.lowest_ask
    )
  );

  $('#tradingHigh24h').textContent = (
    tradingFormatPrice(
      ticker.high_24h
    )
  );

  $('#tradingLow24h').textContent = (
    tradingFormatPrice(
      ticker.low_24h
    )
  );

  $('#tradingBaseVolume').textContent = (
    `${tradingFormatVolume(
      ticker.base_volume
    )} ${base}`
  );

  $('#tradingQuoteVolume').textContent = (
    `${tradingFormatVolume(
      ticker.quote_volume
    )} ${quote}`
  );

  const asks = (
    book.asks || []
  )
    .slice(0, 10)
    .reverse();

  const bids = (
    book.bids || []
  )
    .slice(0, 10);

  $('#tradingAsks').innerHTML = (
    tradingBookRows(
      asks,
      'ask',
    )
  );

  $('#tradingBids').innerHTML = (
    tradingBookRows(
      bids,
      'bid',
    )
  );

  const spread = tradingFormatPrice(
    book.spread
  );

  const spreadPercent = tradingNumeric(
    book.spread_percent
  );

  $('#tradingSpread').textContent = (
    spreadPercent === null
      ? spread
      : (
          `${spread} · `
          + `${spreadPercent.toFixed(4)}%`
        )
  );

  const buyPercent = tradingNumeric(
    book.buy_percent
  );

  const sellPercent = tradingNumeric(
    book.sell_percent
  );

  const buy = Math.max(
    0,
    Math.min(
      100,
      buyPercent ?? 0,
    ),
  );

  const sell = Math.max(
    0,
    Math.min(
      100,
      sellPercent ?? 0,
    ),
  );

  $('#tradingBuyPercent').textContent = (
    `B ${buy.toFixed(2)}%`
  );

  $('#tradingSellPercent').textContent = (
    `${sell.toFixed(2)}% S`
  );

  $('#tradingBuyBar').style.width = (
    `${buy}%`
  );

  $('#tradingSellBar').style.width = (
    `${sell}%`
  );

  const balances = data.balances || {};

  const baseBalance = (
    balances.base || {}
  );

  const quoteBalance = (
    balances.quote || {}
  );

  $('#tradingBaseBalanceLabel').textContent = (
    `${base} available`
  );

  $('#tradingBaseAvailable').textContent = (
    `${tradingFormatAmount(
      baseBalance.available
    )} ${base}`
  );

  $('#tradingBaseLocked').textContent = (
    `${tradingFormatAmount(
      baseBalance.locked
    )} ${base} locked`
  );

  $('#tradingQuoteBalanceLabel').textContent = (
    `${quote} available`
  );

  $('#tradingQuoteAvailable').textContent = (
    `${tradingFormatAmount(
      quoteBalance.available
    )} ${quote}`
  );

  $('#tradingQuoteLocked').textContent = (
    `${tradingFormatAmount(
      quoteBalance.locked
    )} ${quote} locked`
  );

  $('#tradingBookSubtitle').textContent = (
    `${tradingState.pair} · top 10 levels`
  );

  const totalHeader = $(
    '#tradingBookTotalHeader'
  );

  if (totalHeader) {
    totalHeader.textContent = (
      `Total (${quote})`
    );
  }

  $('#tradingBalanceSubtitle').textContent = (
    `Gate spot · ${tradingState.accountId}`
  );

  window.renderTradingLimitOrderTicket?.();
}


function tradingFormatTradeTime(value) {
  const milliseconds = Number(value);

  if (!Number.isFinite(milliseconds)) {
    return '—';
  }

  const date = new Date(milliseconds);

  if (Number.isNaN(date.getTime())) {
    return '—';
  }

  return date.toLocaleTimeString(
    [],
    {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    },
  );
}


function tradingRenderTrades() {
  const element = $('#tradingTrades');

  if (!element) return;

  const rows = tradingState.trades || [];

  if (!rows.length) {
    element.innerHTML = (
      '<div class="empty-state">'
      + 'No recent trades returned.'
      + '</div>'
    );

    return;
  }

  element.innerHTML = rows
    .slice(0, 30)
    .map(trade => {
      const side = (
        trade.side === 'sell'
          ? 'sell'
          : 'buy'
      );

      return `
        <div class="trading-trade-row ${side}">
          <span class="price">
            ${escapeHtml(
              tradingFormatPrice(
                trade.price
              )
            )}
          </span>

          <span>
            ${escapeHtml(
              tradingFormatAmount(
                trade.amount
              )
            )}
          </span>

          <span>
            ${escapeHtml(
              tradingFormatAmount(
                trade.total
              )
            )}
          </span>

          <span>
            ${escapeHtml(
              tradingFormatTradeTime(
                trade.time_ms
              )
            )}
          </span>
        </div>
      `;
    })
    .join('');
}


async function tradingLoadTrades({
  quiet = false,
} = {}) {
  if (
    tradingState.loadingTrades
    || state.activeTab !== 'trading'
    || tradingState.marketSideTab !== 'trades'
    || !state.adminAuthorization
    || !tradingState.accountId
    || !tradingState.pair
  ) {
    return;
  }

  tradingState.loadingTrades = true;

  try {
    const result = await adminApi(
      withParams(
        '/api/trading/trades',
        {
          account_id: tradingState.accountId,
          pair: tradingState.pair,
          limit: 40,
        },
      ),
    );

    tradingState.trades = (
      result.trades || []
    );

    tradingRenderTrades();

  } catch (error) {
    if (!quiet) {
      showToast(
        error.message
        || 'Unable to load recent trades.',
        true,
      );
    }

  } finally {
    tradingState.loadingTrades = false;
  }
}


function tradingOrderStatusLabel(
  value,
) {
  const normalized = String(
    value || ''
  ).trim().toLowerCase();

  const labels = {
    confirmed_open: 'Open',
    confirmed_closed: 'Closed',
    confirmed_cancelled: 'Cancelled',
    submitted: 'Submitted',
    cancelling: 'Cancelling',
    cancelled: 'Cancelled',
    already_cancelled: 'Cancelled',
    rejected: 'Rejected',
    local_rejected: 'Rejected before exchange',
    trading_disabled: 'Trading disabled',
    uncertain: 'Needs review',
    attention: 'Needs review',
    lookup_error: 'Lookup error',
  };

  if (labels[normalized]) {
    return labels[normalized];
  }

  if (!normalized) {
    return '—';
  }

  return normalized
    .replace(/_/g, ' ')
    .replace(
      /\b\w/g,
      character => character.toUpperCase(),
    );
}



function tradingOrderIdLabel(
  value,
) {
  const text = String(
    value || ''
  ).trim();

  if (!text) {
    return '—';
  }

  if (text.length <= 14) {
    return text;
  }

  return (
    text.slice(0, 7)
    + '…'
    + text.slice(-6)
  );
}


function tradingOrderTime(
  value,
) {
  if (
    value === null
    || value === undefined
    || value === ''
  ) {
    return '—';
  }

  let date;

  const numeric = Number(value);

  if (
    Number.isFinite(numeric)
    && String(value).trim() !== ''
  ) {
    const milliseconds = (
      numeric < 1e12
        ? numeric * 1000
        : numeric
    );

    date = new Date(milliseconds);

  } else {
    date = new Date(
      String(value)
    );
  }

  if (Number.isNaN(date.getTime())) {
    return '—';
  }

  return date.toLocaleString(
    [],
    {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    },
  );
}


function tradingResetPersistentOrders() {
  tradingState.openOrders = [];
  tradingState.recentOrders = [];

  tradingState.openOrdersLoaded = false;
  tradingState.recentOrdersLoaded = false;

  tradingState.openOrdersError = '';
  tradingState.recentOrdersError = '';

  tradingRenderOpenOrders();
  tradingRenderRecentOrders();
}



function tradingPersistentCancelEligibility(
  row,
) {
  const gate = (
    row?.gate_order || {}
  );

  const request = (
    row?.request || {}
  );

  const capabilities = (
    tradingState
      .limitOrderExecutionCapabilities
    || {}
  );

  const requestId = String(
    request.request_id || ''
  ).trim();

  const gateOrderId = String(
    row?.gate_order_id
    || gate.id
    || ''
  ).trim();

  const localGateOrderId = String(
    request.gate_order_id || ''
  ).trim();

  const gateStatus = String(
    row?.gate_status
    || gate.status
    || ''
  ).trim().toLowerCase();

  const finishAs = String(
    gate.finish_as || ''
  ).trim().toLowerCase();

  const accountId = String(
    request.account_id || ''
  ).trim().toLowerCase();

  const pair = String(
    request.pair || ''
  ).trim().toUpperCase();

  const configuredAccounts = new Set(
    (
      capabilities
        .configured_account_ids
      || []
    ).map(
      value => String(
        value || ''
      ).trim().toLowerCase()
    )
  );

  const authorizedAccounts = new Set(
    (
      capabilities
        .authorized_account_ids
      || []
    ).map(
      value => String(
        value || ''
      ).trim().toLowerCase()
    )
  );

  if (!row?.managed) {
    return {
      allowed: false,
      label: '—',
      reason: 'unmanaged',
    };
  }

  if (
    row?.identity_conflict
    || row?.state_conflict
  ) {
    return {
      allowed: false,
      label: 'Review',
      reason: 'conflict',
    };
  }

  if (row?.cancellation) {
    const status = String(
      row.cancellation.status || ''
    ).trim();

    return {
      allowed: false,
      label: (
        status
          ? tradingOrderStatusLabel(
              status
            )
          : 'Cancellation recorded'
      ),
      reason: 'existing_cancellation',
    };
  }

  if (
    !requestId
    || !gateOrderId
    || !/^[0-9]+$/.test(gateOrderId)
  ) {
    return {
      allowed: false,
      label: 'Unavailable',
      reason: 'identity_missing',
    };
  }

  /*
   * Fail closed if the durable audited Gate ID
   * is not exactly the live Gate ID.
   *
   * This also means a text-only recovered order
   * remains visible but cannot be cancelled from
   * the persistent table until the durable audit
   * itself contains the real Gate order ID.
   */
  if (
    !localGateOrderId
    || localGateOrderId !== gateOrderId
  ) {
    return {
      allowed: false,
      label: 'Review',
      reason: 'gate_id_mismatch',
    };
  }

  if (
    gateStatus !== 'open'
    || ![
      '',
      'open',
    ].includes(finishAs)
  ) {
    return {
      allowed: false,
      label: 'Not open',
      reason: 'not_open',
    };
  }

  if (
    request.write_performed !== true
    || String(
      request.order_type || ''
    ).toLowerCase() !== 'limit'
  ) {
    return {
      allowed: false,
      label: 'Unavailable',
      reason: 'audit_not_cancellable',
    };
  }

  if (
    accountId !== (
      tradingState.accountId || ''
    ).toLowerCase()
    || pair !== (
      tradingState.pair || ''
    ).toUpperCase()
  ) {
    return {
      allowed: false,
      label: 'Review',
      reason: 'scope_mismatch',
    };
  }

  if (
    tradingState
      .persistentCancelPending
      .has(requestId)
  ) {
    return {
      allowed: false,
      label: 'Cancelling…',
      reason: 'pending',
    };
  }

  if (
    tradingState
      .persistentCancelFrozen
      .has(requestId)
  ) {
    return {
      allowed: false,
      label: 'Check status',
      reason: 'frozen',
    };
  }

  if (
    capabilities
      .cancellation_implemented
      !== true
    || capabilities
      .cancellation_route_available
      !== true
  ) {
    return {
      allowed: false,
      label: 'Unavailable',
      reason: 'capability_unavailable',
    };
  }

  if (
    capabilities.cancel_arm_enabled
    !== true
  ) {
    return {
      allowed: false,
      label: 'Cancel disabled',
      reason: 'cancel_disarmed',
    };
  }

  if (
    !authorizedAccounts.has(accountId)
    || !configuredAccounts.has(accountId)
  ) {
    return {
      allowed: false,
      label: 'Unavailable',
      reason: 'account_unavailable',
    };
  }

  const confirmation = String(
    capabilities
      .cancel_required_confirmation
    || ''
  );

  if (!confirmation) {
    return {
      allowed: false,
      label: 'Unavailable',
      reason: 'confirmation_missing',
    };
  }

  return {
    allowed: true,
    label: 'Cancel',
    reason: 'ready',
    requestId,
    gateOrderId,
    confirmation,
  };
}


async function tradingCancelPersistentOpenOrder(
  requestId,
) {
  const normalizedRequestId = String(
    requestId || ''
  ).trim();

  if (!normalizedRequestId) {
    return;
  }

  /*
   * Resolve the source row from the current,
   * authenticated Open Orders response.
   * Never trust account/pair/Gate ID from DOM data.
   */
  const matches = (
    tradingState.openOrders || []
  ).filter(row => (
    String(
      row?.request?.request_id
      || ''
    ).trim()
    === normalizedRequestId
  ));

  if (matches.length !== 1) {
    showToast(
      'Unable to identify exactly one managed '
      + 'open order for cancellation.',
      true,
    );

    return;
  }

  const row = matches[0];

  const eligibility = (
    tradingPersistentCancelEligibility(
      row
    )
  );

  if (!eligibility.allowed) {
    showToast(
      'This open order is not currently '
      + 'eligible for cancellation.',
      true,
    );

    tradingRenderOpenOrders();

    return;
  }

  const expectedConfirmation = (
    eligibility.confirmation
  );

  const typedConfirmation = window.prompt(
    (
      'Type exactly:\n\n'
      + `${expectedConfirmation}`
      + '\n\n'
      + 'to cancel this live Gate Spot order.'
      + '\n\n'
      + `Gate order: ${eligibility.gateOrderId}`
    ),
    '',
  );

  if (typedConfirmation === null) {
    return;
  }

  if (
    typedConfirmation
    !== expectedConfirmation
  ) {
    showToast(
      'Exact cancellation confirmation '
      + 'text did not match.',
      true,
    );

    return;
  }

  const idFactory = (
    window.tradingLimitCancelRequestId
  );

  if (
    typeof idFactory
    !== 'function'
  ) {
    showToast(
      'Cancellation request identity '
      + 'generator is unavailable.',
      true,
    );

    return;
  }

  const cancelRequestId = String(
    idFactory() || ''
  ).trim();

  if (!cancelRequestId) {
    showToast(
      'Unable to create cancellation '
      + 'request identity.',
      true,
    );

    return;
  }

  /*
   * Stage 3I5: persist cancellation recovery
   * identity before crossing the POST boundary.
   *
   * This helper lives in trading-limit.js and
   * is resolved only when the user clicks.
   */
  const checkpointWriter = (
    window
      .tradingLimitRecoveryCheckpointWrite
  );

  if (
    typeof checkpointWriter
    !== 'function'
  ) {
    showToast(
      'Trading recovery protection is '
      + 'unavailable. No cancellation '
      + 'was sent.',
      true,
    );

    return;
  }

  try {
    checkpointWriter({
      kind: 'cancellation',
      requestId:
        normalizedRequestId,
      cancelRequestId,
      gateOrderId:
        eligibility.gateOrderId,
    });

  } catch (error) {
    showToast(
      (
        error?.message
        || 'Unable to preserve cancellation '
        + 'recovery identity.'
      )
      + ' No cancellation was sent.',
      true,
    );

    return;
  }


  /*
   * Freeze the row before the POST boundary.
   * There is never an automatic POST retry.
   */
  tradingState
    .persistentCancelPending
    .add(normalizedRequestId);

  tradingState
    .persistentCancelFrozen
    .add(normalizedRequestId);

  tradingRenderOpenOrders();

  try {
    const result = await adminApi(
      (
        '/api/trading/limit-orders/requests/'
        + encodeURIComponent(
            normalizedRequestId
          )
        + '/cancel'
      ),
      {
        method: 'POST',
        body: JSON.stringify({
          cancel_request_id:
            cancelRequestId,
          confirmation:
            typedConfirmation,
        }),
      },
    );

    if (
      typeof result?.status !== 'string'
      || typeof result?.definitive
        !== 'boolean'
      || typeof result?.gate_write_performed
        !== 'boolean'
      || typeof result?.write_performed
        !== 'boolean'
      || result.gate_write_performed
        !== result.write_performed
      || String(
        result?.order_request_id
        || ''
      ) !== normalizedRequestId
    ) {
      throw new Error(
        'Safety invariant failed: invalid '
        + 'cancellation response.'
      );
    }

    const cancellation = (
      result?.cancellation || null
    );

    if (
      cancellation
      && String(
        cancellation.order_request_id
        || ''
      ) !== normalizedRequestId
    ) {
      throw new Error(
        'Safety invariant failed: cancellation '
        + 'audit identity mismatch.'
      );
    }

    /*
     * Once this browser session crosses the
     * cancellation POST boundary, keep the source
     * request frozen even after a definitive result.
     *
     * The next read-only Open Orders refresh should
     * remove a successfully cancelled/finished order.
     * If Gate still reports it open, fail closed and
     * show Check status rather than offering another
     * cancellation write.
     */
    const messageFactory = (
      window
        .tradingLimitCancellationMessage
    );

    const message = (
      typeof messageFactory === 'function'
        ? messageFactory(
            result.status,
            result,
          )
        : (
            `Cancellation status: `
            + `${result.status}.`
          )
    );

    showToast(
      message,
      !result.definitive,
    );

    if (result.definitive) {
      const clear = (
        window
          .tradingLimitRecoveryClearKnownDefinitive
      );

      if (
        typeof clear === 'function'
      ) {
        clear({
          kind: 'cancellation',
          requestId:
            normalizedRequestId,
          cancelRequestId,
        });
      }
    }

  } catch (error) {
    /*
     * Browser/network/API uncertainty freezes
     * the source order. Never retry the POST
     * automatically. Backend/open-order refresh
     * determines the durable next state.
     */
    tradingState
      .persistentCancelFrozen
      .add(normalizedRequestId);

    showToast(
      (
        error.message
        || 'Cancellation outcome is uncertain.'
      )
      + ' Do not send another cancellation '
      + 'until status is checked.',
      true,
    );

  } finally {
    tradingState
      .persistentCancelPending
      .delete(normalizedRequestId);

    tradingRenderOpenOrders();

    /*
     * Read-only recovery after the single POST:
     * - Gate Open Orders GET
     * - dashboard Recent Orders GET
     * - market/balance snapshot GET
     */
    await Promise.allSettled([
      tradingRefreshPersistentOrders({
        quiet: true,
      }),
      tradingLoadSnapshot({
        quiet: true,
      }),
    ]);
  }
}


function tradingRenderOpenOrders() {
  const body = $('#tradingOpenOrders');
  const message = $('#tradingOpenOrdersMessage');
  const count = $('#tradingOpenOrdersCount');

  if (
    !body
    || !message
    || !count
  ) {
    return;
  }

  const orders = (
    Array.isArray(
      tradingState.openOrders
    )
      ? tradingState.openOrders
      : []
  );

  count.textContent = (
    tradingState.openOrdersLoaded
      ? String(orders.length)
      : '—'
  );

  if (
    tradingState.loadingOpenOrders
    && !tradingState.openOrdersLoaded
  ) {
    message.textContent = (
      'Loading open orders…'
    );

    message.classList.remove(
      'hidden',
      'error',
    );

  } else if (
    tradingState.openOrdersError
  ) {
    message.textContent = (
      tradingState.openOrdersError
    );

    message.classList.remove(
      'hidden'
    );

    message.classList.add(
      'error'
    );

  } else if (!orders.length) {
    message.textContent = (
      tradingState.openOrdersLoaded
        ? 'No open orders on Gate for this market.'
        : 'Open orders have not been loaded yet.'
    );

    message.classList.remove(
      'hidden',
      'error',
    );

  } else {
    message.textContent = (
      'Live Gate open-order state.'
    );

    message.classList.remove(
      'error'
    );

    message.classList.add(
      'hidden'
    );
  }

  body.innerHTML = orders
    .map(row => {
      const gate = (
        row?.gate_order || {}
      );

      const side = String(
        gate.side || ''
      ).toLowerCase();

      const status = (
        row?.state_conflict
          ? 'State conflict'
          : tradingOrderStatusLabel(
              row?.order_state
                ?.effective_status
              || row?.gate_status
              || gate.status
            )
      );

      const source = (
        row?.identity_conflict
          ? 'Conflict'
          : row?.managed
            ? 'Managed'
            : 'Unmanaged'
      );

      const cancelEligibility = (
        tradingPersistentCancelEligibility(
          row
        )
      );

      const action = (
        cancelEligibility.allowed
          ? `
            <button
              type="button"
              class="trading-orders-cancel-button"
              data-trading-persistent-cancel-request="${escapeHtml(
                cancelEligibility.requestId
              )}"
            >
              Cancel
            </button>
          `
          : `
            <span class="trading-orders-action-note">
              ${escapeHtml(
                cancelEligibility.label
              )}
            </span>
          `
      );

      return `
        <tr>
          <td>
            <span class="trading-orders-side ${escapeHtml(side)}">
              ${escapeHtml(
                side
                  ? side.toUpperCase()
                  : '—'
              )}
            </span>
          </td>

          <td>${escapeHtml(
            tradingFormatPrice(
              gate.price
            )
          )}</td>

          <td>${escapeHtml(
            tradingFormatAmount(
              gate.amount
            )
          )}</td>

          <td>${escapeHtml(
            (
              gate.filled_amount
                === null
              || gate.filled_amount
                === undefined
              || gate.filled_amount
                === ''
            )
              ? '—'
              : tradingFormatAmount(
                  gate.filled_amount
                )
          )}</td>

          <td>
            <span
              class="trading-orders-status ${
                row?.state_conflict
                  || row?.identity_conflict
                    ? 'warning'
                    : ''
              }"
            >
              ${escapeHtml(status)}
            </span>
          </td>

          <td>${escapeHtml(source)}</td>

          <td class="trading-orders-action-cell">
            ${action}
          </td>
        </tr>
      `;
    })
    .join('');
}



function tradingRecentRecoveryEligibility(
  row,
) {
  const factory = (
    window
      .tradingLimitDurableRecoveryEligibility
  );

  if (
    typeof factory !== 'function'
  ) {
    return {
      recoverable: false,
      label: '—',
      reason: 'recovery_unavailable',
    };
  }

  try {
    return factory(
      row
    );

  } catch {
    return {
      recoverable: false,
      label: 'Review',
      reason: 'recovery_error',
    };
  }
}


function tradingRecoverRecentOrder(
  requestId,
) {
  const normalizedRequestId = String(
    requestId || ''
  ).trim();

  if (!normalizedRequestId) {
    return;
  }

  const matches = (
    tradingState.recentOrders || []
  ).filter(
    row => String(
      row?.request?.request_id
      || ''
    ).trim() === normalizedRequestId
  );

  if (matches.length !== 1) {
    showToast(
      'Unable to identify exactly one '
      + 'durable Trading request.',
      true,
    );

    return;
  }

  const recover = (
    window
      .recoverTradingLimitDurableRow
  );

  if (
    typeof recover !== 'function'
  ) {
    showToast(
      'Trading recovery controls '
      + 'are unavailable.',
      true,
    );

    return;
  }

  try {
    const result = recover(
      matches[0]
    );

    showToast(
      (
        'Recovery controls restored for '
        + `request ${result.requestId}.`
      ),
      false,
    );

  } catch (error) {
    showToast(
      (
        error?.message
        || 'Unable to restore Trading recovery.'
      ),
      true,
    );
  }
}


function tradingRenderRecentOrders() {
  const body = $('#tradingRecentOrders');
  const message = $('#tradingRecentOrdersMessage');
  const count = $('#tradingRecentOrdersCount');

  if (
    !body
    || !message
    || !count
  ) {
    return;
  }

  const orders = (
    Array.isArray(
      tradingState.recentOrders
    )
      ? tradingState.recentOrders
      : []
  );

  count.textContent = (
    tradingState.recentOrdersLoaded
      ? String(orders.length)
      : '—'
  );

  if (
    tradingState.loadingRecentOrders
    && !tradingState.recentOrdersLoaded
  ) {
    message.textContent = (
      'Loading recent orders…'
    );

    message.classList.remove(
      'hidden',
      'error',
    );

  } else if (
    tradingState.recentOrdersError
  ) {
    message.textContent = (
      tradingState.recentOrdersError
    );

    message.classList.remove(
      'hidden'
    );

    message.classList.add(
      'error'
    );

  } else if (!orders.length) {
    message.textContent = (
      tradingState.recentOrdersLoaded
        ? 'No dashboard order history for this market.'
        : 'Recent orders have not been loaded yet.'
    );

    message.classList.remove(
      'hidden',
      'error',
    );

  } else {
    message.textContent = (
      'Durable dashboard order history.'
    );

    message.classList.remove(
      'error'
    );

    message.classList.add(
      'hidden'
    );
  }

  body.innerHTML = orders
    .map(row => {
      const request = (
        row?.request || {}
      );

      const cancellation = (
        row?.cancellation || {}
      );

      const gate = (
        row?.gate_snapshot || {}
      );

      const state = (
        row?.order_state || {}
      );

      const side = String(
        request.side
        || gate.side
        || ''
      ).toLowerCase();

      const timestamp = (
        cancellation.completed_at
        || cancellation.updated_at
        || request.completed_at
        || request.updated_at
        || request.created_at
        || gate.update_time_ms
        || gate.update_time
      );

      const status = (
        tradingOrderStatusLabel(
          state.effective_status
          || request.status
        )
      );

      const recovery = (
        tradingRecentRecoveryEligibility(
          row
        )
      );

      const action = (
        recovery.recoverable
          ? `
            <button
              type="button"
              class="trading-orders-recover-button"
              data-trading-recover-request="${escapeHtml(
                recovery.requestId
              )}"
            >
              Recover
            </button>
          `
          : `
            <span class="trading-orders-action-note">
              ${escapeHtml(
                recovery.label || '—'
              )}
            </span>
          `
      );

      return `
        <tr>
          <td>${escapeHtml(
            tradingOrderTime(
              timestamp
            )
          )}</td>

          <td>
            <span class="trading-orders-side ${escapeHtml(side)}">
              ${escapeHtml(
                side
                  ? side.toUpperCase()
                  : '—'
              )}
            </span>
          </td>

          <td>${escapeHtml(
            tradingFormatPrice(
              request.price
              ?? gate.price
            )
          )}</td>

          <td>${escapeHtml(
            tradingFormatAmount(
              request.amount
              ?? gate.amount
            )
          )}</td>

          <td>${escapeHtml(
            (
              gate.filled_amount
                === null
              || gate.filled_amount
                === undefined
              || gate.filled_amount
                === ''
            )
              ? '—'
              : tradingFormatAmount(
                  gate.filled_amount
                )
          )}</td>

          <td>
            <span class="trading-orders-status">
              ${escapeHtml(status)}
            </span>
          </td>

          <td class="trading-orders-gate-id-cell">
            <code
              class="trading-orders-gate-id"
              title="${escapeHtml(
                row?.gate_order_id
                || ''
              )}"
            >${escapeHtml(
              tradingOrderIdLabel(
                row?.gate_order_id
              )
            )}</code>
          </td>

          <td class="trading-orders-action-cell">
            ${action}
          </td>
        </tr>
      `;
    })
    .join('');
}


async function tradingLoadOpenOrders({
  quiet = false,
} = {}) {
  if (
    tradingState.loadingOpenOrders
    || state.activeTab !== 'trading'
    || !state.adminAuthorization
    || !tradingState.accountId
    || !tradingState.pair
  ) {
    return;
  }

  const accountId = (
    tradingState.accountId
  );

  const pair = (
    tradingState.pair
  );

  tradingState.loadingOpenOrders = true;
  tradingState.openOrdersError = '';

  tradingRenderOpenOrders();

  try {
    const result = await adminApi(
      withParams(
        '/api/trading/orders/open',
        {
          account_id: accountId,
          pair,
          limit: 100,
        },
      ),
    );

    if (
      result?.gate_read_performed !== true
      || result?.gate_write_performed !== false
      || result?.write_performed !== false
      || !Array.isArray(result?.orders)
    ) {
      throw new Error(
        'Safety invariant failed: invalid '
        + 'Open Orders response.'
      );
    }

    /*
     * Account/pair may have changed while the
     * authenticated Gate GET was in flight.
     * Never render an old scope into the new one.
     */
    if (
      tradingState.accountId !== accountId
      || tradingState.pair !== pair
    ) {
      return;
    }

    tradingState.openOrders = (
      result.orders
    );

    tradingState.openOrdersLoaded = true;
    tradingState.openOrdersError = '';

  } catch (error) {
    if (
      tradingState.accountId === accountId
      && tradingState.pair === pair
    ) {
      tradingState.openOrdersError = (
        error.message
        || 'Unable to load open orders.'
      );

      if (!quiet) {
        showToast(
          tradingState.openOrdersError,
          true,
        );
      }
    }

  } finally {
    tradingState.loadingOpenOrders = false;

    tradingRenderOpenOrders();
  }
}


async function tradingLoadRecentOrders({
  quiet = false,
} = {}) {
  if (
    tradingState.loadingRecentOrders
    || state.activeTab !== 'trading'
    || !state.adminAuthorization
    || !tradingState.accountId
    || !tradingState.pair
  ) {
    return;
  }

  const accountId = (
    tradingState.accountId
  );

  const pair = (
    tradingState.pair
  );

  tradingState.loadingRecentOrders = true;
  tradingState.recentOrdersError = '';

  tradingRenderRecentOrders();

  try {
    const result = await adminApi(
      withParams(
        '/api/trading/orders/recent',
        {
          account_id: accountId,
          pair,
          limit: 50,
        },
      ),
    );

    if (
      result?.history_source
        !== 'dashboard_audit'
      || result?.gate_read_performed !== false
      || result?.gate_write_performed !== false
      || result?.write_performed !== false
      || !Array.isArray(result?.orders)
    ) {
      throw new Error(
        'Safety invariant failed: invalid '
        + 'Recent Orders response.'
      );
    }

    if (
      tradingState.accountId !== accountId
      || tradingState.pair !== pair
    ) {
      return;
    }

    tradingState.recentOrders = (
      result.orders
    );

    tradingState.recentOrdersLoaded = true;
    tradingState.recentOrdersError = '';

  } catch (error) {
    if (
      tradingState.accountId === accountId
      && tradingState.pair === pair
    ) {
      tradingState.recentOrdersError = (
        error.message
        || 'Unable to load recent orders.'
      );

      if (!quiet) {
        showToast(
          tradingState.recentOrdersError,
          true,
        );
      }
    }

  } finally {
    tradingState.loadingRecentOrders = false;

    tradingRenderRecentOrders();
  }
}


async function tradingRefreshPersistentOrders({
  quiet = false,
} = {}) {
  await Promise.all([
    tradingLoadOpenOrders({
      quiet,
    }),
    tradingLoadRecentOrders({
      quiet,
    }),
  ]);
}


async function tradingLoadCatalog() {
  if (
    tradingState.loadingCatalog
    || !state.adminAuthorization
  ) {
    return;
  }

  tradingState.loadingCatalog = true;

  try {
    const result = await adminApi(
      '/api/trading/catalog'
    );

    tradingState.catalog = result;

    tradingPopulateCatalog();

  } finally {
    tradingState.loadingCatalog = false;
  }
}


async function tradingLoadSnapshot({
  quiet = false,
} = {}) {
  if (
    tradingState.loadingSnapshot
    || state.activeTab !== 'trading'
    || !state.adminAuthorization
    || !tradingState.accountId
    || !tradingState.pair
  ) {
    return;
  }

  tradingState.loadingSnapshot = true;

  try {
    const result = await adminApi(
      withParams(
        '/api/trading/snapshot',
        {
          account_id: (
            tradingState.accountId
          ),
          pair: tradingState.pair,
          depth: 50,
          book_interval: (
            tradingState.bookInterval
          ),
        },
      ),
    );

    tradingState.snapshot = result;

    tradingRenderSnapshot();

    tradingSetError('');

  } catch (error) {
    tradingSetError(
      error.message
      || 'Unable to load Gate market snapshot.'
    );

    if (!quiet) {
      showToast(
        error.message
        || 'Unable to load Gate market snapshot.',
        true,
      );
    }

  } finally {
    tradingState.loadingSnapshot = false;
  }
}


async function tradingLoadCandles({
  quiet = false,
} = {}) {
  if (
    tradingState.loadingCandles
    || state.activeTab !== 'trading'
    || !state.adminAuthorization
    || !tradingState.accountId
    || !tradingState.pair
  ) {
    return;
  }

  tradingState.loadingCandles = true;

  const message = $('#tradingChartMessage');

  try {
    if (message) {
      message.textContent = (
        'Loading Gate candlesticks…'
      );

      message.classList.remove('hidden');
    }

    const result = await adminApi(
      withParams(
        '/api/trading/candles',
        {
          account_id: (
            tradingState.accountId
          ),
          pair: tradingState.pair,
          interval: tradingState.interval,
          limit: 300,
        },
      ),
    );

    tradingRenderCandles(
      result.candles || []
    );

    $('#tradingChartSubtitle').textContent = (
      `${tradingState.pair} · `
      + `${tradingState.interval} candles`
    );

    tradingSetError('');

  } catch (error) {
    if (message) {
      message.textContent = (
        error.message
        || 'Unable to load Gate candlesticks.'
      );

      message.classList.remove('hidden');
    }

    tradingSetError(
      error.message
      || 'Unable to load Gate candlesticks.'
    );

    if (!quiet) {
      showToast(
        error.message
        || 'Unable to load Gate candlesticks.',
        true,
      );
    }

  } finally {
    tradingState.loadingCandles = false;
  }
}


async function tradingRefreshAll({
  quiet = false,
} = {}) {
  const button = $('#refreshTradingMarket');

  tradingSetLoading(
    button,
    true,
    'Refresh',
  );

  try {
    await Promise.all([
      tradingLoadSnapshot({
        quiet,
      }),
      tradingLoadCandles({
        quiet,
      }),
      tradingRefreshPersistentOrders({
        quiet,
      }),
    ]);

  } finally {
    tradingSetLoading(
      button,
      false,
      'Refresh',
    );
  }
}


function tradingStartTimers() {
  if (!tradingState.refreshTimer) {
    tradingState.refreshTimer = setInterval(
      () => {
        if (
          state.activeTab === 'trading'
          && document.visibilityState
            === 'visible'
        ) {
          void tradingLoadSnapshot({
            quiet: true,
          });

          void tradingRefreshPersistentOrders({
            quiet: true,
          });

          if (
            tradingState.marketSideTab
            === 'trades'
          ) {
            void tradingLoadTrades({
              quiet: true,
            });
          }
        }
      },
      3000,
    );
  }

  if (!tradingState.candleTimer) {
    tradingState.candleTimer = setInterval(
      () => {
        if (
          state.activeTab === 'trading'
          && document.visibilityState
            === 'visible'
        ) {
          void tradingLoadCandles({
            quiet: true,
          });
        }
      },
      15000,
    );
  }
}



function tradingApplyRecoveryCheckpointScope() {
  const reader = (
    window
      .tradingLimitRecoveryCheckpointForUser
  );

  if (
    typeof reader !== 'function'
    || !tradingState.catalog
  ) {
    return false;
  }

  const checkpoint = reader();

  if (!checkpoint) {
    return false;
  }

  const accountId = String(
    checkpoint.account_id || ''
  ).trim().toLowerCase();

  const pair = String(
    checkpoint.pair || ''
  ).trim().toUpperCase();

  const accounts = new Set(
    (
      tradingState.catalog.accounts
      || []
    ).map(
      item => String(
        item.id || ''
      ).trim().toLowerCase()
    )
  );

  const pairs = new Set(
    (
      tradingState.catalog.pairs
      || []
    ).map(
      item => String(
        item.id || ''
      ).trim().toUpperCase()
    )
  );

  if (
    !accountId
    || !pair
    || !accounts.has(accountId)
    || !pairs.has(pair)
  ) {
    throw new Error(
      'An unresolved Trading recovery '
      + 'checkpoint references an account '
      + 'or pair that is not currently '
      + 'available to this user.'
    );
  }

  tradingState.accountId = accountId;
  tradingState.pair = pair;

  const accountSelect = $(
    '#tradingAccount'
  );

  const pairInput = $(
    '#tradingPair'
  );

  if (accountSelect) {
    accountSelect.value = accountId;
  }

  if (pairInput) {
    pairInput.value = pair;
  }

  return true;
}


async function tradingRecoverSessionCheckpoint({
  quiet = true,
} = {}) {
  if (
    !state.adminUser
    || !state.adminAuthorization
    || !tradingState.accountId
    || !tradingState.pair
  ) {
    return {
      recovered: false,
      status: 'unavailable',
    };
  }

  const recover = (
    window
      .recoverTradingLimitCheckpoint
  );

  if (
    typeof recover !== 'function'
  ) {
    return {
      recovered: false,
      status: 'unavailable',
    };
  }

  return recover({
    quiet,
  });
}


async function activateTradingTab() {
  if (
    !state.adminUser
    || !state.adminAuthorization
  ) {
    return;
  }

  tradingSetError('');

  try {
    if (!tradingState.catalog) {
      await tradingLoadCatalog();
    } else {
      tradingPopulateCatalog();
    }

    /*
     * A session checkpoint from a previous
     * interrupted browser connection takes
     * precedence over the normal default scope,
     * provided that scope remains authorized.
     */
    tradingApplyRecoveryCheckpointScope();

    if (
      !tradingState.accountId
      || !tradingState.pair
    ) {
      tradingSetError(
        'No explicitly assigned Gate trading account '
        + 'or tradable spot pair is available.'
      );

      return;
    }

    tradingEnsureChart();

    await tradingRefreshAll({
      quiet: true,
    });

    /*
     * One exact request GET may run here when
     * a matching session checkpoint exists.
     * No reconciliation POST is automatic.
     */
    await tradingRecoverSessionCheckpoint({
      quiet: true,
    });

    tradingStartTimers();

  } catch (error) {
    tradingSetError(
      error.message
      || 'Unable to initialize Trading.'
    );

    showToast(
      error.message
      || 'Unable to initialize Trading.',
      true,
    );
  }
}


function resetTradingTab() {
  tradingState.catalog = null;
  tradingState.accountId = '';
  tradingState.pair = '';
  tradingState.snapshot = null;

  tradingResetPersistentOrders();

  tradingSetError('');

  if (tradingState.series) {
    tradingState.series.setData([]);
  }

  if (tradingState.volumeSeries) {
    tradingState.volumeSeries.setData([]);
  }

  const volumeValue = $(
    '#tradingVolumeValue'
  );

  if (volumeValue) {
    volumeValue.textContent = '—';
  }

  $('#tradingAccount').innerHTML = '';
  $('#tradingPair').value = '';
  $('#tradingPairOptions').innerHTML = '';
}


function bindTradingEvents() {
  $('#tradingRecentOrders')?.addEventListener(
    'click',
    event => {
      const button = (
        event.target instanceof Element
          ? event.target.closest(
              '[data-trading-recover-request]'
            )
          : null
      );

      if (!button) {
        return;
      }

      const requestId = String(
        button.dataset
          .tradingRecoverRequest
        || ''
      ).trim();

      if (!requestId) {
        return;
      }

      tradingRecoverRecentOrder(
        requestId
      );
    },
  );

  $('#tradingOpenOrders')?.addEventListener(
    'click',
    event => {
      const button = (
        event.target instanceof Element
          ? event.target.closest(
              '[data-trading-persistent-cancel-request]'
            )
          : null
      );

      if (!button) {
        return;
      }

      const requestId = String(
        button.dataset
          .tradingPersistentCancelRequest
        || ''
      ).trim();

      if (!requestId) {
        return;
      }

      void tradingCancelPersistentOpenOrder(
        requestId
      );
    },
  );

  $('#tradingAccount')?.addEventListener(
    'change',
    event => {
      const accountId = String(
        event.target.value || ''
      ).trim().toLowerCase();

      if (
        !tradingAuthorizedAccountIds()
          .has(accountId)
      ) {
        return;
      }

      tradingState.accountId = accountId;

      tradingResetPersistentOrders();

      void tradingLoadSnapshot();

      void tradingRefreshPersistentOrders();

      void tradingRecoverSessionCheckpoint({
        quiet: true,
      });
    },
  );

  const pairInput = $('#tradingPair');

  const applyPair = () => {
    try {
      tradingValidatePair();

      tradingState.bookInterval = '0';
      tradingPopulateBookIntervals();

      tradingResetPersistentOrders();

      void tradingRefreshAll();

      void tradingRecoverSessionCheckpoint({
        quiet: true,
      });

      if (
        tradingState.marketSideTab === 'trades'
      ) {
        void tradingLoadTrades();
      }

    } catch (error) {
      tradingSetError(
        error.message
      );
    }
  };

  pairInput?.addEventListener(
    'change',
    applyPair,
  );

  pairInput?.addEventListener(
    'keydown',
    event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        applyPair();
      }
    },
  );

  $('#tradingIntervals')?.addEventListener(
    'click',
    event => {
      const button = (
        event.target instanceof Element
          ? event.target.closest(
              '[data-trading-interval]'
            )
          : null
      );

      if (!button) return;

      tradingState.interval = (
        button.dataset.tradingInterval
        || '5m'
      );

      tradingRenderIntervalButtons();

      void tradingLoadCandles();
    },
  );

  $('#tradingBookInterval')?.addEventListener(
    'change',
    event => {
      tradingState.bookInterval = String(
        event.target.value || '0'
      );

      void tradingLoadSnapshot();
    },
  );

  $('.trading-book-tabs')?.addEventListener(
    'click',
    event => {
      const button = (
        event.target instanceof Element
          ? event.target.closest(
              '[data-trading-market-tab]'
            )
          : null
      );

      if (!button) return;

      tradingState.marketSideTab = (
        button.dataset.tradingMarketTab
        || 'book'
      );

      tradingRenderMarketSideTabs();

      if (
        tradingState.marketSideTab
        === 'trades'
      ) {
        void tradingLoadTrades();
      }
    },
  );

  $('#refreshTradingMarket')?.addEventListener(
    'click',
    () => {
      void tradingRefreshAll();
    },
  );

  $('#accountSelector')?.addEventListener(
    'change',
    () => {
      if (
        state.activeTab !== 'trading'
        || !tradingState.catalog
      ) {
        return;
      }

      const ids = (
        tradingAuthorizedAccountIds()
      );

      if (
        state.selectedAccount
        && ids.has(state.selectedAccount)
      ) {
        tradingState.accountId = (
          state.selectedAccount
        );

        $('#tradingAccount').value = (
          state.selectedAccount
        );

        tradingResetPersistentOrders();

        void tradingLoadSnapshot();

        void tradingRefreshPersistentOrders();

        void tradingRecoverSessionCheckpoint({
          quiet: true,
        });
      }
    },
  );
}


window.activateTradingTab = activateTradingTab;
window.resetTradingTab = resetTradingTab;


if (document.readyState === 'loading') {
  document.addEventListener(
    'DOMContentLoaded',
    () => {
      bindTradingEvents();

      if (state.activeTab === 'trading') {
        void activateTradingTab();
      }
    },
    {
      once: true,
    },
  );

} else {
  bindTradingEvents();

  if (state.activeTab === 'trading') {
    void activateTradingTab();
  }
}
