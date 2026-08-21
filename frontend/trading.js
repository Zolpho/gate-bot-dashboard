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
  resizeObserver: null,
  refreshTimer: null,
  candleTimer: null,
  loadingCatalog: false,
  loadingSnapshot: false,
  loadingCandles: false,
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

  tradingState.chart = chart;
  tradingState.series = series;

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

  const rows = (
    Array.isArray(candles)
      ? candles
      : []
  )
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

  tradingUpdateChartPrecision();

  tradingState.series.setData(rows);

  if (!rows.length) {
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

      return `
        <div class="trading-book-row ${side}">
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
        </div>
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
    .slice(0, 8)
    .reverse();

  const bids = (
    book.bids || []
  )
    .slice(0, 8);

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
    `${tradingState.pair} · top 8 levels`
  );

  $('#tradingBalanceSubtitle').textContent = (
    `Gate spot · ${tradingState.accountId}`
  );
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

  tradingSetError('');

  if (tradingState.series) {
    tradingState.series.setData([]);
  }

  $('#tradingAccount').innerHTML = '';
  $('#tradingPair').value = '';
  $('#tradingPairOptions').innerHTML = '';
}


function bindTradingEvents() {
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

      void tradingLoadSnapshot();
    },
  );

  const pairInput = $('#tradingPair');

  const applyPair = () => {
    try {
      tradingValidatePair();

      tradingState.bookInterval = '0';
      tradingPopulateBookIntervals();

      void tradingRefreshAll();

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

        void tradingLoadSnapshot();
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
