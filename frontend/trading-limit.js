'use strict';

tradingState.limitOrderSide = 'buy';
tradingState.limitOrderPercent = null;
tradingState.limitOrderPreview = null;
tradingState.loadingLimitOrderPreview = false;
tradingState.limitOrderExecutionCapabilities = null;
tradingState.loadingLimitOrderExecutionCapabilities = false;
tradingState.limitOrderExecutionAttempt = null;
tradingState.loadingLimitOrderExecution = false;
tradingState.loadingLimitOrderStatus = false;
tradingState.loadingLimitOrderReconcile = false;
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
  if (
    tradingLimitExecutionRecoveryRequired()
    || tradingState.loadingLimitOrderExecution
  ) {
    showToast(
      'Resolve the current Trading request '
      + 'before changing this order.',
      true,
    );

    renderTradingLimitExecution();

    return false;
  }

  tradingState.limitOrderPreview = null;
  tradingState.limitOrderExecutionCapabilities = null;
  tradingState.limitOrderExecutionAttempt = null;
  tradingState.loadingLimitOrderStatus = false;
  tradingState.loadingLimitOrderReconcile = false;

  const preview = $(
    '#tradingLimitOrderPreview'
  );

  if (preview) {
    preview.innerHTML = '';
    preview.classList.add(
      'hidden'
    );
  }

  const error = $(
    '#tradingLimitOrderError'
  );

  if (error) {
    error.textContent = '';
    error.classList.add(
      'hidden'
    );
  }

  const confirmation = $(
    '#tradingLimitConfirmation'
  );

  if (confirmation) {
    confirmation.value = '';
  }

  const executionResult = $(
    '#tradingLimitExecutionResult'
  );

  if (executionResult) {
    executionResult.innerHTML = '';
    executionResult.classList.add(
      'hidden'
    );
  }

  renderTradingLimitExecution();

  return true;
}


function resetTradingLimitOrderTicket() {
  if (
    tradingLimitExecutionRecoveryRequired()
    || tradingState.loadingLimitOrderExecution
  ) {
    showToast(
      'Resolve the current Trading request '
      + 'before resetting this ticket.',
      true,
    );

    renderTradingLimitOrderTicket();
    renderTradingLimitExecution();

    return;
  }

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

  const executionLocked = Boolean(
    tradingState.loadingLimitOrderExecution
    || tradingLimitExecutionRecoveryRequired()
  );

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

    button.disabled = executionLocked;
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
    priceInput.disabled = executionLocked;

    priceInput.step = (
      priceDigits <= 0
        ? '1'
        : (
            10 ** (-priceDigits)
          ).toFixed(priceDigits)
    );
  }

  if (amountInput) {
    amountInput.disabled = executionLocked;

    amountInput.step = (
      amountDigits <= 0
        ? '1'
        : (
            10 ** (-amountDigits)
          ).toFixed(amountDigits)
    );
  }

  const tif = $(
    '#tradingLimitTif'
  );

  if (tif) {
    tif.disabled = executionLocked;
  }

  const tradingAccount = $(
    '#tradingAccount'
  );

  const tradingPair = $(
    '#tradingPair'
  );

  if (tradingAccount) {
    tradingAccount.disabled = executionLocked;
  }

  if (tradingPair) {
    tradingPair.disabled = executionLocked;
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
      executionLocked
      || buyNeedsPrice
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
      executionLocked
      || tradingState.loadingLimitOrderPreview
      || !tradingState.accountId
      || !tradingState.pair
      || values.price === null
      || values.price <= 0
      || values.amount === null
      || values.amount <= 0
    );
  }
}


function tradingLimitExecutionRecoveryRequired() {
  const attempt = (
    tradingState.limitOrderExecutionAttempt
  );

  return Boolean(
    attempt
    && !attempt.definitive
  );
}


