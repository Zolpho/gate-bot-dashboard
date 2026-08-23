'use strict';

tradingState.limitOrderSide = 'buy';
tradingState.limitOrderPercent = null;
tradingState.limitOrderPreview = null;
tradingState.loadingLimitOrderPreview = false;
tradingState.limitOrderExecutionCapabilities = null;
tradingState.loadingLimitOrderExecutionCapabilities = false;
tradingState.limitOrderExecutionAttempt = null;
tradingState.limitOrderCancellationAttempt = null;
tradingState.limitOrderAmendmentAttempt = null;
tradingState.loadingLimitOrderCancellation = false;
tradingState.loadingLimitOrderCancelStatus = false;
tradingState.loadingLimitOrderCancelReconcile = false;
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
  tradingState.limitOrderExecutionAttempt = null;
  tradingState.limitOrderCancellationAttempt = null;
  tradingState.limitOrderAmendmentAttempt = null;
  tradingState.loadingLimitOrderCancellation = false;
  tradingState.loadingLimitOrderCancelStatus = false;
  tradingState.loadingLimitOrderCancelReconcile = false;
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

  const cancelConfirmation = $(
    '#tradingLimitCancelConfirmation'
  );

  if (cancelConfirmation) {
    cancelConfirmation.value = '';
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

function resetTradingLimitOrderSession() {
  /*
   * Clear browser-memory/private UI only.
   *
   * Never remove or overwrite the durable recovery checkpoint.
   */
  tradingState.limitOrderSide = 'buy';
  tradingState.limitOrderPercent = null;
  tradingState.limitOrderPreview = null;

  tradingState.loadingLimitOrderPreview = false;

  tradingState.limitOrderExecutionCapabilities = null;
  tradingState.loadingLimitOrderExecutionCapabilities = false;

  tradingState.limitOrderExecutionAttempt = null;
  tradingState.limitOrderCancellationAttempt = null;
  tradingState.limitOrderAmendmentAttempt = null;

  tradingState.loadingLimitOrderCancellation = false;
  tradingState.loadingLimitOrderCancelStatus = false;
  tradingState.loadingLimitOrderCancelReconcile = false;

  tradingState.loadingLimitOrderExecution = false;
  tradingState.loadingLimitOrderStatus = false;
  tradingState.loadingLimitOrderReconcile = false;

  const form = $('#tradingLimitOrderForm');

  if (form) {
    form.reset();
  }

  for (const selector of [
    '#tradingLimitPrice',
    '#tradingLimitAmount',
    '#tradingLimitConfirmation',
    '#tradingLimitCancelConfirmation',
  ]) {
    const element = $(selector);

    if (element) {
      element.value = '';
    }
  }

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

  const executionResult = $(
    '#tradingLimitExecutionResult'
  );

  if (executionResult) {
    executionResult.innerHTML = '';
    executionResult.classList.add(
      'hidden'
    );
  }

  const cancellationResult = $(
    '#tradingLimitCancellationResult'
  );

  if (cancellationResult) {
    cancellationResult.innerHTML = '';
    cancellationResult.classList.add(
      'hidden'
    );
  }

  const hint = $('#tradingLimitHint');

  if (hint) {
    hint.textContent = (
      'Click any bid or ask price to copy it here.'
    );
  }

  renderTradingLimitOrderTicket();
  renderTradingLimitExecution();
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
  const executionAttempt = (
    tradingState.limitOrderExecutionAttempt
  );

  const cancellationAttempt = (
    tradingState.limitOrderCancellationAttempt
  );

  const amendmentAttempt = (
    tradingState.limitOrderAmendmentAttempt
  );

  return Boolean(
    (
      executionAttempt
      && !executionAttempt.definitive
    )
    || (
      cancellationAttempt
      && !cancellationAttempt.definitive
    )
    || (
      amendmentAttempt
      && !amendmentAttempt.definitive
    )
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



const TRADING_LIMIT_RECOVERY_STORAGE_KEY = (
  'gate-dashboard.trading-recovery.v1'
);

const TRADING_LIMIT_RECOVERY_VERSION = 1;


function tradingLimitRecoveryScope() {
  return {
    username: String(
      state.adminUser?.username
      || ''
    ).trim().toLowerCase(),

    accountId: String(
      tradingState.accountId
      || ''
    ).trim().toLowerCase(),

    pair: String(
      tradingState.pair
      || ''
    ).trim().toUpperCase(),
  };
}


function tradingLimitRecoveryStorage() {
  const storage = (
    globalThis.sessionStorage
  );

  if (
    !storage
    || typeof storage.getItem
      !== 'function'
    || typeof storage.setItem
      !== 'function'
    || typeof storage.removeItem
      !== 'function'
  ) {
    throw new Error(
      'Trading recovery session storage '
      + 'is unavailable.'
    );
  }

  return storage;
}


function tradingLimitRecoveryCheckpointRead() {
  let raw;

  try {
    raw = (
      tradingLimitRecoveryStorage()
        .getItem(
          TRADING_LIMIT_RECOVERY_STORAGE_KEY
        )
    );

  } catch (error) {
    throw new Error(
      (
        'Unable to read the Trading '
        + 'recovery checkpoint. '
      )
      + (
        error?.message || ''
      )
    );
  }

  if (!raw) {
    return null;
  }

  let value;

  try {
    value = JSON.parse(
      raw
    );

  } catch {
    /*
     * Fail closed. A corrupt checkpoint may
     * represent an operation whose outcome is
     * still unknown. Never silently discard it.
     */
    throw new Error(
      'The Trading recovery checkpoint '
      + 'is corrupt. Do not submit another '
      + 'Trading write.'
    );
  }

  if (
    !value
    || typeof value !== 'object'
    || Array.isArray(value)
    || value.version
      !== TRADING_LIMIT_RECOVERY_VERSION
    || ![
      'execution',
      'cancellation',
      'amendment',
    ].includes(
      String(
        value.kind || ''
      )
    )
  ) {
    throw new Error(
      'The Trading recovery checkpoint '
      + 'has an unsupported format. '
      + 'Do not submit another Trading write.'
    );
  }

  return value;
}


function tradingLimitRecoveryCheckpointForUser() {
  const checkpoint = (
    tradingLimitRecoveryCheckpointRead()
  );

  if (!checkpoint) {
    return null;
  }

  const username = String(
    state.adminUser?.username
    || ''
  ).trim().toLowerCase();

  if (
    !username
    || String(
      checkpoint.username
      || ''
    ).trim().toLowerCase()
      !== username
  ) {
    /*
     * Never expose another dashboard user's
     * checkpoint into the active login.
     *
     * Do not delete it here: that user may log
     * back in within this same browser tab and
     * still need recovery.
     */
    return null;
  }

  return checkpoint;
}


function tradingLimitRecoveryDecimalIdentity(
  value,
) {
  const raw = String(
    value ?? ''
  ).trim();

  if (
    !/^\+?(?:\d+(?:\.\d*)?|\.\d+)$/
      .test(raw)
  ) {
    return '';
  }

  const unsigned = raw.replace(
    /^\+/,
    ''
  );

  const parts = unsigned.split('.');

  let whole = String(
    parts[0] || '0'
  );

  let fraction = String(
    parts[1] || ''
  );

  whole = (
    whole.replace(
      /^0+(?=\d)/,
      ''
    )
    || '0'
  );

  fraction = fraction.replace(
    /0+$/,
    ''
  );

  const normalized = (
    fraction
      ? `${whole}.${fraction}`
      : whole
  );

  if (
    normalized === '0'
  ) {
    return '';
  }

  return normalized;
}

function tradingLimitRecoveryCheckpointWrite({
  kind,
  requestId,
  cancelRequestId = '',
  amendRequestId = '',
  gateOrderId = '',
  requestedPrice = '',
} = {}) {
  const scope = (
    tradingLimitRecoveryScope()
  );

  const normalizedKind = String(
    kind || ''
  ).trim().toLowerCase();

  const normalizedRequestId = String(
    requestId || ''
  ).trim();

  const normalizedCancelRequestId = String(
    cancelRequestId || ''
  ).trim();

  const normalizedAmendRequestId = String(
    amendRequestId || ''
  ).trim();

  const normalizedGateOrderId = String(
    gateOrderId || ''
  ).trim();

  const normalizedRequestedPrice = (
    tradingLimitRecoveryDecimalIdentity(
      requestedPrice
    )
  );

  if (
    !scope.username
    || !scope.accountId
    || !scope.pair
  ) {
    throw new Error(
      'Trading recovery scope is incomplete. '
      + 'No Trading write was sent.'
    );
  }

  if (
    ![
      'execution',
      'cancellation',
      'amendment',
    ].includes(
      normalizedKind
    )
    || !normalizedRequestId
  ) {
    throw new Error(
      'Trading recovery identity is invalid. '
      + 'No Trading write was sent.'
    );
  }

  if (
    normalizedKind === 'cancellation'
    && !normalizedCancelRequestId
  ) {
    throw new Error(
      'Cancellation recovery identity '
      + 'is incomplete. '
      + 'No cancellation write was sent.'
    );
  }

  if (
    normalizedKind === 'amendment'
    && (
      !normalizedAmendRequestId
      || !normalizedGateOrderId
      || !/^[0-9]+$/.test(
        normalizedGateOrderId
      )
      || !normalizedRequestedPrice
    )
  ) {
    throw new Error(
      'Amendment recovery identity '
      + 'is incomplete. '
      + 'No amendment write was sent.'
    );
  }

  const checkpoint = {
    version:
      TRADING_LIMIT_RECOVERY_VERSION,

    kind:
      normalizedKind,

    username:
      scope.username,

    account_id:
      scope.accountId,

    pair:
      scope.pair,

    /*
     * For amendment recovery this is the
     * SOURCE audited order request ID.
     */
    request_id:
      normalizedRequestId,

    cancel_request_id: (
      normalizedKind === 'cancellation'
        ? normalizedCancelRequestId
        : ''
    ),

    amend_request_id: (
      normalizedKind === 'amendment'
        ? normalizedAmendRequestId
        : ''
    ),

    gate_order_id: (
      [
        'cancellation',
        'amendment',
      ].includes(
        normalizedKind
      )
        ? normalizedGateOrderId
        : ''
    ),

    requested_price: (
      normalizedKind === 'amendment'
        ? normalizedRequestedPrice
        : ''
    ),

    created_at: (
      new Date().toISOString()
    ),
  };

  /*
   * There may be only one unresolved Trading
   * write checkpoint in this browser tab.
   *
   * Never overwrite another operation's
   * recovery identity. Doing so could make an
   * uncertain Gate write impossible to recover.
   */
  const existing = (
    tradingLimitRecoveryCheckpointRead()
  );

  if (existing) {
    const sameCheckpoint = Boolean(
      String(existing.kind || '')
        === checkpoint.kind
      && String(existing.username || '')
        === checkpoint.username
      && String(existing.account_id || '')
        === checkpoint.account_id
      && String(existing.pair || '')
        === checkpoint.pair
      && String(existing.request_id || '')
        === checkpoint.request_id
      && String(
        existing.cancel_request_id || ''
      ) === checkpoint.cancel_request_id
      && String(
        existing.amend_request_id || ''
      ) === checkpoint.amend_request_id
      && String(
        existing.gate_order_id || ''
      ) === checkpoint.gate_order_id
      && String(
        existing.requested_price || ''
      ) === checkpoint.requested_price
    );

    if (!sameCheckpoint) {
      throw new Error(
        'Another unresolved Trading recovery '
        + 'checkpoint exists in this browser '
        + 'tab. Resolve it before sending '
        + 'another Trading write.'
      );
    }

    /*
     * Re-writing the exact same checkpoint is
     * harmless and does not alter its original
     * creation timestamp.
     */
    return existing;
  }

  const serialized = JSON.stringify(
    checkpoint
  );

  let storage;

  try {
    storage = (
      tradingLimitRecoveryStorage()
    );

    storage.setItem(
      TRADING_LIMIT_RECOVERY_STORAGE_KEY,
      serialized,
    );

    /*
     * Verify the checkpoint really survived
     * the storage write before allowing a later
     * Gate write to cross its POST boundary.
     */
    const persisted = storage.getItem(
      TRADING_LIMIT_RECOVERY_STORAGE_KEY
    );

    if (persisted !== serialized) {
      throw new Error(
        'checkpoint verification failed'
      );
    }

  } catch (error) {
    throw new Error(
      (
        'Unable to persist the Trading '
        + 'recovery checkpoint. '
        + 'No Trading write was sent. '
      )
      + (
        error?.message || ''
      )
    );
  }

  return checkpoint;
}

function tradingLimitRecoveryCheckpointClear({
  kind = '',
  requestId = '',
  cancelRequestId = '',
  amendRequestId = '',
} = {}) {
  const current = (
    tradingLimitRecoveryCheckpointRead()
  );

  if (!current) {
    return true;
  }

  const expectedKind = String(
    kind || ''
  ).trim().toLowerCase();

  const expectedRequestId = String(
    requestId || ''
  ).trim();

  const expectedCancelRequestId = String(
    cancelRequestId || ''
  ).trim();

  const expectedAmendRequestId = String(
    amendRequestId || ''
  ).trim();

  /*
   * Never clear a different operation's
   * checkpoint accidentally.
   */
  if (
    expectedKind
    && String(
      current.kind || ''
    ) !== expectedKind
  ) {
    return false;
  }

  if (
    expectedRequestId
    && String(
      current.request_id || ''
    ) !== expectedRequestId
  ) {
    return false;
  }

  if (
    expectedCancelRequestId
    && String(
      current.cancel_request_id || ''
    ) !== expectedCancelRequestId
  ) {
    return false;
  }

  /*
   * Amendment recovery has two request IDs:
   * source order request + amendment request.
   * Require both identities before clearing it.
   */
  if (
    String(
      current.kind || ''
    ) === 'amendment'
    && (
      !expectedAmendRequestId
      || String(
        current.amend_request_id || ''
      ) !== expectedAmendRequestId
    )
  ) {
    return false;
  }

  try {
    const storage = (
      tradingLimitRecoveryStorage()
    );

    storage.removeItem(
      TRADING_LIMIT_RECOVERY_STORAGE_KEY
    );

    if (
      storage.getItem(
        TRADING_LIMIT_RECOVERY_STORAGE_KEY
      ) !== null
    ) {
      throw new Error(
        'checkpoint removal verification failed'
      );
    }

  } catch (error) {
    throw new Error(
      (
        'Unable to clear the Trading '
        + 'recovery checkpoint. '
      )
      + (
        error?.message || ''
      )
    );
  }

  return true;
}

function tradingLimitRecoveryClearKnownDefinitive({
  kind,
  requestId,
  cancelRequestId = '',
  amendRequestId = '',
  quiet = false,
} = {}) {
  try {
    const cleared = (
      tradingLimitRecoveryCheckpointClear({
        kind,
        requestId,
        cancelRequestId,
        amendRequestId,
      })
    );

    if (!cleared) {
      throw new Error(
        'The stored Trading recovery identity '
        + 'belongs to a different operation.'
      );
    }

    return {
      cleared: true,
      error: null,
    };

  } catch (error) {
    /*
     * The exchange/backend outcome may already
     * be definitive, but failure to remove the
     * browser checkpoint must remain fail-closed.
     *
     * A later Trading write will therefore still
     * be blocked by the checkpoint writer.
     */
    if (!quiet) {
      showToast(
        (
          'Trading outcome is definitive, but '
          + 'the recovery checkpoint could not '
          + 'be cleared. New Trading writes '
          + 'remain blocked. '
        )
        + (
          error?.message || ''
        ),
        true,
      );
    }

    return {
      cleared: false,
      error,
    };
  }
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


function tradingLimitAmendRequestId() {
  const timestamp = (
    Date.now()
      .toString(36)
  );

  let random = '';

  if (
    globalThis.crypto
    && typeof globalThis.crypto.randomUUID
    === 'function'
  ) {
    random = (
      globalThis.crypto
        .randomUUID()
        .replace(
          /[^A-Za-z0-9]/g,
          ''
        )
        .slice(0, 18)
    );

  } else {
    random = (
      Math.random()
        .toString(36)
        .slice(2, 20)
    );
  }

  return (
    `amend-ui-${timestamp}-${random}`
      .replace(
        /[^A-Za-z0-9._-]/g,
        '-'
      )
      .slice(0, 128)
  );
}


function tradingLimitCancelRequestId() {
  const timestamp = (
    Date.now()
      .toString(36)
  );

  let random = '';

  if (
    globalThis.crypto
    && typeof globalThis.crypto.randomUUID
    === 'function'
  ) {
    random = (
      globalThis.crypto
        .randomUUID()
        .replace(
          /[^A-Za-z0-9]/g,
          ''
        )
        .slice(0, 18)
    );

  } else {
    random = (
      Math.random()
        .toString(36)
        .slice(2, 20)
    );
  }

  return (
    `cancel-ui-${timestamp}-${random}`
      .replace(
        /[^A-Za-z0-9._-]/g,
        '-'
      )
      .slice(0, 128)
  );
}


function tradingLimitCancellationSuccessful(
  status
) {
  return new Set([
    'cancelled',
    'confirmed_cancelled',
    'already_cancelled',
  ]).has(
    String(
      status || ''
    ).toLowerCase()
  );
}


function tradingLimitCancellationDefinitive(
  status,
  result = {},
) {
  if (
    typeof result?.definitive
    === 'boolean'
  ) {
    return result.definitive;
  }

  const normalized = String(
    status || ''
  ).toLowerCase();

  return new Set([
    'cancelled',
    'confirmed_cancelled',
    'already_cancelled',
    'confirmed_finished',
    'already_finished',
    'rejected',
    'local_rejected',
    'aborted',
    'precheck_error',
    'precheck_conflict',
  ]).has(
    normalized
  );
}


function tradingLimitCancellationMessage(
  status,
  result = {},
) {
  const normalized = String(
    status || ''
  ).toLowerCase();

  if (
    normalized === 'cancelled'
    || normalized === 'confirmed_cancelled'
  ) {
    return (
      'Gate confirms that the Spot order '
      + 'is cancelled.'
    );
  }

  if (
    normalized === 'already_cancelled'
  ) {
    return (
      'The Gate Spot order was already '
      + 'cancelled.'
    );
  }

  if (
    normalized === 'confirmed_finished'
    || normalized === 'already_finished'
  ) {
    return (
      'The Gate order finished before '
      + 'cancellation could be confirmed.'
    );
  }

  if (
    normalized === 'precheck_conflict'
  ) {
    return (
      'Gate order identity does not match '
      + 'the audited Trading request. '
      + 'No cancellation write was sent.'
    );
  }

  if (
    normalized === 'precheck_error'
  ) {
    return (
      'Cancellation precheck failed before '
      + 'a Gate cancellation write.'
    );
  }

  if (
    normalized === 'rejected'
    || normalized === 'local_rejected'
    || normalized === 'aborted'
  ) {
    return (
      'Cancellation ended without a '
      + 'confirmed cancelled Gate order.'
    );
  }

  if (
    normalized === 'uncertain'
    || normalized === 'attention'
    || normalized === 'client_uncertain'
    || normalized === 'idempotent_replay'
  ) {
    return (
      'Cancellation outcome is not definitive. '
      + 'Do not send another cancellation. '
      + 'Check status or reconcile.'
    );
  }

  return (
    normalized
      ? (
          `Cancellation status: `
          + `${normalized}.`
        )
      : (
          'Cancellation result '
          + 'is unavailable.'
        )
  );
}


function renderTradingLimitCancellationResult() {
  const element = $(
    '#tradingLimitCancellationResult'
  );

  if (!element) {
    return;
  }

  const attempt = (
    tradingState
      .limitOrderCancellationAttempt
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

  const successful = (
    tradingLimitCancellationSuccessful(
      status
    )
  );

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
          data-trading-cancel-action="status"
          ${
            tradingState
              .loadingLimitOrderCancelStatus
              ? 'disabled'
              : ''
          }
        >
          ${
            tradingState
              .loadingLimitOrderCancelStatus
              ? 'Checking…'
              : 'Check cancel status'
          }
        </button>

        <button
          type="button"
          class="button"
          data-trading-cancel-action="reconcile"
          ${
            tradingState
              .loadingLimitOrderCancelReconcile
              ? 'disabled'
              : ''
          }
        >
          ${
            tradingState
              .loadingLimitOrderCancelReconcile
              ? 'Reconciling…'
              : 'Reconcile cancellation'
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
        Gate cancel write:
        ${escapeHtml(gateWrite)}
      </span>
    </div>

    <p>
      ${escapeHtml(
        attempt.message
        || tradingLimitCancellationMessage(
          status,
          attempt.result || {},
        )
      )}
    </p>

    <small>
      Cancel request ID:
      <code>${escapeHtml(
        attempt.cancelRequestId || '—'
      )}</code>
    </small>

    ${actions}
  `;

  element.classList.remove(
    'hidden'
  );
}


function renderTradingLimitCancellationReadiness() {
  const element = $(
    '#tradingLimitCancellation'
  );

  if (!element) {
    return;
  }

  const executionAttempt = (
    tradingState
      .limitOrderExecutionAttempt
  );

  const cancellationAttempt = (
    tradingState
      .limitOrderCancellationAttempt
  );

  const capabilities = (
    tradingState
      .limitOrderExecutionCapabilities
  );

  const executionStatus = String(
    executionAttempt?.status || ''
  ).toLowerCase();

  const eligibleStatus = (
    executionStatus === 'submitted'
    || executionStatus === 'confirmed_open'
  );

  const gateOrderId = (
    tradingLimitGateOrderId()
  );

  if (
    !executionAttempt
    || !eligibleStatus
    || !gateOrderId
  ) {
    element.classList.add(
      'hidden'
    );

    renderTradingLimitCancellationResult();

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

  const busy = Boolean(
    tradingState
      .loadingLimitOrderCancellation
    || tradingState
      .loadingLimitOrderCancelStatus
    || tradingState
      .loadingLimitOrderCancelReconcile
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
    'Live Spot order cancellation '
    + 'is disabled by the backend.'
  );

  let statusClass = 'disabled';

  if (
    tradingState
      .loadingLimitOrderExecutionCapabilities
  ) {
    label = 'CHECKING';

    description = (
      'Checking backend '
      + 'cancellation state…'
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
      'The guarded Spot cancellation '
      + 'backend is unavailable.'
    );

    statusClass = 'warning';

  } else if (!accountConfigured) {
    label = 'NO TRADING KEY';

    description = (
      'This account has no enabled '
      + 'isolated Spot Trading credential.'
    );

    statusClass = 'warning';

  } else if (cancellationAttempt) {
    if (!cancellationAttempt.definitive) {
      label = 'RECOVERY REQUIRED';

      statusClass = 'warning';

    } else if (
      tradingLimitCancellationSuccessful(
        cancellationAttempt.status
      )
    ) {
      label = 'CANCELLED';

      statusClass = 'ready';

    } else if (
      new Set([
        'already_finished',
        'confirmed_finished',
      ]).has(
        String(
          cancellationAttempt.status || ''
        ).toLowerCase()
      )
    ) {
      label = 'ORDER FINISHED';

      statusClass = 'warning';

    } else {
      label = 'CANCELLATION FINISHED';

      statusClass = 'warning';
    }

    description = (
      cancellationAttempt.message
      || tradingLimitCancellationMessage(
        cancellationAttempt.status,
        cancellationAttempt.result || {},
      )
    );

  } else if (cancelArmEnabled) {
    label = 'CANCEL ENABLED';

    description = (
      'Exact confirmation is required. '
      + 'Cancel order sends one guarded '
      + 'Gate Spot cancellation request.'
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

  const inputEnabled = Boolean(
    implemented
    && routeAvailable
    && accountConfigured
    && cancelArmEnabled
    && required
    && !cancellationAttempt
    && !busy
  );

  if (confirmation) {
    confirmation.disabled = (
      !inputEnabled
    );

    if (
      !cancelArmEnabled
      || cancellationAttempt
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
      !inputEnabled
      || !exactConfirmation
    );

    button.textContent = (
      tradingState
        .loadingLimitOrderCancellation
        ? 'Cancelling…'
        : 'Cancel order'
    );

    button.title = (
      !cancelArmEnabled
        ? (
            'Live cancellation is '
            + 'disabled by the backend.'
          )
        : cancellationAttempt
          ? (
              'A cancellation request '
              + 'already exists.'
            )
          : !exactConfirmation
            ? (
                'Enter the exact cancellation '
                + 'confirmation first.'
              )
            : (
                'Send exactly one cancellation '
                + 'request for this Gate order.'
              )
    );
  }

  renderTradingLimitCancellationResult();
}


async function cancelTradingLimitOrder() {
  if (
    tradingState.loadingLimitOrderCancellation
    || tradingState.limitOrderCancellationAttempt
  ) {
    return;
  }

  const executionAttempt = (
    tradingState.limitOrderExecutionAttempt
  );

  const capabilities = (
    tradingState
      .limitOrderExecutionCapabilities
  );

  const gateOrderId = (
    tradingLimitGateOrderId()
  );

  const required = String(
    capabilities
      ?.cancel_required_confirmation
    || ''
  );

  const confirmation = String(
    $('#tradingLimitCancelConfirmation')
      ?.value
    || ''
  );

  if (
    !executionAttempt
    || !executionAttempt.requestId
    || !gateOrderId
    || capabilities
      ?.cancellation_implemented
      !== true
    || capabilities
      ?.cancellation_route_available
      !== true
    || capabilities
      ?.cancel_arm_enabled
      !== true
  ) {
    showToast(
      'Live Spot cancellation '
      + 'is not available.',
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
      'Enter the exact cancellation '
      + 'confirmation.',
      true,
    );

    renderTradingLimitExecution();

    return;
  }

  /*
   * Create the persistent cancellation identity
   * only at the actual cancellation boundary.
   */
  const cancelRequestId = (
    tradingLimitCancelRequestId()
  );

  const orderRequestId = (
    executionAttempt.requestId
  );

  /*
   * Persist BOTH cancellation identities
   * before the Gate cancellation POST.
   */
  try {
    tradingLimitRecoveryCheckpointWrite({
      kind: 'cancellation',
      requestId: orderRequestId,
      cancelRequestId,
      gateOrderId,
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

    renderTradingLimitOrderTicket();
    renderTradingLimitExecution();

    return;
  }

  tradingState.limitOrderCancellationAttempt = {
    cancelRequestId,
    orderRequestId,
    gateOrderId,
    status: 'cancelling',
    definitive: false,
    gateWritePerformed: null,
    result: null,
    message: (
      'Submitting exactly one guarded '
      + 'Spot cancellation request…'
    ),
  };

  tradingState.loadingLimitOrderCancellation = true;

  renderTradingLimitOrderTicket();
  renderTradingLimitExecution();

  try {
    const result = await adminApi(
      (
        '/api/trading/limit-orders/requests/'
        + encodeURIComponent(
          orderRequestId
        )
        + '/cancel'
      ),
      {
        method: 'POST',

        body: JSON.stringify({
          cancel_request_id: (
            cancelRequestId
          ),
          confirmation,
        }),
      },
    );

    const cancelStatus = String(
      result?.status || 'unknown'
    ).toLowerCase();

    const definitive = (
      tradingLimitCancellationDefinitive(
        cancelStatus,
        result,
      )
    );

    tradingState.limitOrderCancellationAttempt = {
      cancelRequestId,
      orderRequestId,
      gateOrderId,
      status: cancelStatus,
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
        tradingLimitCancellationMessage(
          cancelStatus,
          result,
        )
      ),
    };

    if (definitive) {
      showToast(
        tradingLimitCancellationMessage(
          cancelStatus,
          result,
        ),
        !tradingLimitCancellationSuccessful(
          cancelStatus
        ),
      );

      tradingLimitRecoveryClearKnownDefinitive({
        kind: 'cancellation',
        requestId: orderRequestId,
        cancelRequestId,
      });

    } else {
      showToast(
        'Cancellation requires recovery. '
        + 'Do not send another cancellation.',
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

    const cancelStatus = String(
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
              'Cancellation was rejected '
              + 'before a Gate write.'
            )
          : (
              'The browser cannot determine '
              + 'whether cancellation reached '
              + 'the server. Do not retry.'
            ),
      )
    );

    tradingState.limitOrderCancellationAttempt = {
      cancelRequestId,
      orderRequestId,
      gateOrderId,
      status: cancelStatus,
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

    if (explicitNoWrite) {
      tradingLimitRecoveryClearKnownDefinitive({
        kind: 'cancellation',
        requestId: orderRequestId,
        cancelRequestId,
      });
    }

  } finally {
    tradingState.loadingLimitOrderCancellation = false;

    renderTradingLimitOrderTicket();
    renderTradingLimitExecution();
  }
}



function tradingLimitRecoveryRequestSnapshot(
  request,
  checkpoint = {},
) {
  return {
    accountId: String(
      request?.account_id
      || checkpoint?.account_id
      || ''
    ).trim().toLowerCase(),

    pair: String(
      request?.pair
      || checkpoint?.pair
      || ''
    ).trim().toUpperCase(),

    side: String(
      request?.side || ''
    ).trim().toLowerCase(),

    price: (
      request?.price
      ?? null
    ),

    amount: (
      request?.amount
      ?? null
    ),

    timeInForce: String(
      request?.time_in_force
      || ''
    ).trim().toLowerCase(),
  };
}


function tradingLimitRecoveryValidateScope(
  checkpoint,
  request = {},
) {
  const current = (
    tradingLimitRecoveryScope()
  );

  const checkpointUsername = String(
    checkpoint?.username || ''
  ).trim().toLowerCase();

  const checkpointAccount = String(
    checkpoint?.account_id || ''
  ).trim().toLowerCase();

  const checkpointPair = String(
    checkpoint?.pair || ''
  ).trim().toUpperCase();

  const checkpointRequestId = String(
    checkpoint?.request_id || ''
  ).trim();

  const requestAccount = String(
    request?.account_id || ''
  ).trim().toLowerCase();

  const requestPair = String(
    request?.pair || ''
  ).trim().toUpperCase();

  const requestId = String(
    request?.request_id || ''
  ).trim();

  if (
    !current.username
    || checkpointUsername
      !== current.username
  ) {
    throw new Error(
      'Trading recovery checkpoint belongs '
      + 'to a different authenticated user.'
    );
  }

  if (
    !current.accountId
    || !current.pair
    || checkpointAccount
      !== current.accountId
    || checkpointPair
      !== current.pair
  ) {
    return {
      matchesCurrentMarket: false,
    };
  }

  if (
    requestAccount
    && requestAccount !== checkpointAccount
  ) {
    throw new Error(
      'Trading recovery account identity '
      + 'does not match the audited request.'
    );
  }

  if (
    requestPair
    && requestPair !== checkpointPair
  ) {
    throw new Error(
      'Trading recovery market identity '
      + 'does not match the audited request.'
    );
  }

  if (
    requestId
    && requestId !== checkpointRequestId
  ) {
    throw new Error(
      'Trading recovery request identity '
      + 'does not match the audited request.'
    );
  }

  return {
    matchesCurrentMarket: true,
  };
}


function tradingLimitRecoveryHydrateExecution(
  checkpoint,
  result = {},
) {
  const request = (
    result?.request || {}
  );

  const orderState = (
    result?.order_state || {}
  );

  const status = String(
    orderState.effective_status
    || request.status
    || 'client_uncertain'
  ).trim().toLowerCase();

  const definitive = (
    tradingLimitExecutionDefinitive(
      status,
      request,
    )
  );

  const attempt = {
    requestId: String(
      checkpoint?.request_id
      || request.request_id
      || ''
    ).trim(),

    snapshot: (
      tradingLimitRecoveryRequestSnapshot(
        request,
        checkpoint,
      )
    ),

    status,
    definitive,

    gateWritePerformed: (
      typeof request.write_performed
      === 'boolean'
        ? request.write_performed
        : null
    ),

    result,

    message: (
      definitive
        ? tradingLimitExecutionMessage(
            status,
            request,
          )
        : (
            tradingLimitExecutionMessage(
              status,
              request,
            )
          )
    ),

    recovered: true,
  };

  tradingState.limitOrderExecutionAttempt = (
    attempt
  );

  return attempt;
}


function tradingLimitRecoveryHydrateCancellation(
  checkpoint,
  result = {},
) {
  const request = (
    result?.request || {}
  );

  const cancellation = (
    result?.cancellation || null
  );

  const expectedCancelRequestId = String(
    checkpoint?.cancel_request_id
    || ''
  ).trim();

  const durableCancelRequestId = String(
    cancellation?.cancel_request_id
    || ''
  ).trim();

  if (
    expectedCancelRequestId
    && durableCancelRequestId
    && expectedCancelRequestId
      !== durableCancelRequestId
  ) {
    throw new Error(
      'Trading cancellation recovery identity '
      + 'does not match the durable audit.'
    );
  }

  const expectedGateOrderId = String(
    checkpoint?.gate_order_id
    || ''
  ).trim();

  const durableGateOrderId = String(
    request?.gate_order_id
    || ''
  ).trim();

  if (
    expectedGateOrderId
    && durableGateOrderId
    && expectedGateOrderId
      !== durableGateOrderId
  ) {
    throw new Error(
      'Trading cancellation Gate order '
      + 'identity does not match the audit.'
    );
  }

  /*
   * Missing cancellation audit is explicitly
   * uncertain. It is NEVER permission to send
   * another cancellation.
   */
  const status = String(
    cancellation?.status
    || 'client_uncertain'
  ).trim().toLowerCase();

  const definitive = Boolean(
    cancellation
    && tradingLimitCancellationDefinitive(
      status,
      cancellation,
    )
  );

  const attempt = {
    cancelRequestId: (
      durableCancelRequestId
      || expectedCancelRequestId
    ),

    orderRequestId: String(
      checkpoint?.request_id
      || request?.request_id
      || ''
    ).trim(),

    gateOrderId: (
      durableGateOrderId
      || expectedGateOrderId
    ),

    status,
    definitive,

    gateWritePerformed: (
      typeof cancellation
        ?.write_performed
      === 'boolean'
        ? cancellation.write_performed
        : null
    ),

    result,

    message: (
      cancellation
        ? tradingLimitCancellationMessage(
            status,
            cancellation,
          )
        : (
            'No cancellation audit is visible '
            + 'yet. Do not send another '
            + 'cancellation. Check status again.'
          )
    ),

    recovered: true,
  };

  tradingState.limitOrderCancellationAttempt = (
    attempt
  );

  return attempt;
}


function tradingLimitAmendmentDefinitive(
  status,
  amendment = {},
) {
  const normalizedStatus = String(
    status || ''
  ).trim().toLowerCase();

  /*
   * Durable amendment audit completion is the
   * authority here.
   *
   * "uncertain", "attention" and "amending"
   * remain unresolved because their audit row
   * intentionally has no completed_at.
   */
  return Boolean(
    normalizedStatus
    && String(
      amendment?.completed_at || ''
    ).trim()
  );
}


function tradingLimitRecoveryHydrateAmendment(
  checkpoint,
  result = {},
) {
  const request = (
    result?.request || {}
  );

  const expectedAmendRequestId = String(
    checkpoint?.amend_request_id || ''
  ).trim();

  const expectedOrderRequestId = String(
    checkpoint?.request_id || ''
  ).trim();

  const expectedGateOrderId = String(
    checkpoint?.gate_order_id || ''
  ).trim();

  const expectedRequestedPrice = (
    tradingLimitRecoveryDecimalIdentity(
      checkpoint?.requested_price
    )
  );

  if (
    !expectedAmendRequestId
    || !expectedOrderRequestId
    || !expectedGateOrderId
    || !expectedRequestedPrice
  ) {
    throw new Error(
      'Trading amendment recovery checkpoint '
      + 'identity is incomplete.'
    );
  }

  const amendments = (
    Array.isArray(
      result?.amendments
    )
      ? result.amendments
      : []
  );

  const matches = amendments.filter(
    amendment => (
      String(
        amendment?.amend_request_id
        || ''
      ).trim()
      === expectedAmendRequestId
    )
  );

  if (matches.length > 1) {
    throw new Error(
      'Trading amendment recovery found '
      + 'duplicate durable amendment identities.'
    );
  }

  let amendment = (
    matches.length === 1
      ? matches[0]
      : null
  );

  /*
   * Request-detail also exposes the active row
   * separately. Accept it only when its exact
   * amendment identity matches the checkpoint.
   */
  if (!amendment) {
    const active = (
      result?.active_amendment || null
    );

    if (
      active
      && String(
        active.amend_request_id || ''
      ).trim()
      === expectedAmendRequestId
    ) {
      amendment = active;
    }
  }

  const durableRequestId = String(
    request?.request_id || ''
  ).trim();

  if (
    durableRequestId
    && durableRequestId
      !== expectedOrderRequestId
  ) {
    throw new Error(
      'Trading amendment recovery source '
      + 'request identity does not match '
      + 'the durable audit.'
    );
  }

  /*
   * Even when the exact amendment audit has
   * not appeared yet, request-detail already
   * exposes the durable source Gate order ID.
   * A mismatch is an identity conflict, not
   * ordinary write uncertainty.
   */
  const durableSourceGateOrderId = String(
    request?.gate_order_id || ''
  ).trim();

  if (
    durableSourceGateOrderId
    && durableSourceGateOrderId
      !== expectedGateOrderId
  ) {
    throw new Error(
      'Trading amendment recovery Gate order '
      + 'identity does not match the source '
      + 'order audit.'
    );
  }

  if (amendment) {
    const amendmentOrderRequestId = String(
      amendment.order_request_id || ''
    ).trim();

    if (
      amendmentOrderRequestId
      !== expectedOrderRequestId
    ) {
      throw new Error(
        'Trading amendment recovery source '
        + 'identity does not match the '
        + 'amendment audit.'
      );
    }

    const durableAmendRequestId = String(
      amendment.amend_request_id || ''
    ).trim();

    if (
      durableAmendRequestId
      !== expectedAmendRequestId
    ) {
      throw new Error(
        'Trading amendment recovery request '
        + 'identity does not match the audit.'
      );
    }

    const durableGateOrderId = String(
      amendment.gate_order_id
      || request?.gate_order_id
      || ''
    ).trim();

    if (
      !durableGateOrderId
      || durableGateOrderId
        !== expectedGateOrderId
    ) {
      throw new Error(
        'Trading amendment recovery Gate order '
        + 'identity does not match the audit.'
      );
    }

    const durableRequestedPrice = (
      tradingLimitRecoveryDecimalIdentity(
        amendment.requested_price
      )
    );

    if (
      !durableRequestedPrice
      || durableRequestedPrice
        !== expectedRequestedPrice
    ) {
      throw new Error(
        'Trading amendment recovery requested '
        + 'price does not match the audit.'
      );
    }
  }

  /*
   * Missing matching amendment audit is NEVER
   * permission to repeat the write.
   */
  const status = String(
    amendment?.status
    || 'client_uncertain'
  ).trim().toLowerCase();

  const definitive = Boolean(
    amendment
    && tradingLimitAmendmentDefinitive(
      status,
      amendment,
    )
  );

  const attempt = {
    amendRequestId:
      expectedAmendRequestId,

    orderRequestId:
      expectedOrderRequestId,

    gateOrderId:
      expectedGateOrderId,

    requestedPrice:
      expectedRequestedPrice,

    status,
    definitive,

    gateWritePerformed: (
      typeof amendment?.write_performed
      === 'boolean'
        ? amendment.write_performed
        : null
    ),

    amendment,
    result,

    message: (
      amendment
        ? (
            definitive
              ? (
                  'Recovered definitive amendment '
                  + `status: ${status}.`
                )
              : (
                  'The amendment remains unresolved. '
                  + 'Do not send another Trading '
                  + 'write until its status is '
                  + 'resolved.'
                )
          )
        : (
            'The amendment audit is not visible '
            + 'yet. Do not repeat the amendment '
            + 'or send another Trading write. '
            + 'Check status again.'
          )
    ),

    recovered: true,
  };

  tradingState.limitOrderAmendmentAttempt = (
    attempt
  );

  return attempt;
}

function tradingLimitRecoveryHydrateMissingAudit(
  checkpoint,
  message,
) {
  const kind = String(
    checkpoint?.kind || ''
  ).trim().toLowerCase();

  if (kind === 'execution') {
    const attempt = {
      requestId: String(
        checkpoint?.request_id || ''
      ).trim(),

      snapshot: (
        tradingLimitRecoveryRequestSnapshot(
          {},
          checkpoint,
        )
      ),

      status: 'client_uncertain',
      definitive: false,
      gateWritePerformed: null,
      result: null,

      message: (
        message
        || (
          'The Trading request audit is not '
          + 'visible yet. Do not submit another '
          + 'order. Check status again.'
        )
      ),

      recovered: true,
    };

    tradingState.limitOrderExecutionAttempt = (
      attempt
    );

    return attempt;
  }

  if (kind === 'cancellation') {
    const attempt = {
      cancelRequestId: String(
        checkpoint?.cancel_request_id || ''
      ).trim(),

      orderRequestId: String(
        checkpoint?.request_id || ''
      ).trim(),

      gateOrderId: String(
        checkpoint?.gate_order_id || ''
      ).trim(),

      status: 'client_uncertain',
      definitive: false,
      gateWritePerformed: null,
      result: null,

      message: (
        message
        || (
          'The cancellation audit is not '
          + 'visible yet. Do not send another '
          + 'cancellation. Check status again.'
        )
      ),

      recovered: true,
    };

    tradingState.limitOrderCancellationAttempt = (
      attempt
    );

    return attempt;
  }

  if (kind === 'amendment') {
    const attempt = (
      tradingLimitRecoveryHydrateAmendment(
        checkpoint,
        {},
      )
    );

    if (message) {
      attempt.message = message;
    }

    return attempt;
  }

  throw new Error(
    'Unsupported Trading recovery kind.'
  );
}

function tradingLimitDurableRecoveryEligibility(
  row,
) {
  const request = (
    row?.request || {}
  );

  const cancellation = (
    row?.cancellation || null
  );

  const orderState = (
    row?.order_state || {}
  );

  const scope = (
    tradingLimitRecoveryScope()
  );

  const requestId = String(
    request.request_id || ''
  ).trim();

  const accountId = String(
    request.account_id || ''
  ).trim().toLowerCase();

  const pair = String(
    request.pair || ''
  ).trim().toUpperCase();

  if (
    row?.managed === false
    || !requestId
    || !scope.username
    || !scope.accountId
    || !scope.pair
  ) {
    return {
      recoverable: false,
      label: '—',
      reason: 'identity_unavailable',
    };
  }

  if (
    accountId !== scope.accountId
    || pair !== scope.pair
  ) {
    return {
      recoverable: false,
      label: 'Review',
      reason: 'scope_mismatch',
    };
  }

  /*
   * Cancellation state takes precedence over
   * execution state whenever a durable
   * cancellation audit exists.
   */
  if (cancellation) {
    const cancelRequestId = String(
      cancellation.cancel_request_id
      || ''
    ).trim();

    const cancelStatus = String(
      cancellation.status || ''
    ).trim().toLowerCase();

    if (
      !cancelRequestId
      || !cancelStatus
    ) {
      return {
        recoverable: false,
        label: 'Review',
        reason: 'cancellation_identity_missing',
      };
    }

    if (
      tradingLimitCancellationDefinitive(
        cancelStatus,
        cancellation,
      )
    ) {
      return {
        recoverable: false,
        label: '—',
        reason: 'cancellation_definitive',
      };
    }

    return {
      recoverable: true,
      kind: 'cancellation',
      label: 'Recover',
      reason: 'cancellation_unresolved',
      requestId,
      cancelRequestId,
      gateOrderId: String(
        request.gate_order_id
        || row?.gate_order_id
        || ''
      ).trim(),
      status: cancelStatus,
    };
  }

  const executionStatus = String(
    orderState.effective_status
    || request.status
    || ''
  ).trim().toLowerCase();

  if (!executionStatus) {
    return {
      recoverable: false,
      label: 'Review',
      reason: 'execution_status_missing',
    };
  }

  if (
    tradingLimitExecutionDefinitive(
      executionStatus,
      request,
    )
  ) {
    return {
      recoverable: false,
      label: '—',
      reason: 'execution_definitive',
    };
  }

  return {
    recoverable: true,
    kind: 'execution',
    label: 'Recover',
    reason: 'execution_unresolved',
    requestId,
    cancelRequestId: '',
    gateOrderId: String(
      request.gate_order_id
      || row?.gate_order_id
      || ''
    ).trim(),
    status: executionStatus,
  };
}


function recoverTradingLimitDurableRow(
  row,
) {
  const eligibility = (
    tradingLimitDurableRecoveryEligibility(
      row
    )
  );

  if (!eligibility.recoverable) {
    throw new Error(
      'This durable Trading request does not '
      + 'require recovery.'
    );
  }

  /*
   * Never replace another unresolved in-memory
   * operation with a different durable row.
   */
  if (
    tradingLimitExecutionRecoveryRequired()
  ) {
    const executionId = String(
      tradingState
        .limitOrderExecutionAttempt
        ?.requestId
      || ''
    ).trim();

    const cancellationId = String(
      tradingState
        .limitOrderCancellationAttempt
        ?.orderRequestId
      || ''
    ).trim();

    const activeId = (
      cancellationId
      || executionId
    );

    if (
      activeId
      && activeId !== eligibility.requestId
    ) {
      throw new Error(
        'Resolve the current Trading recovery '
        + 'request before opening another one.'
      );
    }
  }

  const scope = (
    tradingLimitRecoveryScope()
  );

  const checkpoint = {
    version:
      TRADING_LIMIT_RECOVERY_VERSION,

    kind:
      eligibility.kind,

    username:
      scope.username,

    account_id:
      scope.accountId,

    pair:
      scope.pair,

    request_id:
      eligibility.requestId,

    cancel_request_id:
      eligibility.cancelRequestId || '',

    gate_order_id:
      eligibility.gateOrderId || '',

    /*
     * This is a synthetic recovery identity
     * derived from durable backend audit.
     * It is NOT written to sessionStorage.
     */
    created_at: '',
  };

  let attempt;

  if (
    eligibility.kind === 'cancellation'
  ) {
    attempt = (
      tradingLimitRecoveryHydrateCancellation(
        checkpoint,
        row,
      )
    );

  } else {
    attempt = (
      tradingLimitRecoveryHydrateExecution(
        checkpoint,
        row,
      )
    );
  }

  renderTradingLimitOrderTicket();
  renderTradingLimitExecution();

  return {
    recovered: true,
    definitive:
      attempt.definitive === true,
    kind: eligibility.kind,
    requestId: eligibility.requestId,
    status: attempt.status,
  };
}


async function recoverTradingLimitCheckpoint({
  quiet = false,
} = {}) {
  let checkpoint;

  try {
    checkpoint = (
      tradingLimitRecoveryCheckpointForUser()
    );

  } catch (error) {
    if (!quiet) {
      showToast(
        (
          error?.message
          || 'Trading recovery checkpoint '
          + 'could not be read.'
        ),
        true,
      );
    }

    return {
      status: 'checkpoint_error',
      recovered: false,
      definitive: false,
      error,
    };
  }

  if (!checkpoint) {
    return {
      status: 'none',
      recovered: false,
      definitive: true,
    };
  }

  const scope = (
    tradingLimitRecoveryValidateScope(
      checkpoint,
    )
  );

  if (!scope.matchesCurrentMarket) {
    return {
      status: 'different_market',
      recovered: false,
      definitive: false,
      checkpoint,
    };
  }

  const requestId = String(
    checkpoint.request_id || ''
  ).trim();

  if (!requestId) {
    return {
      status: 'checkpoint_error',
      recovered: false,
      definitive: false,
      checkpoint,
    };
  }

  try {
    /*
     * EXACT REQUEST LOOKUP ONLY.
     *
     * This is an authenticated dashboard GET.
     * It performs no Trading/Gate write.
     */
    const result = await adminApi(
      (
        '/api/trading/limit-orders/requests/'
        + encodeURIComponent(
            requestId
          )
      )
    );

    const request = (
      result?.request || {}
    );

    const validated = (
      tradingLimitRecoveryValidateScope(
        checkpoint,
        request,
      )
    );

    if (!validated.matchesCurrentMarket) {
      return {
        status: 'different_market',
        recovered: false,
        definitive: false,
        checkpoint,
      };
    }

    let attempt;

    if (
      String(checkpoint.kind)
      === 'cancellation'
    ) {
      attempt = (
        tradingLimitRecoveryHydrateCancellation(
          checkpoint,
          result,
        )
      );

    } else if (
      String(checkpoint.kind)
      === 'amendment'
    ) {
      attempt = (
        tradingLimitRecoveryHydrateAmendment(
          checkpoint,
          result,
        )
      );

    } else {
      attempt = (
        tradingLimitRecoveryHydrateExecution(
          checkpoint,
          result,
        )
      );
    }

    let checkpointCleared = false;

    if (attempt.definitive) {
      const clearResult = (
        tradingLimitRecoveryClearKnownDefinitive({
          kind: checkpoint.kind,
          requestId:
            checkpoint.request_id,
          cancelRequestId: (
            checkpoint.kind === 'cancellation'
              ? checkpoint.cancel_request_id
              : ''
          ),
          amendRequestId: (
            checkpoint.kind === 'amendment'
              ? checkpoint.amend_request_id
              : ''
          ),
          quiet,
        })
      );

      checkpointCleared = (
        clearResult.cleared === true
      );
    }

    renderTradingLimitOrderTicket();
    renderTradingLimitExecution();

    /*
     * Recovery can change whether persistent
     * Open Orders may expose Cancel/Amend.
     *
     * Rerender immediately after hydrating or
     * clearing the checkpoint rather than
     * waiting for the next polling refresh.
     */
    if (
      typeof window.tradingRenderPersistentOrders
      === 'function'
    ) {
      window.tradingRenderPersistentOrders();
    }

    return {
      status: attempt.status,
      recovered: true,
      definitive: (
        attempt.definitive === true
      ),
      checkpoint_cleared:
        checkpointCleared,
      checkpoint,
      result,
    };

  } catch (error) {
    /*
     * 404 is NOT proof the original mutation
     * did not reach the backend.
     *
     * Network/API errors are treated the same:
     * preserve recovery identity and block retry.
     */
    const statusCode = Number(
      error?.status || 0
    );

    const message = (
      statusCode === 404
        ? (
            'The Trading request audit is not '
            + 'visible yet. Do not repeat the '
            + 'original Trading write.'
          )
        : (
            tradingLimitApiErrorMessage(
              error,
              'Trading recovery status could '
              + 'not be confirmed. Do not repeat '
              + 'the original Trading write.',
            )
          )
    );

    const attempt = (
      tradingLimitRecoveryHydrateMissingAudit(
        checkpoint,
        message,
      )
    );

    renderTradingLimitOrderTicket();
    renderTradingLimitExecution();

    /*
     * Missing/failed recovery is itself a
     * fail-closed action-state change.
     */
    if (
      typeof window.tradingRenderPersistentOrders
      === 'function'
    ) {
      window.tradingRenderPersistentOrders();
    }

    if (!quiet) {
      showToast(
        message,
        true,
      );
    }

    return {
      status: attempt.status,
      recovered: true,
      definitive: false,
      checkpoint,
      error,
    };
  }
}


async function checkTradingLimitCancellationStatus() {
  const attempt = (
    tradingState
      .limitOrderCancellationAttempt
  );

  if (
    !attempt
    || attempt.definitive
    || tradingState
      .loadingLimitOrderCancelStatus
  ) {
    return;
  }

  tradingState.loadingLimitOrderCancelStatus = true;

  renderTradingLimitExecution();

  try {
    const result = await adminApi(
      (
        '/api/trading/limit-orders/requests/'
        + encodeURIComponent(
          attempt.orderRequestId
        )
      )
    );

    const cancellation = (
      result?.cancellation
    );

    /*
     * Missing audit is NOT permission to retry.
     * The original browser request could still
     * be in flight or its outcome unknown.
     */
    if (!cancellation) {
      tradingState.limitOrderCancellationAttempt = {
        ...attempt,
        definitive: false,
        result,
        message: (
          'No cancellation audit is visible yet. '
          + 'Do not retry. Check status again.'
        ),
      };

      return;
    }

    const cancelStatus = String(
      cancellation.status || 'unknown'
    ).toLowerCase();

    const definitive = (
      tradingLimitCancellationDefinitive(
        cancelStatus,
        cancellation,
      )
    );

    tradingState.limitOrderCancellationAttempt = {
      ...attempt,
      status: cancelStatus,
      definitive,
      gateWritePerformed: (
        typeof cancellation.write_performed
        === 'boolean'
          ? cancellation.write_performed
          : attempt.gateWritePerformed
      ),
      result,
      message: (
        definitive
          ? (
              tradingLimitCancellationMessage(
                cancelStatus,
                cancellation,
              )
            )
          : (
              `Cancellation remains `
              + `${cancelStatus}. `
              + 'Do not send another cancellation.'
            )
      ),
    };

    if (definitive) {
      tradingLimitRecoveryClearKnownDefinitive({
        kind: 'cancellation',
        requestId: attempt.orderRequestId,
        cancelRequestId:
          attempt.cancelRequestId,
      });
    }

  } catch (error) {
    tradingState.limitOrderCancellationAttempt = {
      ...attempt,
      definitive: false,
      message: (
        tradingLimitApiErrorMessage(
          error,
          'Cancellation status could not '
          + 'be confirmed. Do not retry.',
        )
      ),
    };

  } finally {
    tradingState.loadingLimitOrderCancelStatus = false;

    renderTradingLimitOrderTicket();
    renderTradingLimitExecution();
  }
}


async function reconcileTradingLimitCancellation() {
  const attempt = (
    tradingState
      .limitOrderCancellationAttempt
  );

  if (
    !attempt
    || attempt.definitive
    || tradingState
      .loadingLimitOrderCancelReconcile
  ) {
    return;
  }

  tradingState.loadingLimitOrderCancelReconcile = true;

  renderTradingLimitExecution();

  try {
    const result = await adminApi(
      (
        '/api/trading/limit-orders/requests/'
        + encodeURIComponent(
          attempt.orderRequestId
        )
        + '/cancel/reconcile'
      ),
      {
        method: 'POST',
      },
    );

    const reconciliation = (
      result?.reconciliation || {}
    );

    const cancelStatus = String(
      reconciliation.status
      || 'uncertain'
    ).toLowerCase();

    const definitive = (
      tradingLimitCancellationDefinitive(
        cancelStatus,
        reconciliation,
      )
    );

    const cancellation = (
      reconciliation
        ?.cancellation
      || {}
    );

    tradingState.limitOrderCancellationAttempt = {
      ...attempt,
      status: cancelStatus,
      definitive,
      gateWritePerformed: (
        typeof cancellation.write_performed
        === 'boolean'
          ? cancellation.write_performed
          : attempt.gateWritePerformed
      ),
      result,
      message: (
        tradingLimitCancellationMessage(
          cancelStatus,
          reconciliation,
        )
      ),
    };

    if (definitive) {
      showToast(
        tradingLimitCancellationMessage(
          cancelStatus,
          reconciliation,
        ),
        !tradingLimitCancellationSuccessful(
          cancelStatus
        ),
      );

      tradingLimitRecoveryClearKnownDefinitive({
        kind: 'cancellation',
        requestId: attempt.orderRequestId,
        cancelRequestId:
          attempt.cancelRequestId,
      });

    } else {
      showToast(
        'Cancellation reconciliation '
        + 'is still inconclusive. '
        + 'Do not retry.',
        true,
      );
    }

  } catch (error) {
    tradingState.limitOrderCancellationAttempt = {
      ...attempt,
      definitive: false,
      message: (
        tradingLimitApiErrorMessage(
          error,
          'Cancellation reconciliation failed '
          + 'or remains inconclusive. '
          + 'Do not retry.',
        )
      ),
    };

    showToast(
      tradingState
        .limitOrderCancellationAttempt
        .message,
      true,
    );

  } finally {
    tradingState.loadingLimitOrderCancelReconcile = false;

    renderTradingLimitOrderTicket();
    renderTradingLimitExecution();
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

  /*
   * Persist recovery identity BEFORE the
   * execution POST boundary.
   *
   * If sessionStorage cannot preserve it,
   * fail closed and do not send the order.
   */
  try {
    tradingLimitRecoveryCheckpointWrite({
      kind: 'execution',
      requestId,
    });

  } catch (error) {
    showToast(
      (
        error?.message
        || 'Unable to preserve Trading '
        + 'recovery identity.'
      )
      + ' No Spot order was sent.',
      true,
    );

    renderTradingLimitOrderTicket();
    renderTradingLimitExecution();

    return;
  }

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

      tradingLimitRecoveryClearKnownDefinitive({
        kind: 'execution',
        requestId,
      });

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

    if (explicitNoWrite) {
      tradingLimitRecoveryClearKnownDefinitive({
        kind: 'execution',
        requestId,
      });
    }

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
      result?.order_state?.effective_status
      || request.status
      || 'unknown'
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

    if (definitive) {
      tradingLimitRecoveryClearKnownDefinitive({
        kind: 'execution',
        requestId: attempt.requestId,
      });
    }

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

      tradingLimitRecoveryClearKnownDefinitive({
        kind: 'execution',
        requestId: attempt.requestId,
      });

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
      || result.amendment_implemented !== true
      || result.amendment_route_available !== true
      || typeof result.amend_arm_enabled !== 'boolean'
      || result.amend_reconciliation_implemented !== true
      || result.amend_reconciliation_route_available !== true
      || result.amend_reconciliation_gate_get_only !== true
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
        amendment_implemented: false,
        amendment_route_available: false,
        amend_arm_enabled: false,
        amend_required_confirmation: '',
        amend_reconciliation_implemented: false,
        amend_reconciliation_route_available: false,
        amend_reconciliation_gate_get_only: false,
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

    if (
      typeof window.tradingRenderPersistentOrders
      === 'function'
    ) {
      window.tradingRenderPersistentOrders();
    }
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

  $('#tradingLimitCancelConfirmation')?.addEventListener(
    'input',
    () => {
      renderTradingLimitExecution();
    },
  );

  $('#cancelTradingLimitOrder')?.addEventListener(
    'click',
    () => {
      void cancelTradingLimitOrder();
    },
  );

  $('#tradingLimitCancellationResult')?.addEventListener(
    'click',
    event => {
      const button = (
        event.target instanceof Element
          ? event.target.closest(
              '[data-trading-cancel-action]'
            )
          : null
      );

      if (!button) {
        return;
      }

      const action = String(
        button.dataset.tradingCancelAction
        || ''
      );

      if (action === 'status') {
        void checkTradingLimitCancellationStatus();

      } else if (action === 'reconcile') {
        void reconcileTradingLimitCancellation();
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


window.tradingLimitDurableRecoveryEligibility = (
  tradingLimitDurableRecoveryEligibility
);

window.recoverTradingLimitDurableRow = (
  recoverTradingLimitDurableRow
);

window.tradingLimitRecoveryClearKnownDefinitive = (
  tradingLimitRecoveryClearKnownDefinitive
);


window.recoverTradingLimitCheckpoint = (
  recoverTradingLimitCheckpoint
);


window.tradingLimitRecoveryCheckpointRead = (
  tradingLimitRecoveryCheckpointRead
);

window.tradingLimitRecoveryCheckpointForUser = (
  tradingLimitRecoveryCheckpointForUser
);

window.tradingLimitRecoveryCheckpointWrite = (
  tradingLimitRecoveryCheckpointWrite
);

window.tradingLimitRecoveryCheckpointClear = (
  tradingLimitRecoveryCheckpointClear
);


window.tradingLimitRecoveryDecimalIdentity = (
  tradingLimitRecoveryDecimalIdentity
);

window.tradingLimitAmendRequestId = (
  tradingLimitAmendRequestId
);

window.tradingLimitCancelRequestId = (
  tradingLimitCancelRequestId
);

window.tradingLimitCancellationMessage = (
  tradingLimitCancellationMessage
);


window.loadTradingExecutionCapabilities = (
  loadTradingExecutionCapabilities
);

window.renderTradingLimitOrderTicket = (
  renderTradingLimitOrderTicket
);

window.resetTradingLimitOrderTicket = (
  resetTradingLimitOrderTicket
);


window.resetTradingLimitOrderSession = (
  resetTradingLimitOrderSession
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
