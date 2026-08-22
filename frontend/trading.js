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
  persistentAmendPending: new Set(),
  persistentAmendFrozen: new Set(),
  persistentAmendReconcilePending: new Set(),
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



function tradingOrderAmendmentReadModel(
  row,
) {
  if (!row?.managed) {
    return {
      label: '—',
      warning: false,
      title: (
        'Unmanaged Gate order. '
        + 'No dashboard amendment audit.'
      ),
    };
  }

  const history = (
    Array.isArray(
      row?.amendments
    )
      ? row.amendments
      : []
  );

  const active = (
    row?.active_amendment || null
  );

  const latest = (
    row?.latest_amendment
    || history[0]
    || null
  );

  const amendment = (
    active || latest
  );

  if (amendment) {
    const status = String(
      amendment.status || ''
    ).trim().toLowerCase();

    const count = Number(
      row?.amendment_count
      ?? history.length
    );

    const activeStatus = Boolean(
      active
    );

    let label;

    if (status === 'confirmed_amended') {
      label = 'Amended';

    } else if (status === 'amended') {
      label = 'Amended';

    } else if (
      status === 'confirmed_not_applied'
    ) {
      label = 'Not applied';

    } else if (status === 'uncertain') {
      label = 'Amend uncertain';

    } else if (status === 'attention') {
      label = 'Amend attention';

    } else if (status === 'amending') {
      label = 'Amending';

    } else if (status === 'reserved') {
      label = 'Amend reserved';

    } else {
      label = (
        tradingOrderStatusLabel(
          status || 'unknown'
        )
      );
    }

    if (count > 1) {
      label += ` · ${count}`;
    }

    const currentPrice = String(
      amendment.current_price || ''
    ).trim();

    const requestedPrice = String(
      amendment.requested_price || ''
    ).trim();

    const priceSummary = (
      currentPrice
      && requestedPrice
        ? (
            `${currentPrice} → `
            + requestedPrice
          )
        : ''
    );

    const requestId = String(
      amendment.amend_request_id || ''
    ).trim();

    return {
      label,
      warning: (
        activeStatus
        || [
          'uncertain',
          'attention',
          'amending',
          'reserved',
        ].includes(status)
      ),
      title: [
        (
          activeStatus
            ? 'Unresolved amendment'
            : 'Latest amendment'
        ),
        priceSummary,
        requestId
          ? `ID ${requestId}`
          : '',
        count > 0
          ? (
              `${count} amendment`
              + (
                count === 1
                  ? ''
                  : 's'
              )
              + ' recorded'
            )
          : '',
      ].filter(Boolean).join(' · '),
    };
  }

  const capabilities = (
    tradingState
      .limitOrderExecutionCapabilities
  );

  if (!capabilities) {
    return {
      label: 'Checking…',
      warning: false,
      title: (
        'Waiting for backend amendment '
        + 'capabilities.'
      ),
    };
  }

  if (
    capabilities
      .amendment_implemented !== true
    || capabilities
      .amendment_route_available !== true
  ) {
    return {
      label: 'Unavailable',
      warning: true,
      title: (
        'Guarded amendment backend '
        + 'is unavailable.'
      ),
    };
  }

  if (
    capabilities
      .amend_arm_enabled !== true
  ) {
    return {
      label: 'Amend disabled',
      warning: false,
      title: (
        'Price amendment is implemented '
        + 'but currently disarmed.'
      ),
    };
  }

  return {
    label: 'No history',
    warning: false,
    title: (
      'No amendment has been recorded '
      + 'for this managed order.'
    ),
  };
}


function tradingAmendReconcileKey(
  requestId,
  amendRequestId,
) {
  return (
    String(
      requestId || ''
    ).trim()
    + '::'
    + String(
      amendRequestId || ''
    ).trim()
  );
}