function tradingLimitExecutionSnapshot() {
  const preview = (
    tradingState.limitOrderPreview
  );

  if (
    String(
      preview?.status || ''
    ).toLowerCase()
    !== 'ready'
  ) {
    return null;
  }

  const order = preview?.order || {};
  const pair = preview?.pair || {};

  const accountId = String(
    preview?.account_id || ''
  ).trim().toLowerCase();

  const pairId = String(
    pair.id
    || tradingState.pair
    || ''
  ).trim().toUpperCase();

  const side = String(
    order.side || ''
  ).trim().toLowerCase();

  const price = String(
    order.price || ''
  ).trim();

  const amount = String(
    order.amount || ''
  ).trim();

  const timeInForce = String(
    order.time_in_force || ''
  ).trim().toLowerCase();

  if (
    !accountId
    || !pairId
    || !['buy', 'sell'].includes(side)
    || !price
    || !amount
    || !['gtc', 'poc'].includes(
      timeInForce
    )
  ) {
    return null;
  }

  return {
    accountId,
    pair: pairId,
    side,
    price,
    amount,
    timeInForce,
  };
}


function tradingLimitRequestId() {
  /*
   * Called only after the user presses Place
   * and every local execution guard passes.
   *
   * Preview never receives or creates a
   * persistent execution request ID.
   */
  const random = (
    globalThis.crypto?.randomUUID
      ? globalThis.crypto.randomUUID()
      : (
          Math.random()
            .toString(36)
            .slice(2)
          + '-'
          + Math.random()
            .toString(36)
            .slice(2)
        )
  );

  return (
    `ui-limit-${Date.now().toString(36)}-${random}`
      .replace(
        /[^A-Za-z0-9._-]/g,
        '-'
      )
      .slice(0, 128)
  );
}


function tradingLimitApiErrorDetail(
  error
) {
  const detail = (
    error?.payload?.detail
  );

  if (
    detail
    && typeof detail === 'object'
    && !Array.isArray(detail)
  ) {
    return detail;
  }

  return {};
}


function tradingLimitApiErrorMessage(
  error,
  fallback,
) {
  const detail = (
    error?.payload?.detail
  );

  if (
    detail
    && typeof detail === 'object'
    && !Array.isArray(detail)
  ) {
    const message = String(
      detail.message || ''
    ).trim();

    if (message) {
      return message;
    }
  }

  if (
    typeof detail === 'string'
    && detail.trim()
  ) {
    return detail.trim();
  }

  const message = String(
    error?.message || ''
  ).trim();

  if (
    message
    && message !== '[object Object]'
  ) {
    return message;
  }

  return fallback;
}


function tradingLimitExecutionDefinitive(
  status,
  result = {},
) {
  const normalized = String(
    status || ''
  ).toLowerCase();

  const definitive = new Set([
    'submitted',
    'rejected',
    'rate_limited',
    'preflight_error',
    'preflight_failed',
    'lock_blocked',
    'aborted',
    'local_rejected',
    'not_submitted',
    'confirmed_open',
    'confirmed_closed',
    'confirmed_cancelled',
  ]);

  if (
    normalized === 'idempotent_replay'
  ) {
    return definitive.has(
      String(
        result?.original_status || ''
      ).toLowerCase()
    );
  }

  return definitive.has(
    normalized
  );
}


