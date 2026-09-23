(() => {
  'use strict';

  /*
   * Infinity Grid M4.2
   *
   * Shared Bot Control market catalogue and read-only
   * market context for Spot Grid + Infinity Grid.
   *
   * Safety:
   * - GET /api/trading/catalog only;
   * - GET /api/trading/snapshot only;
   * - no Gate write action exists here;
   * - changing market clears stale absolute prices;
   * - quote-denominated investment is cleared only when
   *   the selected quote currency itself changes.
   */

  const DATALIST_ID =
    'botControlMarketOptions';

  const SNAPSHOT_TTL_MS = 10_000;

  const FORMS = [
    {
      form:
        '#spotGridForm',
      market:
        '#spotGridMarket',
      account:
        '#spotGridAccount',
      reference:
        '#spotGridMarketReference',
      investmentCurrency:
        '#spotGridInvestmentCurrency',
      marketPriceFields: [
        'low_price',
        'high_price',
        'trigger_price',
        'stop_profit',
        'stop_loss',
      ],
    },
    {
      form:
        '#infiniteGridForm',
      market:
        '#infiniteGridMarket',
      account:
        '#infiniteGridAccount',
      reference:
        '#infiniteGridMarketReference',
      investmentCurrency:
        '#infiniteGridInvestmentCurrency',
      marketPriceFields: [
        'price_floor',
        'trigger_price',
        'stop_profit',
        'stop_loss',
      ],
    },
  ];

  let catalog = null;
  let pendingCatalog = null;

  const snapshotCache =
    new Map();

  const pendingSnapshots =
    new Map();


  function normalizeMarket(value) {
    return String(
      value || ''
    )
      .trim()
      .toUpperCase()
      .replace(
        /[-/]/g,
        '_',
      );
  }


  function marketParts(value) {
    const market = normalizeMarket(
      value
    );

    const match = market.match(
      /^([A-Z0-9]+)_([A-Z0-9]+)$/
    );

    if (!match) {
      return {
        market,
        base: '',
        quote: '',
      };
    }

    return {
      market,
      base: match[1],
      quote: match[2],
    };
  }


  function normalizedPairs(result) {
    const rows = (
      Array.isArray(result?.pairs)
        ? result.pairs
        : []
    );

    const seen = new Set();

    return rows
      .map(pair => {
        const id = normalizeMarket(
          pair?.id
          || (
            pair?.base
            && pair?.quote
              ? (
                `${pair.base}_${pair.quote}`
              )
              : ''
          )
        );

        const base = String(
          pair?.base || ''
        )
          .trim()
          .toUpperCase();

        const quote = String(
          pair?.quote || ''
        )
          .trim()
          .toUpperCase();

        return {
          id,
          base,
          quote,
        };
      })
      .filter(pair => {
        if (
          !pair.id
          || seen.has(pair.id)
        ) {
          return false;
        }

        seen.add(pair.id);
        return true;
      });
  }


  function renderCatalog(result) {
    const list = document.getElementById(
      DATALIST_ID
    );

    if (!list) {
      return;
    }

    const fragment =
      document.createDocumentFragment();

    normalizedPairs(result)
      .forEach(pair => {
        const option =
          document.createElement(
            'option'
          );

        option.value = pair.id;

        option.label = (
          pair.base
          && pair.quote
            ? `${pair.base} / ${pair.quote}`
            : pair.id
        );

        fragment.appendChild(
          option
        );
      });

    list.replaceChildren(
      fragment
    );
  }


  async function loadCatalog() {
    if (catalog) {
      renderCatalog(catalog);
      return catalog;
    }

    if (pendingCatalog) {
      return pendingCatalog;
    }

    if (
      typeof adminApi
      !== 'function'
    ) {
      return null;
    }

    pendingCatalog = (
      async () => {
        const result = await adminApi(
          '/api/trading/catalog'
        );

        if (
          !result
          || !Array.isArray(
            result.pairs
          )
          || result.write_performed
            !== false
          || result.market_data_only
            !== true
        ) {
          throw new Error(
            'Gate pair catalogue returned '
            + 'an invalid read-only response.'
          );
        }

        catalog = result;

        renderCatalog(
          catalog
        );

        return catalog;
      }
    )()
      .catch(() => null)
      .finally(() => {
        pendingCatalog = null;
      });

    return pendingCatalog;
  }


  function configElements(config) {
    return {
      form:
        document.querySelector(
          config.form
        ),
      market:
        document.querySelector(
          config.market
        ),
      account:
        document.querySelector(
          config.account
        ),
      reference:
        document.querySelector(
          config.reference
        ),
      investmentCurrency:
        document.querySelector(
          config.investmentCurrency
        ),
    };
  }


  function setReference(
    config,
    text,
    state = '',
  ) {
    const element =
      document.querySelector(
        config.reference
      );

    if (!element) {
      return;
    }

    element.textContent = text;

    element.classList.remove(
      'is-loading',
      'is-live',
      'is-unavailable',
    );

    if (state) {
      element.classList.add(
        state
      );
    }
  }


  function updateInvestmentCurrency(
    config,
    marketValue,
  ) {
    const parts = marketParts(
      marketValue
    );

    const element =
      document.querySelector(
        config.investmentCurrency
      );

    if (!element) {
      return;
    }

    element.textContent = (
      parts.quote
      || 'QUOTE'
    );
  }


  function clearNamedField(
    form,
    name,
  ) {
    const field = form?.elements?.namedItem(
      name
    );

    if (
      field
      && 'value' in field
    ) {
      field.value = '';
    }
  }


  function clearMarketBoundValues(
    config,
    previousMarket,
    nextMarket,
  ) {
    const elements =
      configElements(config);

    if (!elements.form) {
      return;
    }

    const previous =
      marketParts(
        previousMarket
      );

    const next =
      marketParts(
        nextMarket
      );

    if (
      !previous.market
      || !next.market
      || previous.market === next.market
    ) {
      return;
    }

    config.marketPriceFields
      .forEach(name => {
        clearNamedField(
          elements.form,
          name
        );
      });

    /*
     * The investment amount is denominated in quote
     * currency. Preserve it for ETH_USDT -> BTC_USDT,
     * but never silently reinterpret 100 USDT as
     * 100 BTC (or another quote asset).
     */
    if (
      previous.quote
      && next.quote
      && previous.quote !== next.quote
    ) {
      clearNamedField(
        elements.form,
        'money'
      );
    }
  }


  function snapshotKey(
    account,
    market,
  ) {
    return (
      `${String(account || '')
        .trim()
        .toLowerCase()}|`
      + normalizeMarket(
        market
      )
    );
  }


  function snapshotStillCurrent(
    config,
    account,
    market,
  ) {
    const elements =
      configElements(config);

    return (
      String(
        elements.account?.value
        || ''
      )
        .trim()
        .toLowerCase()
      === String(
        account || ''
      )
        .trim()
        .toLowerCase()
      && normalizeMarket(
        elements.market?.value
      ) === normalizeMarket(
        market
      )
    );
  }


  function decimalPlacesFromText(
    value,
  ) {
    const text = String(
      value || ''
    )
      .trim()
      .toLowerCase();

    if (!text) {
      return 0;
    }

    const exponentMatch = text.match(
      /^([+-]?\d+)(?:\.(\d*))?e([+-]?\d+)$/
    );

    if (exponentMatch) {
      const fractionLength = (
        exponentMatch[2] || ''
      ).length;

      const exponent = Number(
        exponentMatch[3]
      );

      return Math.max(
        0,
        fractionLength - exponent,
      );
    }

    const dot = text.indexOf(
      '.'
    );

    return (
      dot < 0
        ? 0
        : text.length - dot - 1
    );
  }


  function marketPricePrecision(
    market,
    values,
  ) {
    const pair = (
      Array.isArray(
        catalog?.pairs
      )
        ? catalog.pairs.find(
            item => (
              normalizeMarket(
                item?.id
              )
              === normalizeMarket(
                market
              )
            )
          )
        : null
    );

    const configured = Number(
      pair?.precision
    );

    if (
      Number.isInteger(
        configured
      )
      && configured >= 0
      && configured <= 20
    ) {
      return configured;
    }

    const inferred = Math.max(
      0,
      ...values.map(
        decimalPlacesFromText
      ),
    );

    return Math.min(
      inferred,
      20,
    );
  }


  function formatCalculatedPrice(
    value,
    precision,
  ) {
    const number = Number(
      value
    );

    if (
      !Number.isFinite(
        number
      )
      || number <= 0
    ) {
      return '';
    }

    const digits = Math.max(
      0,
      Math.min(
        Number(
          precision
        ) || 0,
        20,
      ),
    );

    const fixed = number.toFixed(
      digits
    );

    if (!fixed.includes('.')) {
      return fixed;
    }

    return fixed
      .replace(
        /0+$/,
        '',
      )
      .replace(
        /\.$/,
        '',
      );
  }


  function renderSnapshot(
    config,
    result,
  ) {
    const ticker = (
      result?.ticker
      || {}
    );

    const orderBook = (
      result?.order_book
      || {}
    );

    const pair = (
      result?.pair
      || {}
    );

    const last = String(
      ticker.last || ''
    ).trim();

    const bestBid = String(
      orderBook.best_bid
      || ticker.highest_bid
      || ''
    ).trim();

    const bestAsk = String(
      orderBook.best_ask
      || ticker.lowest_ask
      || ''
    ).trim();

    const quote = String(
      pair.quote || ''
    )
      .trim()
      .toUpperCase();

    const market = normalizeMarket(
      pair.id || ''
    );

    const bidNumber = Number(
      bestBid
    );

    const askNumber = Number(
      bestAsk
    );

    if (
      Number.isFinite(
        bidNumber
      )
      && bidNumber > 0
      && Number.isFinite(
        askNumber
      )
      && askNumber > 0
      && askNumber >= bidNumber
    ) {
      const midpoint = (
        bidNumber + askNumber
      ) / 2;

      /*
       * Informational liquidity band only.
       *
       * Nothing here modifies Spot Grid ranges,
       * Infinity Grid floor, profit-per-grid,
       * or any Gate order.
       */
      const lowerBand = (
        midpoint * 0.98
      );

      const upperBand = (
        midpoint * 1.02
      );

      const precision = (
        marketPricePrecision(
          market,
          [
            bestBid,
            bestAsk,
            last,
          ],
        )
      );

      const bidText = (
        formatCalculatedPrice(
          bidNumber,
          precision,
        )
      );

      const askText = (
        formatCalculatedPrice(
          askNumber,
          precision,
        )
      );

      const midText = (
        formatCalculatedPrice(
          midpoint,
          precision,
        )
      );

      const lowerText = (
        formatCalculatedPrice(
          lowerBand,
          precision,
        )
      );

      const upperText = (
        formatCalculatedPrice(
          upperBand,
          precision,
        )
      );

      setReference(
        config,
        (
          `Bid ${bidText}`
          + ` · Ask ${askText}`
          + ` · Mid ${midText}`
          + ` · ±2% ${lowerText}–${upperText}`
          + `${quote ? ` ${quote}` : ''}`
        ),
        'is-live',
      );

      return;
    }

    const fallback = [];

    if (last) {
      fallback.push(
        `Last ${last}`
      );
    }

    if (bestBid) {
      fallback.push(
        `Bid ${bestBid}`
      );
    }

    if (bestAsk) {
      fallback.push(
        `Ask ${bestAsk}`
      );
    }

    if (!fallback.length) {
      setReference(
        config,
        'Live market reference unavailable.',
        'is-unavailable',
      );

      return;
    }

    setReference(
      config,
      (
        fallback.join(
          ' · '
        )
        + `${quote ? ` ${quote}` : ''}`
      ),
      'is-live',
    );
  }


  async function getSnapshot(
    account,
    market,
  ) {
    const key = snapshotKey(
      account,
      market,
    );

    const cached =
      snapshotCache.get(
        key
      );

    if (
      cached
      && (
        Date.now()
        - cached.loadedAt
      ) < SNAPSHOT_TTL_MS
    ) {
      return cached.result;
    }

    if (
      pendingSnapshots.has(
        key
      )
    ) {
      return pendingSnapshots.get(
        key
      );
    }

    const params =
      new URLSearchParams({
        account_id:
          String(
            account || ''
          )
            .trim()
            .toLowerCase(),
        pair:
          normalizeMarket(
            market
          ),
        depth:
          '5',
        book_interval:
          '0',
      });

    const pending = (
      async () => {
        const result = await adminApi(
          (
            '/api/trading/snapshot?'
            + params.toString()
          )
        );

        if (
          !result
          || result.write_performed
            !== false
          || result.market_data_only
            !== true
          || normalizeMarket(
            result?.pair?.id
          ) !== normalizeMarket(
            market
          )
        ) {
          throw new Error(
            'Gate snapshot returned '
            + 'an invalid read-only response.'
          );
        }

        snapshotCache.set(
          key,
          {
            loadedAt:
              Date.now(),
            result,
          },
        );

        return result;
      }
    )()
      .finally(() => {
        pendingSnapshots.delete(
          key
        );
      });

    pendingSnapshots.set(
      key,
      pending,
    );

    return pending;
  }


  async function refreshMarketReference(
    config,
  ) {
    const elements =
      configElements(config);

    const account = String(
      elements.account?.value
      || ''
    )
      .trim()
      .toLowerCase();

    const parts = marketParts(
      elements.market?.value
    );

    updateInvestmentCurrency(
      config,
      parts.market,
    );

    if (
      !account
      || !parts.base
      || !parts.quote
    ) {
      setReference(
        config,
        'Select a valid market to load live price.',
        'is-unavailable',
      );

      return null;
    }

    if (
      typeof adminApi
      !== 'function'
    ) {
      setReference(
        config,
        'Live market reference unavailable.',
        'is-unavailable',
      );

      return null;
    }

    setReference(
      config,
      'Loading live market reference…',
      'is-loading',
    );

    try {
      const result = await getSnapshot(
        account,
        parts.market,
      );

      if (
        snapshotStillCurrent(
          config,
          account,
          parts.market,
        )
      ) {
        renderSnapshot(
          config,
          result
        );
      }

      return result;

    } catch {
      if (
        snapshotStillCurrent(
          config,
          account,
          parts.market,
        )
      ) {
        setReference(
          config,
          'Live market reference unavailable.',
          'is-unavailable',
        );
      }

      return null;
    }
  }


  function refreshAllReferences() {
    FORMS.forEach(
      config => {
        void refreshMarketReference(
          config
        );
      },
    );
  }


  function commitMarket(
    config,
    input,
  ) {
    const previous = normalizeMarket(
      input.dataset
        .botControlCommittedMarket
      || ''
    );

    const next = normalizeMarket(
      input.value
    );

    input.value = next;

    updateInvestmentCurrency(
      config,
      next,
    );

    if (
      previous
      && next
      && previous !== next
    ) {
      clearMarketBoundValues(
        config,
        previous,
        next,
      );
    }

    input.dataset
      .botControlCommittedMarket =
      next;

    void refreshMarketReference(
      config
    );
  }


  function syncAfterReset(
    config,
    input,
  ) {
    setTimeout(
      () => {
        const market = normalizeMarket(
          input.value
        );

        input.dataset
          .botControlCommittedMarket =
          market;

        updateInvestmentCurrency(
          config,
          market,
        );

        void refreshMarketReference(
          config
        );
      },
      0,
    );
  }


  function bindMarketInput(
    config,
  ) {
    const elements =
      configElements(config);

    const input =
      elements.market;

    if (
      !input
      || input.dataset
        .botControlMarketPickerBound
    ) {
      return;
    }

    input.dataset
      .botControlMarketPickerBound =
      '1';

    input.dataset
      .botControlCommittedMarket =
      normalizeMarket(
        input.value
      );

    updateInvestmentCurrency(
      config,
      input.value,
    );

    input.addEventListener(
      'focus',
      () => {
        void loadCatalog();
        void refreshMarketReference(
          config
        );
      },
    );

    input.addEventListener(
      'input',
      () => {
        const upper = String(
          input.value || ''
        ).toUpperCase();

        if (
          input.value !== upper
        ) {
          input.value = upper;
        }

        updateInvestmentCurrency(
          config,
          input.value,
        );

        if (!catalog) {
          void loadCatalog();
        }
      },
    );

    input.addEventListener(
      'change',
      () => {
        commitMarket(
          config,
          input,
        );
      },
    );

    elements.form
      ?.addEventListener(
        'reset',
        () => {
          syncAfterReset(
            config,
            input,
          );
        },
      );
  }


  function bindAccountRefresh() {
    for (const selector of [
      '#spotGridAccount',
      '#infiniteGridAccount',
    ]) {
      const account =
        document.querySelector(
          selector
        );

      if (
        !account
        || account.dataset
          .botControlMarketReferenceBound
      ) {
        continue;
      }

      account.dataset
        .botControlMarketReferenceBound =
        '1';

      account.addEventListener(
        'change',
        () => {
          /*
           * Account synchronization between Spot and
           * Infinity may run in another listener.
           * Refresh after the current change event.
           */
          setTimeout(
            refreshAllReferences,
            0,
          );
        },
      );
    }
  }


  function start() {
    FORMS.forEach(
      bindMarketInput
    );

    bindAccountRefresh();

    document.querySelector(
      '[data-tab="bot-control"]'
    )?.addEventListener(
      'click',
      () => {
        void loadCatalog();

        setTimeout(
          refreshAllReferences,
          0,
        );
      },
    );
  }


  window.loadBotControlMarketCatalog =
    loadCatalog;

  window.refreshBotControlMarketReferences =
    refreshAllReferences;


  if (
    document.readyState
    === 'loading'
  ) {
    document.addEventListener(
      'DOMContentLoaded',
      start,
      {
        once: true,
      },
    );

  } else {
    start();
  }
})();