function tradingPersistentAmendReconcileEligibility(
  row,
) {
  const request = (
    row?.request || {}
  );

  const amendment = (
    row?.active_amendment || null
  );

  const capabilities = (
    tradingState
      .limitOrderExecutionCapabilities
    || {}
  );

  const requestId = String(
    request.request_id || ''
  ).trim();

  const amendRequestId = String(
    amendment?.amend_request_id || ''
  ).trim();

  const amendmentOrderRequestId = String(
    amendment?.order_request_id || ''
  ).trim();

  const gateOrderId = String(
    row?.gate_order_id
    || row?.gate_order?.id
    || row?.gate_snapshot?.id
    || ''
  ).trim();

  const sourceGateOrderId = String(
    request.gate_order_id || ''
  ).trim();

  const amendmentGateOrderId = String(
    amendment?.gate_order_id || ''
  ).trim();

  const accountId = String(
    request.account_id || ''
  ).trim().toLowerCase();

  const pair = String(
    request.pair || ''
  ).trim().toUpperCase();

  const status = String(
    amendment?.status || ''
  ).trim().toLowerCase();

  const requestedPrice = String(
    amendment?.requested_price || ''
  ).trim();

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
      reconcilable: false,
      label: '—',
      reason: 'unmanaged',
    };
  }

  if (
    row?.identity_conflict
    || row?.state_conflict
  ) {
    return {
      reconcilable: false,
      label: 'Review',
      reason: 'conflict',
    };
  }

  /*
   * Only the durable ACTIVE amendment may be
   * manually reconciled. Completed historical
   * amendments need no recovery operation.
   */
  if (!amendment) {
    return {
      reconcilable: false,
      label: '—',
      reason: 'no_active_amendment',
    };
  }

  if (
    ![
      'amending',
      'uncertain',
      'attention',
    ].includes(
      status
    )
  ) {
    return {
      reconcilable: false,
      label: '—',
      reason: 'status_not_reconcilable',
    };
  }

  if (
    amendment.write_performed !== true
    || String(
      amendment.completed_at || ''
    ).trim()
  ) {
    return {
      reconcilable: false,
      label: '—',
      reason: 'audit_not_reconcilable',
    };
  }

  if (
    !requestId
    || !amendRequestId
    || amendmentOrderRequestId
      !== requestId
    || !gateOrderId
    || !/^[0-9]+$/.test(
      gateOrderId
    )
  ) {
    return {
      reconcilable: false,
      label: 'Review',
      reason: 'identity_missing',
    };
  }

  /*
   * Source audit, amendment audit and current
   * row must all identify the same Gate order.
   */
  if (
    !sourceGateOrderId
    || sourceGateOrderId !== gateOrderId
    || !amendmentGateOrderId
    || amendmentGateOrderId !== gateOrderId
  ) {
    return {
      reconcilable: false,
      label: 'Review',
      reason: 'gate_id_mismatch',
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
      reconcilable: false,
      label: 'Review',
      reason: 'scope_mismatch',
    };
  }

  if (
    capabilities
      .amend_reconciliation_implemented
      !== true
    || capabilities
      .amend_reconciliation_route_available
      !== true
    || capabilities
      .amend_reconciliation_gate_get_only
      !== true
  ) {
    return {
      reconcilable: false,
      label: 'Check unavailable',
      reason: 'capability_unavailable',
    };
  }

  if (
    !authorizedAccounts.has(accountId)
    || !configuredAccounts.has(accountId)
  ) {
    return {
      reconcilable: false,
      label: 'Check unavailable',
      reason: 'account_unavailable',
    };
  }

  const pendingKey = (
    tradingAmendReconcileKey(
      requestId,
      amendRequestId,
    )
  );

  if (
    tradingState
      .persistentAmendReconcilePending
      .has(pendingKey)
  ) {
    return {
      reconcilable: false,
      label: 'Checking amendment…',
      reason: 'pending',
    };
  }

  /*
   * Deliberately NO amend_arm_enabled check.
   *
   * Manual reconciliation must remain available
   * while new amendment writes are disarmed.
   */
  return {
    reconcilable: true,
    label: 'Check amendment',
    reason: 'ready',
    requestId,
    amendRequestId,
    gateOrderId,
    requestedPrice,
    accountId,
    pair,
    status,
    pendingKey,
  };
}


