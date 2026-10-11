'use strict';

(function installBotNativeActivityView() {
  function text(value) {
    return String(
      value === null
      || value === undefined
        ? ''
        : value
    ).trim();
  }


  function escapeHtml(value) {
    return text(value)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }


  function display(value) {
    const normalized = text(value);

    return normalized || '—';
  }


  function displayWithAsset(
    value,
    asset,
  ) {
    const normalized = text(value);

    if (!normalized) {
      return '—';
    }

    const normalizedAsset = text(
      asset
    );

    return normalizedAsset
      ? `${normalized} ${normalizedAsset}`
      : normalized;
  }


  function unixMilliseconds(value) {
    const numeric = Number(
      value
    );

    if (
      !Number.isFinite(numeric)
      || numeric <= 0
    ) {
      return null;
    }

    return (
      numeric > 100000000000
        ? numeric
        : numeric * 1000
    );
  }


  function formatUtc(value) {
    const milliseconds = (
      unixMilliseconds(value)
    );

    if (milliseconds === null) {
      return '—';
    }

    const date = new Date(
      milliseconds
    );

    if (
      !Number.isFinite(
        date.valueOf()
      )
    ) {
      return '—';
    }

    return (
      date
        .toISOString()
        .replace('T', ' ')
        .slice(0, 19)
      + ' UTC'
    );
  }


  function formatAge(
    value,
    nowMilliseconds = Date.now(),
  ) {
    const milliseconds = (
      unixMilliseconds(value)
    );

    if (milliseconds === null) {
      return '—';
    }

    const seconds = Math.max(
      0,
      Math.floor(
        (
          nowMilliseconds
          - milliseconds
        ) / 1000
      ),
    );

    if (seconds < 60) {
      return `${seconds}s`;
    }

    if (seconds < 3600) {
      return `${
        Math.floor(
          seconds / 60
        )
      }m`;
    }

    if (seconds < 86400) {
      return `${
        Math.floor(
          seconds / 3600
        )
      }h`;
    }

    return `${
      Math.floor(
        seconds / 86400
      )
    }d`;
  }


  function integerDisplay(
    value,
    fallback = 0,
  ) {
    const numeric = Number(
      value
    );

    if (!Number.isFinite(numeric)) {
      return fallback;
    }

    return Math.max(
      0,
      Math.trunc(numeric),
    );
  }


  function sideHtml(side) {
    const normalized = text(
      side
    ).toLowerCase();

    const label = (
      normalized === 'buy'
        ? 'Buy'
        : normalized === 'sell'
          ? 'Sell'
          : display(side)
    );

    const className = (
      normalized === 'buy'
      || normalized === 'sell'
        ? normalized
        : 'unknown'
    );

    return (
      `<span class="bot-native-side ${className}">`
      + `${escapeHtml(label)}`
      + '</span>'
    );
  }


  function emptyRow(
    columns,
    message,
  ) {
    return (
      '<tr>'
      + `<td colspan="${columns}" `
      + 'class="bot-native-empty">'
      + `${escapeHtml(message)}`
      + '</td>'
      + '</tr>'
    );
  }


  function buildViewModel(
    activity,
    {
      baseAsset = '',
      quoteAsset = '',
    } = {},
  ) {
    if (
      !activity
      || typeof activity !== 'object'
    ) {
      throw new Error(
        'Native bot activity model is required.'
      );
    }

    const openOrders = (
      activity.open_orders
      && typeof activity.open_orders
      === 'object'
        ? activity.open_orders
        : {}
    );

    const trades = (
      activity.trades
      && typeof activity.trades
      === 'object'
        ? activity.trades
        : {}
    );

    const openItems = (
      Array.isArray(
        openOrders.items
      )
        ? openOrders.items
        : []
    );

    const tradeItems = (
      Array.isArray(
        trades.items
      )
        ? trades.items
        : []
    );

    const openSummary = (
      openOrders.summary
      && typeof openOrders.summary
      === 'object'
        ? openOrders.summary
        : {}
    );

    const tradeSummary = (
      trades.summary
      && typeof trades.summary
      === 'object'
        ? trades.summary
        : {}
    );

    const pagination = (
      trades.pagination
      && typeof trades.pagination
      === 'object'
        ? trades.pagination
        : {}
    );

    const openCount = integerDisplay(
      openSummary.open_count,
      openItems.length,
    );

    const sellCount = integerDisplay(
      openSummary.sell_count,
      openItems.filter(
        item => (
          text(
            item?.side
          ).toLowerCase()
          === 'sell'
        )
      ).length,
    );

    const buyCount = integerDisplay(
      openSummary.buy_count,
      openItems.filter(
        item => (
          text(
            item?.side
          ).toLowerCase()
          === 'buy'
        )
      ).length,
    );

    const returnedTradeCount = (
      integerDisplay(
        tradeSummary.returned_count,
        tradeItems.length,
      )
    );

    const gateTotalCountValue = Number(
      pagination.total_count
      ?? tradeSummary.gate_total_count
    );

    const tradeCount = (
      Number.isFinite(
        gateTotalCountValue
      )
        ? Math.max(
            0,
            Math.trunc(
              gateTotalCountValue
            ),
          )
        : returnedTradeCount
    );

    const profitCount = integerDisplay(
      tradeSummary.positive_profit_count,
      tradeItems.filter(
        item => (
          item?.profit_positive
          === true
        )
      ).length,
    );

    return {
      strategyId: display(
        activity.strategy_id
      ),

      baseAsset: text(
        baseAsset
      ),

      quoteAsset: text(
        quoteAsset
      ),

      counters: {
        openCount,
        sellCount,
        buyCount,
        tradeCount,
        profitCount,
        returnedTradeCount,
      },

      openItems,
      tradeItems,
    };
  }


  function renderOpenOrders(
    model,
  ) {
    if (
      !model.openItems.length
    ) {
      return emptyRow(
        7,
        'No native open orders.',
      );
    }

    return model.openItems.map(
      item => {
        const orderIndex = (
          item?.order_index === null
          || item?.order_index
          === undefined
            ? '—'
            : `#${item.order_index}`
        );

        return (
          '<tr>'
          + `<td>${
            sideHtml(
              item?.side
            )
          }</td>`
          + '<td class="numeric">'
          + escapeHtml(
            displayWithAsset(
              item?.price,
              model.quoteAsset,
            )
          )
          + '</td>'
          + '<td class="numeric">'
          + escapeHtml(
            displayWithAsset(
              item?.quantity,
              model.baseAsset,
            )
          )
          + '</td>'
          + `<td>${escapeHtml(orderIndex)}</td>`
          + '<td class="mono">'
          + escapeHtml(
            display(
              item?.linked_order_id
            )
          )
          + '</td>'
          + '<td>'
          + escapeHtml(
            formatAge(
              item?.create_time
            )
          )
          + '</td>'
          + '<td class="mono">'
          + escapeHtml(
            display(
              item?.order_id
            )
          )
          + '</td>'
          + '</tr>'
        );
      }
    ).join('');
  }


  function renderTrades(
    model,
  ) {
    if (
      !model.tradeItems.length
    ) {
      return emptyRow(
        8,
        'No native trades.',
      );
    }

    return model.tradeItems.map(
      item => {
        const profitClass = (
          item?.profit_positive === true
            ? 'positive'
            : ''
        );

        const normalizedSide = text(
          item?.side
        ).toLowerCase();

        /*
         * Gate native grid records do not carry a
         * fee_currency field.
         *
         * The captured records show the normal spot
         * settlement convention:
         *
         *   buy  -> fee value is denominated in base
         *   sell -> fee value is denominated in quote
         *
         * gt_fee and point_fee remain separate raw fields
         * in the normalized model.
         */
        const feeAsset = (
          normalizedSide === 'buy'
            ? model.baseAsset
            : normalizedSide === 'sell'
              ? model.quoteAsset
              : ''
        );

        return (
          '<tr>'
          + '<td>'
          + escapeHtml(
            formatUtc(
              item?.finish_time
              ?? item?.create_time
            )
          )
          + '</td>'
          + `<td>${
            sideHtml(
              item?.side
            )
          }</td>`
          + '<td class="numeric">'
          + escapeHtml(
            displayWithAsset(
              item?.price,
              model.quoteAsset,
            )
          )
          + '</td>'
          + '<td class="numeric">'
          + escapeHtml(
            displayWithAsset(
              item?.quantity,
              model.baseAsset,
            )
          )
          + '</td>'
          + '<td class="numeric">'
          + escapeHtml(
            displayWithAsset(
              item?.match_amount,
              model.quoteAsset,
            )
          )
          + '</td>'
          + '<td class="numeric">'
          + escapeHtml(
            displayWithAsset(
              item?.fee,
              feeAsset,
            )
          )
          + '</td>'
          + `<td class="numeric ${profitClass}">`
          + escapeHtml(
            displayWithAsset(
              item?.profit,
              model.quoteAsset,
            )
          )
          + '</td>'
          + '<td class="mono">'
          + escapeHtml(
            display(
              item?.order_id
            )
          )
          + '</td>'
          + '</tr>'
        );
      }
    ).join('');
  }


  function render(
    activity,
    context = {},
  ) {
    const model = buildViewModel(
      activity,
      context,
    );

    const returned = (
      model.counters
        .returnedTradeCount
    );

    const total = (
      model.counters
        .tradeCount
    );

    const tradeStatus = (
      total === returned
        ? `${total} Gate trade${
            total === 1 ? '' : 's'
          }`
        : (
          `${total} Gate trades · `
          + `${returned} shown`
        )
    );

    return {
      strategyId:
        model.strategyId,

      counters:
        model.counters,

      openStatus: (
        `${model.counters.openCount} open · `
        + `${model.counters.sellCount} sell · `
        + `${model.counters.buyCount} buy`
      ),

      tradeStatus,

      openRowsHtml:
        renderOpenOrders(
          model
        ),

      tradeRowsHtml:
        renderTrades(
          model
        ),
    };
  }


  window.BotNativeActivityView = (
    Object.freeze({
      buildViewModel,
      render,
      formatUtc,
      formatAge,
    })
  );
})();