function tradingLimitExecutionMessage(
  status,
  result = {},
) {
  const normalized = String(
    status || ''
  ).toLowerCase();

  if (normalized === 'submitted') {
    const orderId = String(
      result?.gate_order_id || ''
    );

    return orderId
      ? (
          `Gate accepted Spot order ${orderId}.`
        )
      : 'Gate accepted the Spot order.';
  }

  if (
    normalized === 'confirmed_open'
  ) {
    return (
      'Reconciliation confirmed that the '
      + 'Gate order exists and is open.'
    );
  }

  if (
    normalized === 'confirmed_closed'
  ) {
    return (
      'Reconciliation confirmed that the '
      + 'Gate order is closed.'
    );
  }

  if (
    normalized === 'confirmed_cancelled'
  ) {
    return (
      'Reconciliation confirmed that the '
      + 'Gate order is cancelled.'
    );
  }

  if (normalized === 'rejected') {
    return (
      'Gate definitively rejected the order. '
      + 'No retry was performed.'
    );
  }

  if (
    normalized === 'preflight_failed'
    || normalized === 'preflight_error'
  ) {
    return (
      'The fresh server-side preflight stopped '
      + 'the order before submission.'
    );
  }

  if (normalized === 'rate_limited') {
    return (
      'The execution request was stopped by '
      + 'the Trading rate limit.'
    );
  }

  if (normalized === 'lock_blocked') {
    return (
      'Another Trading operation currently '
      + 'owns this funding-asset lock.'
    );
  }

  if (
    normalized === 'aborted'
    || normalized === 'local_rejected'
  ) {
    return (
      'Execution stopped before a definitive '
      + 'Gate order submission.'
    );
  }

  if (
    normalized === 'uncertain'
    || normalized === 'attention'
    || normalized === 'lookup_error'
    || normalized === 'not_found'
    || normalized === 'history_window_expired'
    || normalized === 'history_search_incomplete'
    || normalized === 'duplicate_correlation'
    || normalized === 'correlation_conflict'
    || normalized === 'client_uncertain'
  ) {
    return (
      'Submission outcome is not definitive. '
      + 'Do not place another order. '
      + 'Check status or reconcile this request.'
    );
  }

  return (
    normalized
      ? `Execution status: ${normalized}.`
      : 'Execution result is unavailable.'
  );
}


function tradingLimitGateOrderId() {
  const attempt = (
    tradingState.limitOrderExecutionAttempt
  );

  const candidates = [
    attempt?.result?.gate_order_id,
    attempt?.result?.audit?.gate_order_id,
    attempt?.result?.request?.gate_order_id,
    attempt?.result?.reconciliation?.gate_order_id,
    attempt?.result?.reconciliation
      ?.audit?.gate_order_id,
  ];

  for (const candidate of candidates) {
    const value = String(
      candidate || ''
    ).trim();

    /*
     * Stage 3H4 only exposes cancellation
     * readiness when the real Gate numeric
     * order ID is known.
     */
    if (
      value
      && /^[0-9]+$/.test(value)
    ) {
      return value;
    }
  }

  return '';
}