async function tradingReconcilePersistentAmendment(
  requestId,
  amendRequestId,
) {
  const normalizedRequestId = String(
    requestId || ''
  ).trim();

  const normalizedAmendRequestId = String(
    amendRequestId || ''
  ).trim();

  if (
    !normalizedRequestId
    || !normalizedAmendRequestId
  ) {
    return;
  }

  /*
   * Re-resolve from authenticated Open/Recent
   * data. The DOM contributes only lookup keys.
   */
  const candidates = [
    ...(
      tradingState.openOrders || []
    ),
    ...(
      tradingState.recentOrders || []
    ),
  ].filter(
    row => (
      String(
        row?.request?.request_id || ''
      ).trim()
        === normalizedRequestId
      && String(
        row?.active_amendment
          ?.amend_request_id
        || ''
      ).trim()
        === normalizedAmendRequestId
    )
  );

  if (!candidates.length) {
    showToast(
      'Unable to identify the unresolved '
      + 'amendment for manual checking.',
      true,
    );

    tradingRenderPersistentOrders();

    return;
  }

  const eligible = candidates
    .map(
      row => (
        tradingPersistentAmendReconcileEligibility(
          row
        )
      )
    )
    .filter(
      item => (
        item.reconcilable
        && item.requestId
          === normalizedRequestId
        && item.amendRequestId
          === normalizedAmendRequestId
      )
    );

  /*
   * Every authenticated copy of this exact
   * amendment must independently pass all
   * reconciliation identity/scope checks.
   *
   * Never ignore a conflicting Open/Recent
   * duplicate merely because another copy is
   * eligible.
   */
  if (
    eligible.length
    !== candidates.length
  ) {
    showToast(
      'Amendment reconciliation candidate '
      + 'conflict detected. Refresh order '
      + 'state before trying again.',
      true,
    );

    tradingRenderPersistentOrders();

    return;
  }

  /*
   * Open and Recent may theoretically both
   * contain the same source request. Multiple
   * copies are acceptable only when every
   * durable identity agrees exactly.
   */
  const identities = new Set(
    eligible.map(
      item => JSON.stringify({
        requestId:
          item.requestId,
        amendRequestId:
          item.amendRequestId,
        gateOrderId:
          item.gateOrderId,
        requestedPrice:
          item.requestedPrice,
        accountId:
          item.accountId,
        pair:
          item.pair,
      })
    )
  );

  if (identities.size !== 1) {
    showToast(
      'Amendment reconciliation identity '
      + 'conflict detected.',
      true,
    );

    return;
  }

  const eligibility = eligible[0];

  const decimalIdentity = (
    window
      .tradingLimitRecoveryDecimalIdentity
  );

  if (
    typeof decimalIdentity !== 'function'
  ) {
    showToast(
      'Amendment reconciliation price '
      + 'identity helper is unavailable.',
      true,
    );

    return;
  }

  const expectedRequestedPrice = String(
    decimalIdentity(
      eligibility.requestedPrice
    ) || ''
  ).trim();

  if (!expectedRequestedPrice) {
    showToast(
      'Amendment reconciliation requested '
      + 'price identity is invalid.',
      true,
    );

    return;
  }

  const pendingKey = (
    eligibility.pendingKey
  );

  tradingState
    .persistentAmendReconcilePending
    .add(pendingKey);

  tradingRenderPersistentOrders();

  try {
    /*
     * This dashboard POST asks the backend to
     * perform the existing MANUAL reconciliation.
     *
     * Backend contract:
     * - Gate GET may occur
     * - Gate PATCH cannot occur
     * - no new amendment is created
     */
    const result = await adminApi(
      (
        '/api/trading/limit-orders/requests/'
        + encodeURIComponent(
            normalizedRequestId
          )
        + '/amendments/'
        + encodeURIComponent(
            normalizedAmendRequestId
          )
        + '/reconcile'
      ),
      {
        method: 'POST',
      },
    );

    const reconciliation = (
      result?.reconciliation
    );

    if (
      result?.gate_read_performed
        !== true
      || result?.gate_write_performed
        !== false
      || result?.write_performed
        !== false
      || !reconciliation
      || typeof reconciliation
        !== 'object'
      || Array.isArray(
        reconciliation
      )
      || typeof reconciliation.status
        !== 'string'
      || typeof reconciliation.definitive
        !== 'boolean'
      || reconciliation
        .gate_read_performed
        !== true
      || reconciliation
        .gate_write_performed
        !== false
      || reconciliation
        .write_performed
        !== false
      || reconciliation
        .manual_reconciliation
        !== true
      || reconciliation
        .historical_amend_write_performed
        !== true
      || String(
        reconciliation.order_request_id
        || ''
      ) !== normalizedRequestId
      || String(
        reconciliation.amend_request_id
        || ''
      ) !== normalizedAmendRequestId
    ) {
      throw new Error(
        'Safety invariant failed: invalid '
        + 'manual amendment reconciliation '
        + 'response.'
      );
    }

    const amendment = (
      reconciliation.amendment || null
    );

    if (amendment) {
      const durableRequestedPrice = String(
        decimalIdentity(
          amendment.requested_price
        ) || ''
      ).trim();

      if (
        String(
          amendment.order_request_id
          || ''
        ) !== normalizedRequestId
        || String(
          amendment.amend_request_id
          || ''
        ) !== normalizedAmendRequestId
        || String(
          amendment.gate_order_id
          || ''
        ) !== eligibility.gateOrderId
        || !durableRequestedPrice
        || durableRequestedPrice
          !== expectedRequestedPrice
      ) {
        throw new Error(
          'Safety invariant failed: reconciled '
          + 'amendment audit identity mismatch.'
        );
      }
    }

    showToast(
      (
        'Amendment check: '
        + tradingPersistentAmendMessage(
            reconciliation.status,
            reconciliation,
          )
      ),
      !reconciliation.definitive,
    );

  } catch (error) {
    /*
     * Safe to retry manually:
     * this route cannot PATCH Gate.
     *
     * Do NOT create a durable write checkpoint
     * and do NOT freeze future recovery checks.
     */
    showToast(
      (
        error?.message
        || (
          'Unable to check the amendment '
          + 'status.'
        )
      )
      + ' This check cannot write Gate; '
      + 'you may retry it manually.',
      true,
    );

  } finally {
    tradingState
      .persistentAmendReconcilePending
      .delete(pendingKey);

    /*
     * Refresh durable audit/order state.
     */
    await Promise.allSettled([
      tradingRefreshPersistentOrders({
        quiet: true,
      }),
      tradingLoadSnapshot({
        quiet: true,
      }),
    ]);

    /*
     * If this browser holds the matching B0
     * amendment checkpoint, the normal GET-only
     * checkpoint recovery can now observe the
     * reconciled durable state and clear it when
     * definitive.
     */
    await Promise.allSettled([
      tradingRecoverSessionCheckpoint({
        quiet: true,
      }),
    ]);

    tradingRenderPersistentOrders();
  }
}


