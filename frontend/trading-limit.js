'use strict';

tradingState.limitOrderSide = 'buy';
tradingState.limitOrderPercent = null;
tradingState.limitOrderPreview = null;
tradingState.loadingLimitOrderPreview = false;
tradingState.limitOrderExecutionCapabilities = null;
tradingState.loadingLimitOrderExecutionCapabilities = false;
function tradingLimitAmountDigits() {
  const precision = Number(
    tradingPairDefinition()?.amount_precision
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


function tradingLimitAssets() {
  const pair = (
    tradingState.snapshot?.pair
    || tradingPairDefinition()
    || {}
  );

  const fallback = String(
    tradingState.pair || ''
  ).split('_');

  return {
    base: String(
      pair.base || fallback[0] || ''
    ).toUpperCase(),

    quote: String(
      pair.quote || fallback[1] || ''
    ).toUpperCase(),
  };
}


function tradingLimitAvailable() {
  const balances = (
    tradingState.snapshot?.balances
    || {}
  );

  const value = (
    tradingState.limitOrderSide === 'buy'
      ? balances.quote?.available
      : balances.base?.available
  );

  return tradingNumeric(value) ?? 0;
}


function tradingLimitFloor(
  value,
  digits,
) {
  if (!Number.isFinite(value)) {
    return 0;
  }

  if (digits <= 0) {
    return Math.floor(
      value + Number.EPSILON
    );
  }

  const factor = 10 ** digits;

  return (
    Math.floor(
      (
        value
        + Number.EPSILON
      )
      * factor
    )
    / factor
  );
}


function tradingLimitText(
  value,
  digits = 8,
) {
  if (!Number.isFinite(value)) {
    return '';
  }

  if (digits <= 0) {
    return String(
      Math.trunc(value)
    );
  }

  return value
    .toFixed(digits)
    .replace(/\.?0+$/, '');
}


function tradingLimitValues() {
  const price = tradingNumeric(
    $('#tradingLimitPrice')?.value
  );

  const amount = tradingNumeric(
    $('#tradingLimitAmount')?.value
  );

  return {
    price,
    amount,

    total: (
      price !== null
      && amount !== null
        ? price * amount
        : null
    ),
  };
}


function clearTradingLimitOrderPreview() {
  tradingState.limitOrderPreview = null;
  tradingState.limitOrderExecutionCapabilities = null;

  const preview = $(
    '#tradingLimitOrderPreview'
  );

  if (preview) {
    preview.innerHTML = '';
    preview.classList.add('hidden');
  }

  const error = $(
    '#tradingLimitOrderError'
  );

  if (error) {
    error.textContent = '';
    error.classList.add('hidden');
  }
  renderTradingLimitExecution();
}


function resetTradingLimitOrderTicket() {
  clearTradingLimitOrderPreview();

  tradingState.limitOrderPercent = null;

  const price = $('#tradingLimitPrice');
  const amount = $('#tradingLimitAmount');

  if (price) {
    price.value = '';
  }

  if (amount) {
    amount.value = '';
  }

  const hint = $('#tradingLimitHint');

  if (hint) {
    hint.textContent = (
      'Click any bid or ask price to copy it here.'
    );
  }

  renderTradingLimitOrderTicket();
}


function renderTradingLimitOrderTicket() {
  const form = $('#tradingLimitOrderForm');

  if (!form) {
    return;
  }

  const {
    base,
    quote,
  } = tradingLimitAssets();

  $$(
    '[data-trading-order-side]'
  ).forEach(button => {
    button.classList.toggle(
      'active',
      button.dataset.tradingOrderSide
      === tradingState.limitOrderSide,
    );
  });

  const priceAsset = $(
    '#tradingLimitPriceAsset'
  );

  const amountAsset = $(
    '#tradingLimitAmountAsset'
  );

  const totalAsset = $(
    '#tradingLimitTotalAsset'
  );

  if (priceAsset) {
    priceAsset.textContent = quote || 'Quote';
  }

  if (amountAsset) {
    amountAsset.textContent = base || 'Base';
  }

  if (totalAsset) {
    totalAsset.textContent = quote || 'Quote';
  }

  const priceInput = $('#tradingLimitPrice');
  const amountInput = $('#tradingLimitAmount');

  const priceDigits = tradingPriceDigits();
  const amountDigits = tradingLimitAmountDigits();

  if (priceInput) {
    priceInput.step = (
      priceDigits <= 0
        ? '1'
        : (
            10 ** (-priceDigits)
          ).toFixed(priceDigits)
    );
  }

  if (amountInput) {
    amountInput.step = (
      amountDigits <= 0
        ? '1'
        : (
            10 ** (-amountDigits)
          ).toFixed(amountDigits)
    );
  }

  const values = tradingLimitValues();

  const total = $('#tradingLimitTotal');

  if (total) {
    total.textContent = (
      values.total === null
        ? '—'
        : tradingLimitText(
            values.total,
            8,
          )
    );
  }

  const available = tradingLimitAvailable();

  const availableElement = $(
    '#tradingLimitAvailable'
  );

  if (availableElement) {
    const asset = (
      tradingState.limitOrderSide === 'buy'
        ? quote
        : base
    );

    availableElement.textContent = (
      `${tradingFormatAmount(available)} `
      + `${asset} available for `
      + `${tradingState.limitOrderSide.toUpperCase()}`
    );
  }

  const buyNeedsPrice = (
    tradingState.limitOrderSide === 'buy'
    && !(
      values.price !== null
      && values.price > 0
    )
  );

  $$(
    '[data-trading-order-percent]'
  ).forEach(button => {
    const percentage = Number(
      button.dataset.tradingOrderPercent
    );

    button.disabled = (
      buyNeedsPrice
      || available <= 0
    );

    button.classList.toggle(
      'active',
      percentage
      === tradingState.limitOrderPercent,
    );
  });

  const review = $(
    '#reviewTradingLimitOrder'
  );

  if (review) {
    review.disabled = Boolean(
      tradingState.loadingLimitOrderPreview
      || !tradingState.accountId
      || !tradingState.pair
      || values.price === null
      || values.price <= 0
      || values.amount === null
      || values.amount <= 0
    );
  }
}


function renderTradingLimitExecution() {
  const element = $(
    '#tradingLimitExecution'
  );

  if (!element) {
    return;
  }

  const preview = (
    tradingState.limitOrderPreview
  );

  const capabilities = (
    tradingState
      .limitOrderExecutionCapabilities
  );

  const ready = (
    String(
      preview?.status || ''
    ).toLowerCase()
    === 'ready'
  );

  if (!ready) {
    element.classList.add(
      'hidden'
    );

    return;
  }

  element.classList.remove(
    'hidden'
  );

  const status = $(
    '#tradingLimitExecutionStatus'
  );

  const message = $(
    '#tradingLimitExecutionMessage'
  );

  const requiredElement = $(
    '#tradingLimitRequiredConfirmation'
  );

  const confirmation = $(
    '#tradingLimitConfirmation'
  );

  const button = $(
    '#placeTradingLimitOrder'
  );

  const accountId = String(
    tradingState.accountId || ''
  ).toLowerCase();

  const configuredAccounts = (
    capabilities
      ?.configured_account_ids
    || []
  ).map(
    value => String(
      value || ''
    ).toLowerCase()
  );

  const implemented = (
    capabilities
      ?.execution_implemented
    === true
  );

  const routeAvailable = (
    capabilities
      ?.execution_route_available
    === true
  );

  const accountConfigured = (
    configuredAccounts.includes(
      accountId
    )
  );

  const liveArmEnabled = (
    capabilities
      ?.live_arm_enabled
    === true
  );

  const required = String(
    capabilities
      ?.required_confirmation
    || ''
  );

  const configError = String(
    capabilities
      ?.config_error
    || ''
  );

  if (status) {
    status.classList.remove(
      'disabled',
      'ready',
      'warning',
    );
  }

  let label = 'LIVE DISABLED';

  let description = (
    'Live Spot order placement is disabled '
    + 'by the backend.'
  );

  let statusClass = 'disabled';

  if (
    tradingState
      .loadingLimitOrderExecutionCapabilities
  ) {
    label = 'CHECKING';

    description = (
      'Checking backend execution state…'
    );

  } else if (configError) {
    label = 'CONFIG ERROR';
    description = configError;
    statusClass = 'warning';

  } else if (
    !implemented
    || !routeAvailable
  ) {
    label = 'UNAVAILABLE';

    description = (
      'The guarded Spot execution backend '
      + 'is unavailable.'
    );

    statusClass = 'warning';

  } else if (!accountConfigured) {
    label = 'NO TRADING KEY';

    description = (
      'This account has no enabled isolated '
      + 'Spot Trading credential.'
    );

    statusClass = 'warning';

  } else if (liveArmEnabled) {
    label = 'BACKEND ARMED';

    /*
     * Stage 3G1 deliberately keeps the browser
     * write control disabled even if the backend
     * reports itself armed.
     */
    description = (
      'The backend reports live Trading armed, '
      + 'but this frontend build intentionally '
      + 'does not submit orders yet.'
    );

    statusClass = 'ready';
  }

  if (status) {
    status.textContent = label;

    status.classList.add(
      statusClass
    );
  }

  if (message) {
    message.textContent = (
      description
    );
  }

  if (requiredElement) {
    requiredElement.textContent = (
      required || '—'
    );
  }

  if (confirmation) {
    confirmation.disabled = !(
      implemented
      && routeAvailable
      && accountConfigured
      && liveArmEnabled
      && required
    );

    if (!liveArmEnabled) {
      confirmation.value = '';
    }
  }

  if (button) {
    /*
     * Hard Stage 3G1 safety boundary:
     * this browser build has no execute caller.
     */
    button.disabled = true;

    button.title = liveArmEnabled
      ? (
          'Frontend execution is intentionally '
          + 'not activated in this build.'
        )
      : (
          'Live Trading is disabled by the backend.'
        );
  }
}


async function loadTradingExecutionCapabilities() {
  if (
    tradingState
      .loadingLimitOrderExecutionCapabilities
  ) {
    return;
  }

  tradingState
    .loadingLimitOrderExecutionCapabilities = true;

  renderTradingLimitExecution();

  try {
    const result = await adminApi(
      '/api/trading/execution-capabilities'
    );

    if (
      result.execution_implemented !== true
      || result.execution_route_available !== true
      || result.gate_write_performed !== false
      || result.write_performed !== false
    ) {
      throw new Error(
        'Safety invariant failed: invalid '
        + 'Trading execution capability response.'
      );
    }

    tradingState
      .limitOrderExecutionCapabilities = result;

  } catch (error) {
    tradingState
      .limitOrderExecutionCapabilities = {
        execution_implemented: false,
        execution_route_available: false,
        live_arm_enabled: false,
        configured_account_ids: [],
        required_confirmation: '',
        config_error: (
          error.message
          || 'Execution capability check failed.'
        ),
      };

  } finally {
    tradingState
      .loadingLimitOrderExecutionCapabilities = false;

    renderTradingLimitExecution();
  }
}


function renderTradingLimitOrderPreview(
  preview,
) {
  const element = $(
    '#tradingLimitOrderPreview'
  );

  if (!element) {
    return;
  }

  const order = preview?.order || {};
  const funds = preview?.funds || {};
  const market = preview?.market || {};

  const blockers = preview?.blockers || [];
  const warnings = preview?.warnings || [];

  const ready = (
    String(
      preview?.status || ''
    ).toLowerCase()
    === 'ready'
  );

  const cards = [
    ['Account', preview.account_id],
    ['Side', String(order.side || '').toUpperCase()],
    ['Price', order.price],
    ['Amount', order.amount],
    ['Total', order.total],
    [
      'Time in force',
      String(
        order.time_in_force || ''
      ).toUpperCase(),
    ],
    [
      'Funds required',
      `${funds.required || '—'} ${funds.asset || ''}`,
    ],
    [
      'Available',
      `${funds.available || '—'} ${funds.asset || ''}`,
    ],
    [
      'Remaining',
      `${funds.remaining || '—'} ${funds.asset || ''}`,
    ],
    ['Best bid', market.best_bid],
    ['Best ask', market.best_ask],
    [
      'Marketable now',
      market.marketable ? 'YES' : 'NO',
    ],
  ];

  const cardsHtml = cards
    .map(([label, value]) => `
      <div class="trading-order-preview-card">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value || '—')}</strong>
      </div>
    `)
    .join('');

  const blockerHtml = blockers.length
    ? `
      <div>
        <strong>Blockers</strong>
        <ul class="trading-order-preview-list blockers">
          ${blockers.map(
            item => `<li>${escapeHtml(item)}</li>`
          ).join('')}
        </ul>
      </div>
    `
    : '';

  const warningHtml = warnings.length
    ? `
      <div>
        <strong>Warnings</strong>
        <ul class="trading-order-preview-list">
          ${warnings.map(
            item => `<li>${escapeHtml(item)}</li>`
          ).join('')}
        </ul>
      </div>
    `
    : '';

  element.innerHTML = `
    <div class="trading-order-preview-head">
      <strong>Limit-order preflight</strong>

      <span
        class="trading-order-preview-status ${
          ready ? 'ready' : 'invalid'
        }"
      >
        ${ready ? 'READY' : 'BLOCKED'}
      </span>
    </div>

    <div class="trading-order-preview-grid">
      ${cardsHtml}
    </div>

    ${blockerHtml}
    ${warningHtml}

    <div class="trading-order-safety">
      <span>
        Preview:
        <strong>READ ONLY</strong>
      </span>

      <span>
        Execution:
        <strong>SEPARATE STEP</strong>
      </span>

      <span>
        Gate write:
        <strong>NOT PERFORMED</strong>
      </span>
    </div>
  `;

  element.classList.remove('hidden');
}


async function reviewTradingLimitOrder() {
  if (
    tradingState.loadingLimitOrderPreview
  ) {
    return;
  }

  const values = tradingLimitValues();

  if (
    values.price === null
    || values.price <= 0
    || values.amount === null
    || values.amount <= 0
  ) {
    return;
  }

  tradingState.loadingLimitOrderPreview = true;

  const button = $(
    '#reviewTradingLimitOrder'
  );

  if (button) {
    button.disabled = true;
    button.textContent = 'Reviewing…';
  }

  clearTradingLimitOrderPreview();

  try {
    const result = await adminApi(
      '/api/trading/limit-orders/preview',
      {
        method: 'POST',

        body: JSON.stringify({
          account_id: tradingState.accountId,
          pair: tradingState.pair,
          side: tradingState.limitOrderSide,
          price: String(
            $('#tradingLimitPrice').value
          ),
          amount: String(
            $('#tradingLimitAmount').value
          ),
          time_in_force: String(
            $('#tradingLimitTif').value
            || 'gtc'
          ),
        }),
      },
    );

    if (
      result.execution_implemented !== false
      || result.execution_enabled !== false
      || result.can_execute !== false
      || result.gate_write_performed !== false
      || result.write_performed !== false
    ) {
      throw new Error(
        'Safety invariant failed: preview endpoint '
        + 'reported an executable or written order.'
      );
    }

    tradingState.limitOrderPreview = result;

    renderTradingLimitOrderPreview(
      result
    );


    await loadTradingExecutionCapabilities();
} catch (error) {
    const box = $(
      '#tradingLimitOrderError'
    );

    if (box) {
      box.textContent = (
        error.message
        || 'Limit-order preflight failed.'
      );

      box.classList.remove('hidden');
    }

    showToast(
      error.message
      || 'Limit-order preflight failed.',
      true,
    );

  } finally {
    tradingState.loadingLimitOrderPreview = false;

    if (button) {
      button.textContent = 'Review limit order';
    }

    renderTradingLimitOrderTicket();
  }
}


function applyTradingLimitPercentage(
  percentage,
) {
  const percent = Number(percentage);

  if (
    !Number.isFinite(percent)
    || percent <= 0
    || percent > 100
  ) {
    return;
  }

  const available = tradingLimitAvailable();

  const price = tradingNumeric(
    $('#tradingLimitPrice')?.value
  );

  tradingState.limitOrderPercent = percent;

  let amount;

  if (tradingState.limitOrderSide === 'buy') {
    if (
      price === null
      || price <= 0
    ) {
      return;
    }

    amount = (
      available
      * percent
      / 100
      / price
    );

  } else {
    amount = (
      available
      * percent
      / 100
    );
  }

  amount = tradingLimitFloor(
    amount,
    tradingLimitAmountDigits(),
  );

  const input = $('#tradingLimitAmount');

  if (input) {
    input.value = tradingLimitText(
      amount,
      tradingLimitAmountDigits(),
    );
  }

  clearTradingLimitOrderPreview();
  renderTradingLimitOrderTicket();
}


function reapplyTradingLimitPercentage() {
  const percentage = (
    tradingState.limitOrderPercent
  );

  if (
    percentage === null
    || percentage === undefined
  ) {
    return;
  }

  applyTradingLimitPercentage(
    percentage
  );
}


function useTradingBookPrice(row) {
  const price = String(
    row.dataset.tradingBookPrice || ''
  );

  if (!price) {
    return;
  }

  const input = $('#tradingLimitPrice');

  if (input) {
    input.value = price;
  }

  $$(
    '.trading-book-row.selected',
    $('#tradingBookView')
  ).forEach(item => {
    item.classList.remove('selected');
  });

  row.classList.add('selected');

  setTimeout(
    () => row.classList.remove('selected'),
    650,
  );

  const side = String(
    row.dataset.tradingBookSide || ''
  );

  const hint = $('#tradingLimitHint');

  if (hint) {
    hint.textContent = (
      `${side === 'ask' ? 'Ask' : 'Bid'} `
      + `${price} copied to Price. `
      + 'Buy/Sell was not changed.'
    );
  }

  clearTradingLimitOrderPreview();

  if (
    tradingState.limitOrderSide === 'buy'
    && tradingState.limitOrderPercent !== null
  ) {
    reapplyTradingLimitPercentage();
  } else {
    renderTradingLimitOrderTicket();
  }

  input?.focus();
}


function bindTradingLimitOrderEvents() {
  $('#tradingBookView')?.addEventListener(
    'click',
    event => {
      const row = (
        event.target instanceof Element
          ? event.target.closest(
              '[data-trading-book-price]'
            )
          : null
      );

      if (row) {
        useTradingBookPrice(row);
      }
    },
  );

  $('.trading-order-side-tabs')?.addEventListener(
    'click',
    event => {
      const button = (
        event.target instanceof Element
          ? event.target.closest(
              '[data-trading-order-side]'
            )
          : null
      );

      if (!button) return;

      const side = String(
        button.dataset.tradingOrderSide || ''
      );

      if (
        side !== 'buy'
        && side !== 'sell'
      ) {
        return;
      }

      tradingState.limitOrderSide = side;
      tradingState.limitOrderPercent = null;

      const amount = $('#tradingLimitAmount');

      if (amount) {
        amount.value = '';
      }

      clearTradingLimitOrderPreview();
      renderTradingLimitOrderTicket();
    },
  );

  $('#tradingLimitPrice')?.addEventListener(
    'input',
    () => {
      clearTradingLimitOrderPreview();

      if (
        tradingState.limitOrderSide === 'buy'
        && tradingState.limitOrderPercent !== null
      ) {
        reapplyTradingLimitPercentage();
      } else {
        renderTradingLimitOrderTicket();
      }
    },
  );

  $('#tradingLimitAmount')?.addEventListener(
    'input',
    () => {
      tradingState.limitOrderPercent = null;

      clearTradingLimitOrderPreview();
      renderTradingLimitOrderTicket();
    },
  );

  $('#tradingLimitTif')?.addEventListener(
    'change',
    () => {
      clearTradingLimitOrderPreview();
      renderTradingLimitOrderTicket();
    },
  );

  $('.trading-order-percentages')?.addEventListener(
    'click',
    event => {
      const button = (
        event.target instanceof Element
          ? event.target.closest(
              '[data-trading-order-percent]'
            )
          : null
      );

      if (button) {
        applyTradingLimitPercentage(
          button.dataset.tradingOrderPercent
        );
      }
    },
  );

  $('#reviewTradingLimitOrder')?.addEventListener(
    'click',
    () => {
      void reviewTradingLimitOrder();
    },
  );

  $('#tradingAccount')?.addEventListener(
    'change',
    resetTradingLimitOrderTicket,
  );

  $('#tradingPair')?.addEventListener(
    'change',
    resetTradingLimitOrderTicket,
  );

  $('#accountSelector')?.addEventListener(
    'change',
    resetTradingLimitOrderTicket,
  );
}


window.renderTradingLimitOrderTicket = (
  renderTradingLimitOrderTicket
);

window.resetTradingLimitOrderTicket = (
  resetTradingLimitOrderTicket
);


if (document.readyState === 'loading') {
  document.addEventListener(
    'DOMContentLoaded',
    () => {
      bindTradingLimitOrderEvents();
      renderTradingLimitOrderTicket();
    },
    {
      once: true,
    },
  );

} else {
  bindTradingLimitOrderEvents();
  renderTradingLimitOrderTicket();
}