function renderTradingLimitCancellationReadiness() {
  const element = $(
    '#tradingLimitCancellation'
  );

  if (!element) {
    return;
  }

  const attempt = (
    tradingState.limitOrderExecutionAttempt
  );

  const capabilities = (
    tradingState
      .limitOrderExecutionCapabilities
  );

  const executionStatus = String(
    attempt?.status || ''
  ).toLowerCase();

  const eligibleStatus = (
    executionStatus === 'submitted'
    || executionStatus === 'confirmed_open'
  );

  const gateOrderId = (
    tradingLimitGateOrderId()
  );

  /*
   * Do not expose cancellation controls for
   * failed, uncertain, closed or ID-less orders.
   */
  if (
    !attempt
    || !eligibleStatus
    || !gateOrderId
  ) {
    element.classList.add(
      'hidden'
    );

    return;
  }

  element.classList.remove(
    'hidden'
  );

  const status = $(
    '#tradingLimitCancellationStatus'
  );

  const message = $(
    '#tradingLimitCancellationMessage'
  );

  const gateOrder = $(
    '#tradingLimitCancellationGateOrderId'
  );

  const requiredElement = $(
    '#tradingLimitCancelRequiredConfirmation'
  );

  const confirmation = $(
    '#tradingLimitCancelConfirmation'
  );

  const button = $(
    '#cancelTradingLimitOrder'
  );

  const accountId = String(
    tradingState.accountId || ''
  ).trim().toLowerCase();

  const configuredAccounts = (
    capabilities
      ?.configured_account_ids
    || []
  ).map(
    value => String(
      value || ''
    ).trim().toLowerCase()
  );

  const implemented = (
    capabilities
      ?.cancellation_implemented
    === true
  );

  const routeAvailable = (
    capabilities
      ?.cancellation_route_available
    === true
  );

  const cancelArmEnabled = (
    capabilities
      ?.cancel_arm_enabled
    === true
  );

  const required = String(
    capabilities
      ?.cancel_required_confirmation
    || ''
  );

  const accountConfigured = (
    configuredAccounts.includes(
      accountId
    )
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

  let label = 'CANCEL DISABLED';

  let description = (
    'Live Spot order cancellation is disabled '
    + 'by the backend.'
  );

  let statusClass = 'disabled';

  if (
    tradingState
      .loadingLimitOrderExecutionCapabilities
  ) {
    label = 'CHECKING';

    description = (
      'Checking backend cancellation state…'
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
      'The guarded Spot cancellation backend '
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

  } else if (cancelArmEnabled) {
    label = 'BACKEND ARMED';

    /*
     * Hard Stage 3H4 safety boundary:
     * this browser build has NO cancellation
     * request caller.
     */
    description = (
      'The backend reports live cancellation '
      + 'armed, but this frontend build '
      + 'intentionally cannot cancel orders yet.'
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
    message.textContent = description;
  }

  if (gateOrder) {
    gateOrder.textContent = gateOrderId;
  }

  if (requiredElement) {
    requiredElement.textContent = (
      required || '—'
    );
  }

  if (confirmation) {
    /*
     * Stage 3H4 deliberately keeps the
     * confirmation input disabled regardless
     * of backend arm state.
     */
    confirmation.disabled = true;
    confirmation.value = '';
  }

  if (button) {
    /*
     * Hard Stage 3H4 safety boundary:
     * there is no browser cancellation caller.
     */
    button.disabled = true;

    button.title = (
      cancelArmEnabled
        ? (
            'Frontend cancellation is '
            + 'intentionally not activated '
            + 'in this build.'
          )
        : (
            'Live cancellation is disabled '
            + 'by the backend.'
          )
    );
  }
}


function renderTradingLimitExecutionResult() {
  const element = $(
    '#tradingLimitExecutionResult'
  );

  if (!element) {
    return;
  }

  const attempt = (
    tradingState.limitOrderExecutionAttempt
  );

  element.classList.remove(
    'success',
    'error',
    'uncertain',
  );

  if (!attempt) {
    element.innerHTML = '';
    element.classList.add(
      'hidden'
    );

    return;
  }

  const status = String(
    attempt.status || 'pending'
  ).toLowerCase();

  const successful = new Set([
    'submitted',
    'confirmed_open',
    'confirmed_closed',
    'confirmed_cancelled',
  ]).has(status);

  const uncertain = (
    !attempt.definitive
  );

  element.classList.add(
    uncertain
      ? 'uncertain'
      : successful
        ? 'success'
        : 'error'
  );

  const gateWrite = (
    attempt.gateWritePerformed === true
      ? 'ATTEMPTED'
      : attempt.gateWritePerformed === false
        ? 'NOT PERFORMED'
        : 'UNKNOWN'
  );

  const actions = uncertain
    ? `
      <div class="trading-order-execution-result-actions">
        <button
          type="button"
          class="button"
          data-trading-execution-action="status"
          ${
            tradingState.loadingLimitOrderStatus
              ? 'disabled'
              : ''
          }
        >
          ${
            tradingState.loadingLimitOrderStatus
              ? 'Checking…'
              : 'Check status'
          }
        </button>

        <button
          type="button"
          class="button"
          data-trading-execution-action="reconcile"
          ${
            tradingState.loadingLimitOrderReconcile
              ? 'disabled'
              : ''
          }
        >
          ${
            tradingState.loadingLimitOrderReconcile
              ? 'Reconciling…'
              : 'Reconcile'
          }
        </button>
      </div>
    `
    : '';

  element.innerHTML = `
    <div class="trading-order-execution-result-head">
      <strong>
        ${escapeHtml(
          status.toUpperCase()
        )}
      </strong>

      <span>
        Gate write: ${escapeHtml(gateWrite)}
      </span>
    </div>

    <p>
      ${escapeHtml(
        attempt.message
        || tradingLimitExecutionMessage(
          status,
          attempt.result || {},
        )
      )}
    </p>

    <small>
      Request ID:
      <code>${escapeHtml(
        attempt.requestId || '—'
      )}</code>
    </small>

    ${actions}
  `;

  element.classList.remove(
    'hidden'
  );
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

    renderTradingLimitExecutionResult();
    renderTradingLimitCancellationReadiness();

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

  const attempt = (
    tradingState.limitOrderExecutionAttempt
  );

  const busy = Boolean(
    tradingState.loadingLimitOrderExecution
    || tradingState.loadingLimitOrderStatus
    || tradingState.loadingLimitOrderReconcile
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

  } else if (attempt) {
    if (attempt.definitive) {
      label = (
        String(
          attempt.status || ''
        ).toLowerCase()
        === 'submitted'
          ? 'ORDER SUBMITTED'
          : 'EXECUTION FINISHED'
      );

      statusClass = (
        String(
          attempt.status || ''
        ).toLowerCase()
        === 'submitted'
          ? 'ready'
          : 'warning'
      );

    } else {
      label = 'RECOVERY REQUIRED';
      statusClass = 'warning';
    }

    description = (
      attempt.message
      || tradingLimitExecutionMessage(
        attempt.status,
        attempt.result || {},
      )
    );

  } else if (liveArmEnabled) {
    label = 'LIVE ENABLED';

    description = (
      'Exact confirmation is required. '
      + 'Pressing Place limit order may submit '
      + 'a real Gate Spot order.'
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

  const executionInputEnabled = Boolean(
    implemented
    && routeAvailable
    && accountConfigured
    && liveArmEnabled
    && required
    && !attempt
    && !busy
  );

  if (confirmation) {
    confirmation.disabled = (
      !executionInputEnabled
    );

    if (
      !liveArmEnabled
      && !attempt
    ) {
      confirmation.value = '';
    }
  }

  if (button) {
    const exactConfirmation = (
      String(
        confirmation?.value || ''
      )
      === required
    );

    button.disabled = Boolean(
      !executionInputEnabled
      || !exactConfirmation
    );

    button.textContent = (
      tradingState.loadingLimitOrderExecution
        ? 'Placing…'
        : 'Place limit order'
    );

    button.title = (
      !liveArmEnabled
        ? (
            'Live Trading is disabled '
            + 'by the backend.'
          )
        : !exactConfirmation
          ? (
              'Enter the exact required '
              + 'confirmation first.'
            )
          : (
              'Submit this reviewed limit '
              + 'order to Gate.'
            )
    );
  }

  renderTradingLimitExecutionResult();
  renderTradingLimitCancellationReadiness();
}


async function placeTradingLimitOrder() {
  if (
    tradingState.loadingLimitOrderExecution
    || tradingState.limitOrderExecutionAttempt
  ) {
    return;
  }

  const capabilities = (
    tradingState
      .limitOrderExecutionCapabilities
  );

  const required = String(
    capabilities
      ?.required_confirmation
    || ''
  );

  const confirmation = String(
    $('#tradingLimitConfirmation')
      ?.value
    || ''
  );

  const snapshot = (
    tradingLimitExecutionSnapshot()
  );

  /*
   * Client-side guards are convenience only.
   * The backend independently enforces all of
   * these conditions again.
   */
  if (
    !snapshot
    || capabilities
      ?.execution_implemented
      !== true
    || capabilities
      ?.execution_route_available
      !== true
    || capabilities
      ?.live_arm_enabled
      !== true
    || !(
      capabilities
        ?.configured_account_ids
      || []
    ).map(
      value => String(
        value || ''
      ).toLowerCase()
    ).includes(
      snapshot.accountId
    )
  ) {
    showToast(
      'Live Spot execution is not available.',
      true,
    );

    renderTradingLimitExecution();

    return;
  }

  if (
    !required
    || confirmation !== required
  ) {
    showToast(
      'Enter the exact required confirmation.',
      true,
    );

    renderTradingLimitExecution();

    return;
  }

  /*
   * Persistent execution identity is created
   * HERE — never during Preview.
   */
  const requestId = (
    tradingLimitRequestId()
  );

  tradingState.limitOrderExecutionAttempt = {
    requestId,
    snapshot,
    status: 'submitting',
    definitive: false,
    gateWritePerformed: null,
    result: null,
    message: (
      'Submitting exactly one guarded '
      + 'Spot limit-order request…'
    ),
  };

  tradingState.loadingLimitOrderExecution = true;

  renderTradingLimitOrderTicket();
  renderTradingLimitExecution();

  try {
    const result = await adminApi(
      '/api/trading/limit-orders/execute',
      {
        method: 'POST',

        body: JSON.stringify({
          request_id: requestId,
          account_id: snapshot.accountId,
          pair: snapshot.pair,
          side: snapshot.side,
          price: snapshot.price,
          amount: snapshot.amount,
          time_in_force: (
            snapshot.timeInForce
          ),
          confirmation,
        }),
      },
    );

    const executionStatus = String(
      result?.status || 'unknown'
    ).toLowerCase();

    const definitive = (
      tradingLimitExecutionDefinitive(
        executionStatus,
        result,
      )
    );

    tradingState.limitOrderExecutionAttempt = {
      requestId,
      snapshot,
      status: executionStatus,
      definitive,
      gateWritePerformed: (
        typeof result
          ?.gate_write_performed
        === 'boolean'
          ? result.gate_write_performed
          : null
      ),
      result,
      message: (
        tradingLimitExecutionMessage(
          executionStatus,
          result,
        )
      ),
    };

    if (definitive) {
      showToast(
        tradingLimitExecutionMessage(
          executionStatus,
          result,
        ),
        executionStatus !== 'submitted',
      );

    } else {
      showToast(
        'Trading result requires recovery. '
        + 'Do not submit another order.',
        true,
      );
    }

  } catch (error) {
    const detail = (
      tradingLimitApiErrorDetail(
        error
      )
    );

    const explicitNoWrite = (
      detail.gate_write_performed
        === false
      && detail.write_performed
        === false
    );

    const executionStatus = String(
      detail.code
      || (
        error?.status
          ? `http_${error.status}`
          : 'client_uncertain'
      )
    ).toLowerCase();

    const message = (
      tradingLimitApiErrorMessage(
        error,
        explicitNoWrite
          ? (
              'Execution was rejected before '
              + 'a Gate write.'
            )
          : (
              'The browser cannot determine '
              + 'whether submission reached '
              + 'the server. Do not resubmit.'
            ),
      )
    );

    tradingState.limitOrderExecutionAttempt = {
      requestId,
      snapshot,
      status: executionStatus,
      definitive: explicitNoWrite,
      gateWritePerformed: (
        explicitNoWrite
          ? false
          : null
      ),
      result: (
        error?.payload || null
      ),
      message,
    };

    showToast(
      message,
      true,
    );

  } finally {
    tradingState.loadingLimitOrderExecution = false;

    renderTradingLimitOrderTicket();
    renderTradingLimitExecution();
  }
}


async function checkTradingLimitOrderStatus() {
  const attempt = (
    tradingState.limitOrderExecutionAttempt
  );

  if (
    !attempt
    || attempt.definitive
    || tradingState.loadingLimitOrderStatus
  ) {
    return;
  }

  tradingState.loadingLimitOrderStatus = true;

  renderTradingLimitExecution();

  try {
    const result = await adminApi(
      (
        '/api/trading/limit-orders/requests/'
        + encodeURIComponent(
            attempt.requestId
          )
      )
    );

    const request = (
      result?.request || {}
    );

    const executionStatus = String(
      request.status || 'unknown'
    ).toLowerCase();

    const definitive = (
      tradingLimitExecutionDefinitive(
        executionStatus,
        request,
      )
    );

    tradingState.limitOrderExecutionAttempt = {
      ...attempt,
      status: executionStatus,
      definitive,
      gateWritePerformed: (
        typeof request.write_performed
        === 'boolean'
          ? request.write_performed
          : attempt.gateWritePerformed
      ),
      result,
      message: (
        definitive
          ? tradingLimitExecutionMessage(
              executionStatus,
              request,
            )
          : (
              `Request remains ${executionStatus}. `
              + 'Do not submit another order.'
            )
      ),
    };

  } catch (error) {
    tradingState.limitOrderExecutionAttempt = {
      ...attempt,
      definitive: false,
      message: (
        tradingLimitApiErrorMessage(
          error,
          'Status could not be confirmed. '
          + 'Do not submit another order.',
        )
      ),
    };

  } finally {
    tradingState.loadingLimitOrderStatus = false;

    renderTradingLimitOrderTicket();
    renderTradingLimitExecution();
  }
}


async function reconcileTradingLimitOrder() {
  const attempt = (
    tradingState.limitOrderExecutionAttempt
  );

  if (
    !attempt
    || attempt.definitive
    || tradingState.loadingLimitOrderReconcile
  ) {
    return;
  }

  tradingState.loadingLimitOrderReconcile = true;

  renderTradingLimitExecution();

  try {
    const result = await adminApi(
      (
        '/api/trading/limit-orders/requests/'
        + encodeURIComponent(
            attempt.requestId
          )
        + '/reconcile'
      ),
      {
        method: 'POST',
      },
    );

    const reconciliation = (
      result?.reconciliation || {}
    );

    const executionStatus = String(
      reconciliation.status
      || reconciliation.outcome
      || 'uncertain'
    ).toLowerCase();

    const definitive = (
      tradingLimitExecutionDefinitive(
        executionStatus,
        reconciliation,
      )
    );

    tradingState.limitOrderExecutionAttempt = {
      ...attempt,
      status: executionStatus,
      definitive,
      result,
      message: (
        definitive
          ? tradingLimitExecutionMessage(
              executionStatus,
              reconciliation,
            )
          : (
              tradingLimitExecutionMessage(
                executionStatus,
                reconciliation,
              )
            )
      ),
    };

    if (definitive) {
      showToast(
        tradingLimitExecutionMessage(
          executionStatus,
          reconciliation,
        )
      );

    } else {
      showToast(
        'Reconciliation is still inconclusive. '
        + 'Do not submit another order.',
        true,
      );
    }

  } catch (error) {
    tradingState.limitOrderExecutionAttempt = {
      ...attempt,
      definitive: false,
      message: (
        tradingLimitApiErrorMessage(
          error,
          'Reconciliation failed or remains '
          + 'inconclusive. Do not resubmit.',
        )
      ),
    };

    showToast(
      tradingState
        .limitOrderExecutionAttempt
        .message,
      true,
    );

  } finally {
    tradingState.loadingLimitOrderReconcile = false;

    renderTradingLimitOrderTicket();
    renderTradingLimitExecution();
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
      || result.cancellation_implemented !== true
      || result.cancellation_route_available !== true
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
        cancellation_implemented: false,
        cancellation_route_available: false,
        cancel_arm_enabled: false,
        configured_account_ids: [],
        required_confirmation: '',
        cancel_required_confirmation: '',
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
  if (
    tradingLimitExecutionRecoveryRequired()
    || tradingState.loadingLimitOrderExecution
  ) {
    showToast(
      'Resolve the current Trading request '
      + 'before changing the price.',
      true,
    );

    return;
  }

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


  $('#tradingLimitConfirmation')?.addEventListener(
    'input',
    () => {
      renderTradingLimitExecution();
    },
  );

  $('#placeTradingLimitOrder')?.addEventListener(
    'click',
    () => {
      void placeTradingLimitOrder();
    },
  );

  $('#tradingLimitExecutionResult')?.addEventListener(
    'click',
    event => {
      const button = (
        event.target instanceof Element
          ? event.target.closest(
              '[data-trading-execution-action]'
            )
          : null
      );

      if (!button) {
        return;
      }

      const action = String(
        button.dataset.tradingExecutionAction
        || ''
      );

      if (action === 'status') {
        void checkTradingLimitOrderStatus();

      } else if (action === 'reconcile') {
        void reconcileTradingLimitOrder();
      }
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