function tradingPersistentAmendEligibility(
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

  const sourceStatus = String(
    request.status || ''
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

  /*
   * Backend amendment policy is intentionally
   * stricter than "cancellation in progress":
   * any cancellation audit blocks amendment.
   */
  if (row?.cancellation) {
    return {
      allowed: false,
      label: 'Cancellation recorded',
      reason: 'existing_cancellation',
    };
  }

  if (row?.active_amendment) {
    const status = String(
      row.active_amendment.status || ''
    ).trim();

    return {
      allowed: false,
      label: (
        status
          ? tradingOrderStatusLabel(
              status
            )
          : 'Amend unresolved'
      ),
      reason: 'active_amendment',
    };
  }

  if (
    !requestId
    || !gateOrderId
    || !/^[0-9]+$/.test(
      gateOrderId
    )
  ) {
    return {
      allowed: false,
      label: 'Unavailable',
      reason: 'identity_missing',
    };
  }

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
    ].includes(
      finishAs
    )
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
    ).trim().toLowerCase()
      !== 'limit'
    || ![
      'submitted',
      'confirmed_open',
    ].includes(
      sourceStatus
    )
  ) {
    return {
      allowed: false,
      label: 'Unavailable',
      reason: 'audit_not_amendable',
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
    || tradingState
      .persistentCancelFrozen
      .has(requestId)
  ) {
    return {
      allowed: false,
      label: 'Cancellation active',
      reason: 'cancel_active',
    };
  }

  if (
    tradingState
      .persistentAmendPending
      .has(requestId)
  ) {
    return {
      allowed: false,
      label: 'Amending…',
      reason: 'pending',
    };
  }

  if (
    tradingState
      .persistentAmendFrozen
      .has(requestId)
  ) {
    return {
      allowed: false,
      label: 'Check amend',
      reason: 'frozen',
    };
  }

  /*
   * Synthetic or checkpoint-based recovery from
   * any Trading write blocks a new amendment.
   */
  const unresolvedAttempt = [
    tradingState
      .limitOrderExecutionAttempt,
    tradingState
      .limitOrderCancellationAttempt,
    tradingState
      .limitOrderAmendmentAttempt,
  ].some(
    attempt => (
      attempt
      && attempt.definitive !== true
    )
  );

  if (unresolvedAttempt) {
    return {
      allowed: false,
      label: 'Recovery required',
      reason: 'recovery_required',
    };
  }

  const checkpointReader = (
    window
      .tradingLimitRecoveryCheckpointForUser
  );

  if (
    typeof checkpointReader
    !== 'function'
  ) {
    return {
      allowed: false,
      label: 'Unavailable',
      reason: 'recovery_unavailable',
    };
  }

  try {
    if (checkpointReader()) {
      return {
        allowed: false,
        label: 'Recovery required',
        reason: 'checkpoint_present',
      };
    }

  } catch {
    return {
      allowed: false,
      label: 'Review',
      reason: 'checkpoint_error',
    };
  }

  if (
    capabilities
      .amendment_implemented
      !== true
    || capabilities
      .amendment_route_available
      !== true
  ) {
    return {
      allowed: false,
      label: 'Unavailable',
      reason: 'capability_unavailable',
    };
  }

  /*
   * This is the primary browser arm gate.
   * With the current .env=false there must be
   * no actionable Amend button.
   */
  if (
    capabilities
      .amend_arm_enabled
      !== true
  ) {
    return {
      allowed: false,
      label: 'Amend disabled',
      reason: 'amend_disarmed',
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
      .amend_required_confirmation
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
    label: 'Amend price',
    reason: 'ready',
    requestId,
    gateOrderId,
    confirmation,
    currentPrice: String(
      gate.price || ''
    ).trim(),
  };
}


function tradingPersistentAmendMessage(
  status,
  result = {},
) {
  const normalized = String(
    status || ''
  ).trim().toLowerCase();

  if (
    normalized === 'amended'
    || normalized === 'confirmed_amended'
  ) {
    return (
      'Gate confirmed the requested '
      + 'price amendment.'
    );
  }

  if (
    normalized === 'confirmed_not_applied'
  ) {
    return (
      'Gate confirmed that the requested '
      + 'price was not applied.'
    );
  }

  if (
    normalized === 'already_at_requested_price'
  ) {
    return (
      'The Gate order is already at the '
      + 'requested price.'
    );
  }

  if (
    normalized === 'uncertain'
    || normalized === 'attention'
    || normalized === 'amending'
  ) {
    return (
      'The amendment outcome is not definitive. '
      + 'Do not send another Trading write '
      + 'until its status is resolved.'
    );
  }

  if (
    normalized === 'rejected'
    || normalized === 'local_rejected'
    || normalized === 'precheck_error'
    || normalized === 'aborted'
  ) {
    return (
      String(
        result?.error
        || result?.message
        || ''
      ).trim()
      || (
        'The amendment was not accepted.'
      )
    );
  }

  return (
    `Amendment status: ${normalized || 'unknown'}.`
  );
}


async function tradingAmendPersistentOpenOrder(
  requestId,
) {
  const normalizedRequestId = String(
    requestId || ''
  ).trim();

  if (!normalizedRequestId) {
    return;
  }

  /*
   * Resolve identity again from the current
   * authenticated Open Orders response.
   * DOM attributes contain only the source
   * request ID and are never trusted for Gate
   * identity, market or account scope.
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
      + 'open order for amendment.',
      true,
    );

    return;
  }

  const row = matches[0];

  const eligibility = (
    tradingPersistentAmendEligibility(
      row
    )
  );

  if (!eligibility.allowed) {
    showToast(
      'This open order is not currently '
      + 'eligible for price amendment.',
      true,
    );

    tradingRenderOpenOrders();

    return;
  }

  const decimalIdentity = (
    window
      .tradingLimitRecoveryDecimalIdentity
  );

  if (
    typeof decimalIdentity
    !== 'function'
  ) {
    showToast(
      'Amendment price validation is '
      + 'unavailable. No amendment was sent.',
      true,
    );

    return;
  }

  const typedPrice = window.prompt(
    (
      'Enter the new price for this live '
      + 'Gate Spot limit order.'
      + '\n\n'
      + `Gate order: ${eligibility.gateOrderId}`
      + '\n'
      + `Current price: ${
          eligibility.currentPrice || '—'
        }`
    ),
    eligibility.currentPrice || '',
  );

  if (typedPrice === null) {
    return;
  }

  const requestedPrice = String(
    decimalIdentity(
      typedPrice
    ) || ''
  ).trim();

  if (!requestedPrice) {
    showToast(
      'Requested amendment price must be '
      + 'a positive decimal.',
      true,
    );

    return;
  }

  const currentPrice = String(
    decimalIdentity(
      eligibility.currentPrice
    ) || ''
  ).trim();

  if (
    currentPrice
    && requestedPrice === currentPrice
  ) {
    showToast(
      'The requested price is already the '
      + 'current Gate order price.',
      true,
    );

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
      + 'to amend this LIVE Gate Spot order.'
      + '\n\n'
      + `Gate order: ${eligibility.gateOrderId}`
      + '\n'
      + `New price: ${requestedPrice}`
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
      'Exact amendment confirmation '
      + 'text did not match.',
      true,
    );

    return;
  }

  const idFactory = (
    window
      .tradingLimitAmendRequestId
  );

  if (
    typeof idFactory
    !== 'function'
  ) {
    showToast(
      'Amendment request identity '
      + 'generator is unavailable.',
      true,
    );

    return;
  }

  const amendRequestId = String(
    idFactory() || ''
  ).trim();

  if (!amendRequestId) {
    showToast(
      'Unable to create amendment '
      + 'request identity.',
      true,
    );

    return;
  }

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
      + 'unavailable. No amendment was sent.',
      true,
    );

    return;
  }

  /*
   * CRITICAL:
   * Persist the full amendment recovery identity
   * before crossing the browser POST boundary.
   */
  try {
    checkpointWriter({
      kind: 'amendment',
      requestId:
        normalizedRequestId,
      amendRequestId,
      gateOrderId:
        eligibility.gateOrderId,
      requestedPrice,
    });

  } catch (error) {
    showToast(
      (
        error?.message
        || (
          'Unable to preserve amendment '
          + 'recovery identity.'
        )
      )
      + ' No amendment was sent.',
      true,
    );

    return;
  }

  /*
   * Freeze before POST. There is exactly one
   * browser amendment POST attempt and never
   * an automatic retry.
   */
  tradingState
    .persistentAmendPending
    .add(normalizedRequestId);

  tradingState
    .persistentAmendFrozen
    .add(normalizedRequestId);

  tradingRenderOpenOrders();

  let definitiveOutcome = false;
  let checkpointCleared = false;

  try {
    const result = await adminApi(
      (
        '/api/trading/limit-orders/requests/'
        + encodeURIComponent(
            normalizedRequestId
          )
        + '/amend'
      ),
      {
        method: 'POST',
        body: JSON.stringify({
          amend_request_id:
            amendRequestId,
          requested_price:
            requestedPrice,
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
      || typeof result?.manual_review_required
        !== 'boolean'
      || String(
        result?.order_request_id
        || ''
      ) !== normalizedRequestId
      || String(
        result?.amend_request_id
        || ''
      ) !== amendRequestId
    ) {
      throw new Error(
        'Safety invariant failed: invalid '
        + 'amendment response.'
      );
    }

    const amendment = (
      result?.amendment || null
    );

    if (amendment) {
      const durableRequestedPrice = String(
        decimalIdentity(
          amendment.requested_price
        ) || ''
      ).trim();

      if (
        String(
          amendment.order_request_id
          || ''
        ) !== normalizedRequestId
        || String(
          amendment.amend_request_id
          || ''
        ) !== amendRequestId
        || String(
          amendment.gate_order_id
          || ''
        ) !== eligibility.gateOrderId
        || !durableRequestedPrice
        || durableRequestedPrice
          !== requestedPrice
      ) {
        throw new Error(
          'Safety invariant failed: amendment '
          + 'audit identity mismatch.'
        );
      }
    }

    tradingState
      .limitOrderAmendmentAttempt = {
        amendRequestId,
        orderRequestId:
          normalizedRequestId,
        gateOrderId:
          eligibility.gateOrderId,
        requestedPrice,
        status:
          result.status,
        definitive:
          result.definitive,
        gateWritePerformed:
          result.gate_write_performed,
        amendment,
        result,
        message: (
          tradingPersistentAmendMessage(
            result.status,
            result,
          )
        ),
        recovered: false,
      };

    definitiveOutcome = (
      result.definitive === true
    );

    showToast(
      tradingPersistentAmendMessage(
        result.status,
        result,
      ),
      (
        !result.definitive
        || result.manual_review_required
      ),
    );

    if (result.definitive) {
      const clear = (
        window
          .tradingLimitRecoveryClearKnownDefinitive
      );

      if (
        typeof clear !== 'function'
      ) {
        throw new Error(
          'Trading recovery checkpoint clearer '
          + 'is unavailable after a definitive '
          + 'amendment.'
        );
      }

      const clearResult = clear({
        kind: 'amendment',
        requestId:
          normalizedRequestId,
        amendRequestId,
      });

      checkpointCleared = (
        clearResult?.cleared === true
      );

      if (!checkpointCleared) {
        showToast(
          'The amendment outcome is definitive, '
          + 'but its browser recovery checkpoint '
          + 'could not be cleared. New Trading '
          + 'writes remain blocked.',
          true,
        );
      }
    }

  } catch (error) {
    const detail = (
      error?.payload?.detail
    );

    const errorStatus = Number(
      error?.status || 0
    );

    const detailStatus = Number(
      detail?.status_code || 0
    );

    const structuredNoWriteDenial = Boolean(
      detail
      && typeof detail === 'object'
      && !Array.isArray(detail)
      && errorStatus > 0
      && detailStatus === errorStatus
      && String(
        detail.code || ''
      ).trim()
      && String(
        detail.message || ''
      ).trim()
      && detail.gate_write_performed
        === false
      && detail.write_performed
        === false
    );

    if (structuredNoWriteDenial) {
      /*
       * A complete backend denial response proves
       * that Gate's amendment write boundary was
       * not crossed. This is definitive and the
       * pre-POST browser checkpoint may be cleared.
       */
      const status = String(
        detail.code
        || 'local_rejected'
      ).trim().toLowerCase();

      tradingState
        .limitOrderAmendmentAttempt = {
          amendRequestId,
          orderRequestId:
            normalizedRequestId,
          gateOrderId:
            eligibility.gateOrderId,
          requestedPrice,
          status,
          definitive: true,
          gateWritePerformed: false,
          amendment: null,
          result: detail,
          message: (
            String(
              detail.message || ''
            ).trim()
            || (
              'The amendment was rejected '
              + 'before any Gate write.'
            )
          ),
          recovered: false,
        };

      definitiveOutcome = true;

      const clear = (
        window
          .tradingLimitRecoveryClearKnownDefinitive
      );

      if (
        typeof clear === 'function'
      ) {
        const clearResult = clear({
          kind: 'amendment',
          requestId:
            normalizedRequestId,
          amendRequestId,
        });

        checkpointCleared = (
          clearResult?.cleared === true
        );
      }

      showToast(
        String(
          detail.message || ''
        ).trim()
        || (
          'The amendment was rejected before '
          + 'any Gate write.'
        ),
        true,
      );

    } else {
      /*
       * Browser/network/invalid-response ambiguity
       * after POST must remain frozen. Never retry
       * automatically.
       */
      tradingState
        .limitOrderAmendmentAttempt = {
          amendRequestId,
          orderRequestId:
            normalizedRequestId,
          gateOrderId:
            eligibility.gateOrderId,
          requestedPrice,
          status: 'client_uncertain',
          definitive: false,
          gateWritePerformed: null,
          amendment: null,
          result: null,
          message: (
            error?.message
            || (
              'Amendment outcome is uncertain.'
            )
          ),
          recovered: false,
        };

      showToast(
        (
          error?.message
          || 'Amendment outcome is uncertain.'
        )
        + ' Do not send another Trading write '
        + 'until status is checked.',
        true,
      );
    }

  } finally {
    tradingState
      .persistentAmendPending
      .delete(normalizedRequestId);

    /*
     * A definitive response is allowed to release
     * the session freeze only after the matching
     * recovery checkpoint was successfully cleared.
     */
    if (
      definitiveOutcome
      && checkpointCleared
    ) {
      tradingState
        .persistentAmendFrozen
        .delete(normalizedRequestId);
    }

    tradingRenderOpenOrders();

    /*
     * Read-only refresh after the one POST.
     * There is no automatic amendment retry and
     * no automatic manual-reconciliation POST.
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

  if (row?.active_amendment) {
    const status = String(
      row.active_amendment.status || ''
    ).trim();

    return {
      allowed: false,
      label: (
        status
          ? tradingOrderStatusLabel(
              status
            )
          : 'Amend unresolved'
      ),
      reason: 'active_amendment',
    };
  }

  if (
    requestId
    && (
      tradingState
        .persistentAmendPending
        .has(requestId)
      || tradingState
        .persistentAmendFrozen
        .has(requestId)
    )
  ) {
    return {
      allowed: false,
      label: 'Amend active',
      reason: 'amend_active',
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

  /*
   * A surviving recovery attempt from ANY
   * Trading write blocks another cancellation.
   *
   * This is especially important after browser
   * reload: an amendment checkpoint can hydrate
   * before Open Orders exposes active_amendment.
   */
  const unresolvedAttempt = [
    tradingState
      .limitOrderExecutionAttempt,
    tradingState
      .limitOrderCancellationAttempt,
    tradingState
      .limitOrderAmendmentAttempt,
  ].some(
    attempt => (
      attempt
      && attempt.definitive !== true
    )
  );

  if (unresolvedAttempt) {
    return {
      allowed: false,
      label: 'Recovery required',
      reason: 'recovery_required',
    };
  }

  const checkpointReader = (
    window
      .tradingLimitRecoveryCheckpointForUser
  );

  if (
    typeof checkpointReader
    !== 'function'
  ) {
    return {
      allowed: false,
      label: 'Unavailable',
      reason: 'recovery_unavailable',
    };
  }

  try {
    if (checkpointReader()) {
      return {
        allowed: false,
        label: 'Recovery required',
        reason: 'checkpoint_present',
      };
    }

  } catch {
    return {
      allowed: false,
      label: 'Review',
      reason: 'checkpoint_error',
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
        ? 'No open Gate orders for the selected account and market.'
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

      const amendEligibility = (
        tradingPersistentAmendEligibility(
          row
        )
      );

      const amendReconcileEligibility = (
        tradingPersistentAmendReconcileEligibility(
          row
        )
      );

      const amendmentReadModel = (
        tradingOrderAmendmentReadModel(
          row
        )
      );

      const actionButtons = [];

      if (
        amendReconcileEligibility.reconcilable
      ) {
        actionButtons.push(
          `
            <button
              type="button"
              class="trading-orders-reconcile-button"
              data-trading-amend-reconcile-request="${escapeHtml(
                amendReconcileEligibility.requestId
              )}"
              data-trading-amend-reconcile-id="${escapeHtml(
                amendReconcileEligibility.amendRequestId
              )}"
            >
              Check amendment
            </button>
          `
        );
      }

      if (amendEligibility.allowed) {
        actionButtons.push(
          `
            <button
              type="button"
              class="trading-orders-amend-button"
              data-trading-persistent-amend-request="${escapeHtml(
                amendEligibility.requestId
              )}"
            >
              Amend price
            </button>
          `
        );
      }

      if (cancelEligibility.allowed) {
        actionButtons.push(
          `
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
        );
      }

      let action;

      if (actionButtons.length) {
        action = `
          <div class="trading-orders-action-buttons">
            ${actionButtons.join('')}
          </div>
        `;

      } else {
        const reconcilePending = (
          amendReconcileEligibility.reason
          === 'pending'
        );

        const amendOperationalReason = [
          'pending',
          'frozen',
          'active_amendment',
          'recovery_required',
          'checkpoint_present',
          'checkpoint_error',
        ].includes(
          amendEligibility.reason
        );

        action = `
          <span class="trading-orders-action-note">
            ${escapeHtml(
              reconcilePending
                ? amendReconcileEligibility.label
                : amendOperationalReason
                  ? amendEligibility.label
                  : cancelEligibility.label
            )}
          </span>
        `;
      }

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

          <td>
            <span
              class="trading-orders-status ${
                amendmentReadModel.warning
                  ? 'warning'
                  : ''
              }"
              title="${escapeHtml(
                amendmentReadModel.title
              )}"
            >
              ${escapeHtml(
                amendmentReadModel.label
              )}
            </span>
          </td>

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
        ? 'No dashboard-managed order history for the selected account and market.'
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

      const amendReconcileEligibility = (
        tradingPersistentAmendReconcileEligibility(
          row
        )
      );

      const amendmentReadModel = (
        tradingOrderAmendmentReadModel(
          row
        )
      );

      const actionButtons = [];

      if (
        amendReconcileEligibility.reconcilable
      ) {
        actionButtons.push(
          `
            <button
              type="button"
              class="trading-orders-reconcile-button"
              data-trading-amend-reconcile-request="${escapeHtml(
                amendReconcileEligibility.requestId
              )}"
              data-trading-amend-reconcile-id="${escapeHtml(
                amendReconcileEligibility.amendRequestId
              )}"
            >
              Check amendment
            </button>
          `
        );
      }

      if (recovery.recoverable) {
        actionButtons.push(
          `
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
        );
      }

      const action = (
        actionButtons.length
          ? `
            <div class="trading-orders-action-buttons">
              ${actionButtons.join('')}
            </div>
          `
          : `
            <span class="trading-orders-action-note">
              ${escapeHtml(
                amendReconcileEligibility.reason
                  === 'pending'
                    ? amendReconcileEligibility.label
                    : recovery.label || '—'
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

          <td>
            <span
              class="trading-orders-status ${
                amendmentReadModel.warning
                  ? 'warning'
                  : ''
              }"
              title="${escapeHtml(
                amendmentReadModel.title
              )}"
            >
              ${escapeHtml(
                amendmentReadModel.label
              )}
            </span>
          </td>

          <td class="trading-orders-action-cell">
            ${action}
          </td>
        </tr>
      `;
    })
    .join('');
}


function tradingRenderPersistentOrders() {
  tradingRenderOpenOrders();
  tradingRenderRecentOrders();
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

    const loadCapabilities = (
      window.loadTradingExecutionCapabilities
    );

    if (
      typeof loadCapabilities !== 'function'
    ) {
      throw new Error(
        'Trading capability loader is unavailable.'
      );
    }

    await loadCapabilities();

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

  tradingState.limitOrderExecutionCapabilities = null;
  tradingState.loadingLimitOrderExecutionCapabilities = false;

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
      const target = (
        event.target instanceof Element
          ? event.target
          : null
      );

      if (!target) {
        return;
      }

      const reconcileButton = target.closest(
        '[data-trading-amend-reconcile-request]'
      );

      if (reconcileButton) {
        const requestId = String(
          reconcileButton.dataset
            .tradingAmendReconcileRequest
          || ''
        ).trim();

        const amendRequestId = String(
          reconcileButton.dataset
            .tradingAmendReconcileId
          || ''
        ).trim();

        if (
          requestId
          && amendRequestId
        ) {
          void tradingReconcilePersistentAmendment(
            requestId,
            amendRequestId,
          );
        }

        return;
      }

      const recoverButton = target.closest(
        '[data-trading-recover-request]'
      );

      if (!recoverButton) {
        return;
      }

      const requestId = String(
        recoverButton.dataset
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
      const target = (
        event.target instanceof Element
          ? event.target
          : null
      );

      if (!target) {
        return;
      }

      const reconcileButton = target.closest(
        '[data-trading-amend-reconcile-request]'
      );

      if (reconcileButton) {
        const requestId = String(
          reconcileButton.dataset
            .tradingAmendReconcileRequest
          || ''
        ).trim();

        const amendRequestId = String(
          reconcileButton.dataset
            .tradingAmendReconcileId
          || ''
        ).trim();

        if (
          requestId
          && amendRequestId
        ) {
          void tradingReconcilePersistentAmendment(
            requestId,
            amendRequestId,
          );
        }

        return;
      }

      const amendButton = target.closest(
        '[data-trading-persistent-amend-request]'
      );

      if (amendButton) {
        const requestId = String(
          amendButton.dataset
            .tradingPersistentAmendRequest
          || ''
        ).trim();

        if (requestId) {
          void tradingAmendPersistentOpenOrder(
            requestId
          );
        }

        return;
      }

      const cancelButton = target.closest(
        '[data-trading-persistent-cancel-request]'
      );

      if (!cancelButton) {
        return;
      }

      const requestId = String(
        cancelButton.dataset
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


window.tradingRenderPersistentOrders = (
  tradingRenderPersistentOrders
);

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
