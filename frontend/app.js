'use strict';

const configuredApiBaseUrl = String(
  window.GATE_DASHBOARD_CONFIG?.apiBaseUrl || ''
).replace(/\/+$/, '');

const runningOnGitHubPages = window.location.hostname.endsWith('.github.io');
const API_BASE_URL = configuredApiBaseUrl || (
  runningOnGitHubPages ? '' : window.location.origin
);

function apiUrl(path) {
  if (!API_BASE_URL) {
    throw new Error(
      'The dashboard frontend is online, but the backend API URL is not configured yet.'
    );
  }
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${normalizedPath}`;
}

const state = {
  overview: null,
  bots: [],
  filteredBots: [],
  filteredArchivedBots: [],
  botFilters: {},
  history: [],
  alertIncidents: [],
  alertIncidentHistory: [],
  rules: [],
  health: null,
  syncRuns: [],
  currentBot: null,
  currentBotData: null,
  currentBotHistory: [],
  currentRawData: null,
  currentRawKey: 'metrics',
  selectedAccount: '',
  activeTab: 'overview',
  adminAuthorization: '',
  adminUser: null,
  privateBalance: null,
  privateBalanceAccountId: '',
  privateBalanceFetchedAt: 0,
  depositCatalog: [],
  depositFavorites: [],
  depositCurrency: '',
  depositNetworks: [],
  depositChain: '',
  depositDetails: null,
  depositHistory: [],
  botControlCapabilities: null,
  botControlPrepared: null,
  botControlDraft: null,
  botControlRequestId: '',
  botControlActivity: [],
  botControlActivityPagination: {
    limit: 10,
    offset: 0,
    total: 0,
    hasPrevious: false,
    hasNext: false,
  },
  botControlAttention: [],
  botControlAttentionSummary: null,
  botControlRequestDetail: null,
  treasuryTransfers: [],
  treasuryLocks: [],
  treasuryOwnershipBalances: [],
  treasuryOwnershipLedger: [],
  treasuryUserTransferParticipants: [],
  treasuryUserTransfersEnabled: false,
  treasuryUserTransferPreview: null,
  treasuryUserTransferExecutionAttempted: false,
  treasuryWithdrawalDestinations: [],
  treasuryWithdrawalRequests: [],
  treasuryWithdrawalPreflight: null,
  treasuryWithdrawalRequestDetail: null,
  treasuryWithdrawalRequiredConfirmation: '',
  treasuryRequestDetail: null,
  botStopPrepared: null,
  botStopRequestId: '',
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

async function api(path, options = {}) {
  const { headers = {}, ...fetchOptions } = options;
  const response = await fetch(apiUrl(path), {
    credentials: 'omit',
    ...fetchOptions,
    headers: {
      'Content-Type': 'application/json',
      ...headers,
    },
  });
  const text = await response.text();
  let payload;
  try { payload = text ? JSON.parse(text) : {}; } catch { payload = { detail: text }; }
  if (!response.ok) {
    throw new ApiError(
      payload.detail || payload.error || `Request failed (${response.status})`,
      response.status,
      payload,
    );
  }
  return payload;
}

function adminApi(path, options = {}) {
  if (!state.adminAuthorization) {
    openAdminDialog();
    throw new ApiError('Sign in to your account first.', 401, {});
  }
  return api(path, {
    ...options,
    headers: {
      Authorization: state.adminAuthorization,
      ...(options.headers || {}),
    },
  }).catch(error => {
    if (error.status === 401) lockAdmin(false);
    throw error;
  });
}

function canManageAccount(accountId) {
  const user = state.adminUser;
  if (!user) return false;
  return user.role === 'super_admin' || (user.account_ids || []).includes(accountId);
}

function canManageRule(rule) {
  if (!state.adminUser) return false;
  if (!rule.account_id) return state.adminUser.role === 'super_admin';
  return canManageAccount(rule.account_id);
}

function basicAuthorization(username, password) {
  const bytes = new TextEncoder().encode(`${username}:${password}`);
  let binary = '';
  bytes.forEach(byte => { binary += String.fromCharCode(byte); });
  return `Basic ${btoa(binary)}`;
}

function setAdminError(message = '') {
  const errorBox = $('#adminError');
  if (!errorBox) return;
  errorBox.textContent = message;
  errorBox.classList.toggle('hidden', !message);
}


function setChangePasswordError(message = '') {
  const errorBox = $('#changePasswordError');
  if (!errorBox) return;
  errorBox.textContent = message;
  errorBox.classList.toggle('hidden', !message);
}

function openAdminDialog() {
  const dialog = $('#adminDialog');
  setAdminError('');
  if (!dialog.open) dialog.showModal();
  setTimeout(() => $('#adminForm input[name="username"]')?.focus(), 0);
}


function openChangePasswordDialog() {
  if (!state.adminUser) {
    openAdminDialog();
    return;
  }
  if (state.adminUser.auth_source !== 'file') {
    showToast('Legacy .env administrator passwords must be changed on the server.', true);
    return;
  }

  const dialog = $('#changePasswordDialog');
  const form = $('#changePasswordForm');
  form.reset();
  setChangePasswordError('');
  $('#changePasswordIdentity').textContent = `Signed in as ${state.adminUser.username}.`;
  if (!dialog.open) dialog.showModal();
  setTimeout(() => form.querySelector('input[name="current_password"]')?.focus(), 0);
}

function renderAdminState() {
  const button = $('#adminButton');
  const identity = $('#adminIdentity');
  const changePasswordButton = $('#changePasswordButton');
  const walletNavItem = $('#walletNavItem');
  const tradingNavItem = $('#tradingNavItem');
  const signedIn = Boolean(
    state.adminUser
    && state.adminAuthorization
  );

  if (state.adminUser) {
    button.textContent = 'Lock account';
    identity.textContent = `${state.adminUser.username} · ${state.adminUser.role.replace('_', ' ')}`;
    identity.classList.remove('hidden');
    changePasswordButton.classList.toggle('hidden', state.adminUser.auth_source !== 'file');
  } else {
    button.textContent = 'Account login';
    identity.textContent = '';
    identity.classList.add('hidden');
    changePasswordButton.classList.add('hidden');
  }

  walletNavItem?.classList.toggle(
    'hidden',
    !signedIn,
  );

  walletNavItem?.setAttribute(
    'aria-hidden',
    String(!signedIn),
  );

  if (walletNavItem) {
    walletNavItem.tabIndex = signedIn ? 0 : -1;
  }

  tradingNavItem?.classList.toggle(
    'hidden',
    !signedIn,
  );

  tradingNavItem?.setAttribute(
    'aria-hidden',
    String(!signedIn),
  );

  if (tradingNavItem) {
    tradingNavItem.tabIndex = signedIn ? 0 : -1;
  }

  if (signedIn) {
    $('#privateBalancePanel')?.classList.remove('hidden');
  } else {
    clearPrivateBalance();
    clearDepositHistory();

    if (
      state.activeTab === 'wallet'
      || state.activeTab === 'trading'
    ) {
      switchTab('overview');
    }

    window.resetTradingTab?.();
  }

  populateFilterOptions(state.botFilters);
  renderAlerts();
  renderBots();
  renderArchivedBots();

  if (state.currentBotData?.bot) {
    updateBotAdminControls(
      state.currentBotData.bot
    );
  }
  renderBotControlAccess();
}
function lockAdmin(showMessage = true) {
  state.adminAuthorization = '';
  state.adminUser = null;
  state.currentRawData = null;
  clearPrivateBalance();
  clearDepositHistory();
  clearDepositState({ keepCatalog: false });
  clearBotControlSession();
  const depositDialog = $('#depositDialog');
  if (depositDialog?.open) depositDialog.close();
  const passwordDialog = $('#changePasswordDialog');
  if (passwordDialog?.open) passwordDialog.close();
  renderAdminState();
  renderBotRaw();
  if (showMessage) showToast('Account session locked.');
}

async function unlockAdmin(event) {
  event.preventDefault();

  // Event.currentTarget is not reliable after an await. Keep the form reference
  // before making the API request so a successful login can reset and close it.
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  const username = String(form.get('username') || '').trim();
  const password = String(form.get('password') || '');
  const authorization = basicAuthorization(username, password);
  const submitButton = $('#adminSubmitButton');

  setAdminError('');
  submitButton.disabled = true;
  submitButton.textContent = 'Unlocking…';

  try {
    const result = await api('/api/auth/me', { headers: { Authorization: authorization } });
    state.adminAuthorization = authorization;
    state.adminUser = result.user;
    await loadBotControlCapabilities();
    formElement.reset();
    $('#adminDialog').close();
    renderAdminState();
    switchTab('wallet');
    showToast(`Signed in as ${result.user.username}.`);
    if (state.currentBotData?.bot && canManageAccount(state.currentBotData.bot.account_id)) {
      await loadCurrentBotRaw();
    }
  } catch (error) {
    const message = error instanceof ApiError && error.status === 401
      ? 'Invalid username or password.'
      : error instanceof TypeError
        ? 'The dashboard could not contact the API. Check the network connection and CORS configuration.'
        : (error.message || 'Unable to unlock account actions.');

    setAdminError(message);
    const passwordInput = formElement.querySelector('input[name="password"]');
    if (passwordInput) {
      passwordInput.value = '';
      passwordInput.focus();
    }
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = 'Unlock';
  }
}

async function changeOwnPassword(event) {
  event.preventDefault();

  if (!state.adminUser || !state.adminAuthorization) {
    $('#changePasswordDialog').close();
    openAdminDialog();
    return;
  }

  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  const currentPassword = String(form.get('current_password') || '');
  const newPassword = String(form.get('new_password') || '');
  const confirmPassword = String(form.get('confirm_password') || '');
  const submitButton = $('#changePasswordSubmitButton');

  setChangePasswordError('');
  if (newPassword.length < 12) {
    setChangePasswordError('The new password must contain at least 12 characters.');
    formElement.querySelector('input[name="new_password"]')?.focus();
    return;
  }
  if (newPassword !== confirmPassword) {
    setChangePasswordError('The new password and confirmation do not match.');
    formElement.querySelector('input[name="confirm_password"]')?.focus();
    return;
  }
  if (currentPassword === newPassword) {
    setChangePasswordError('The new password must be different from the current password.');
    formElement.querySelector('input[name="new_password"]')?.focus();
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = 'Changing…';

  try {
    await adminApi('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      }),
    });

    // Basic authentication is stateless. Keep this browser session unlocked by
    // replacing the in-memory Authorization value with the new password.
    state.adminAuthorization = basicAuthorization(state.adminUser.username, newPassword);
    formElement.reset();
    $('#changePasswordDialog').close();
    showToast('Password changed successfully.');
  } catch (error) {
    const message = error instanceof ApiError && error.status === 401
      ? 'Your admin session is no longer valid. Unlock it again.'
      : error instanceof TypeError
        ? 'The dashboard could not contact the API. Check the network connection and CORS configuration.'
        : (error.message || 'Unable to change the password.');
    setChangePasswordError(message);
    const currentInput = formElement.querySelector('input[name="current_password"]');
    if (currentInput) {
      currentInput.value = '';
      currentInput.focus();
    }
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = 'Change password';
  }
}

function showToast(message, error = false) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.className = `toast show${error ? ' error' : ''}`;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.className = 'toast'; }, 3200);
}

function fmtMoney(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Number(value));
}

function hasValue(value) {
  return value !== null
    && value !== undefined
    && value !== '';
}

function numericValue(value) {
  if (!hasValue(value)) return null;

  const number = Number(
    String(value).replaceAll(',', '')
  );

  return Number.isFinite(number) ? number : null;
}

function marketAssets(market) {
  const parts = String(market || '')
    .trim()
    .toUpperCase()
    .split(/[_\/-]/)
    .filter(Boolean);

  return {
    base: parts[0] || '',
    quote: parts.slice(1).join('_') || '',
  };
}

function fmtPrice(value, quoteAsset = 'USD') {
  const number = numericValue(value);
  if (number === null) return '—';

  const absolute = Math.abs(number);

  let maximumDigits = 2;

  if (absolute > 0 && absolute < 0.0001) {
    maximumDigits = 10;
  } else if (absolute < 0.01) {
    maximumDigits = 8;
  } else if (absolute < 1) {
    maximumDigits = 6;
  } else if (absolute < 100) {
    maximumDigits = 4;
  }

  const formatted = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: maximumDigits,
  }).format(number);

  const quote = String(
    quoteAsset || 'USD'
  ).toUpperCase();

  if (
    ['USD', 'USDT', 'USDC', 'DAI'].includes(quote)
  ) {
    return `$${formatted}`;
  }

  return `${formatted} ${quote}`;
}

function fmtQuoteValue(value, quoteAsset = 'USD') {
  const number = numericValue(value);
  if (number === null) return '—';

  const absolute = Math.abs(number);

  const maximumDigits = (
    absolute > 0 && absolute < 0.01
      ? 8
      : absolute < 1
        ? 6
        : 2
  );

  const formatted = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: maximumDigits,
  }).format(number);

  const quote = String(
    quoteAsset || 'USD'
  ).toUpperCase();

  if (
    ['USD', 'USDT', 'USDC', 'DAI'].includes(quote)
  ) {
    return `$${formatted}`;
  }

  return `${formatted} ${quote}`;
}

function fmtPriceRange(value, quoteAsset = 'USD') {
  if (!value) return '—';

  const match = String(value)
    .trim()
    .match(
      /^([0-9.,]+)\s*[-–]\s*([0-9.,]+)$/
    );

  if (!match) return String(value);

  return (
    `${fmtPrice(match[1], quoteAsset)}`
    + ` – ${fmtPrice(match[2], quoteAsset)}`
  );
}

function sameNumericValue(left, right) {
  const a = numericValue(left);
  const b = numericValue(right);

  if (a === null || b === null) return false;

  return Math.abs(a - b) <= (
    Math.max(1, Math.abs(a), Math.abs(b))
    * 1e-12
  );
}

function fmtNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(Number(value));
}

function fmtPct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  const n = Number(value);
  return `${n > 0 ? '+' : ''}${fmtNumber(n, digits)}%`;
}

function ratioPct(value) {
  const ratio = numericValue(value);

  return ratio === null
    ? null
    : ratio * 100;
}

function fmtRatioPct(value, digits = 2) {
  const percentage = ratioPct(value);

  return percentage === null
    ? '—'
    : fmtPct(percentage, digits);
}

function annualizedAprPct(rate, runtimeSeconds) {
  const ratio = numericValue(rate);
  const seconds = numericValue(runtimeSeconds);

  if (
    ratio === null
    || seconds === null
    || seconds <= 0
  ) {
    return null;
  }

  return (
    ratio
    * (365 * 24 * 60 * 60 / seconds)
    * 100
  );
}

function fmtDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const s = Math.max(0, Number(seconds));
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const mins = Math.floor((s % 3600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

function valueClass(value) { return Number(value) > 0 ? 'positive' : Number(value) < 0 ? 'negative' : ''; }
function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#039;', '"':'&quot;' }[c])); }
function strategyLabel(value) { return String(value || 'unknown').replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase()); }

function withParams(path, params = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') url.searchParams.set(key, value);
  });
  return `${url.pathname}${url.search}`;
}

function scopedPath(path, params = {}) {
  return withParams(path, { ...params, account_id: state.selectedAccount || undefined });
}

function privateBalanceTargetAccount() {
  const user = state.adminUser;
  if (!user) return '';
  if (state.selectedAccount && canManageAccount(state.selectedAccount)) return state.selectedAccount;
  const assigned = user.account_ids || [];
  if (assigned.length === 1) return assigned[0];
  return '';
}

function clearPrivateBalance() {
  state.privateBalance = null;
  state.privateBalanceAccountId = '';
  state.privateBalanceFetchedAt = 0;
  $('#privateBalancePanel')?.classList.add('hidden');
  $('#privateBalanceContent')?.classList.add('hidden');
  $('#privateBalanceLoading')?.classList.add('hidden');
  $('#privateBalanceError')?.classList.add('hidden');
  $('#privateBalanceSelect')?.classList.add('hidden');
  if ($('#privateAssetsBody')) $('#privateAssetsBody').innerHTML = '';
  if ($('#privateAccountBreakdown')) $('#privateAccountBreakdown').innerHTML = '';
}

function setPrivateBalanceView(view, message = '') {
  const panel = $('#privateBalancePanel');
  if (!panel) return;
  panel.classList.toggle('hidden', !state.adminUser);
  $('#privateBalanceLoading').classList.toggle('hidden', view !== 'loading');
  $('#privateBalanceError').classList.toggle('hidden', view !== 'error');
  $('#privateBalanceSelect').classList.toggle('hidden', view !== 'select');
  $('#privateBalanceContent').classList.toggle('hidden', view !== 'content');
  if (view === 'error') $('#privateBalanceError').textContent = message;
  if (view === 'select' && message) $('#privateBalanceSelect').textContent = message;
}

function fmtAssetQuantity(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  const absolute = Math.abs(Number(value));
  const digits = absolute >= 1_000_000 ? 0 : absolute >= 1_000 ? 2 : absolute >= 1 ? 4 : 8;
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(Number(value));
}

function renderPrivateBalance() {
  const data = state.privateBalance;
  if (!state.adminUser || !data) return;

  const summary = data.summary || {};
  const usdt = summary.usdt || {};
  const eqty = summary.eqty || {};
  const bot = data.bot_allocation || {};
  const quantValue = data.quant_value ?? bot.current_value;

  $('#privateBalanceSubtitle').textContent = `Private · ${data.display_name} (${data.account_id})`;
  $('#privateTotalValue').textContent = fmtMoney(data.total_value);
  $('#privateTotalNote').textContent = data.source === 'demo'
    ? 'Demo account estimate'
    : 'Gate wallet estimate · may be cached up to 1 minute';

  $('#privateUsdtTotal').textContent = `${fmtAssetQuantity(usdt.total || 0)} USDT`;
  $('#privateUsdtNote').textContent = `${fmtAssetQuantity(usdt.available || 0)} available · ${fmtAssetQuantity(usdt.locked || 0)} locked`;

  $('#privateEqtyTotal').textContent = `${fmtAssetQuantity(eqty.total || 0)} EQTY`;
  $('#privateEqtyNote').textContent = eqty.value_usdt === null || eqty.value_usdt === undefined
    ? 'No direct USDT valuation available'
    : `${fmtMoney(eqty.value_usdt)} · ${fmtMoney(eqty.price_usdt, 8)} per EQTY`;

  $('#privateQuantValue').textContent = fmtMoney(quantValue);
  $('#privateQuantNote').textContent = `${bot.running_bots || 0} running · tracked ${fmtMoney(bot.current_value)} current / ${fmtMoney(bot.initial_capital)} initial`;

  $('#privateOtherValue').textContent = fmtMoney(summary.other_value || 0);
  $('#privateOtherNote').textContent = `${summary.other_count || 0} non-zero token${Number(summary.other_count || 0) === 1 ? '' : 's'}`;

  $('#privateBalanceUpdated').textContent = `Updated ${fmtDate(data.as_of)}${data.cache?.hit ? ' · cached' : ''}`;
  $('#privateBalanceCoverage').textContent = `${(data.assets || []).length} non-zero spot assets · ${summary.unvalued_count || 0} without USDT price`;

  const breakdown = data.account_breakdown || [];
  $('#privateAccountBreakdown').innerHTML = breakdown.length
    ? breakdown.map(item => `<span class="private-account-chip"><span>${escapeHtml(String(item.account_type).replaceAll('_', ' '))}</span><strong>${fmtMoney(item.amount)}</strong></span>`).join('')
    : '<span class="private-account-chip">No Gate account-type breakdown returned</span>';

  const assets = data.assets || [];
  $('#privateAssetsBody').innerHTML = assets.length
    ? assets.map(asset => `<tr>
        <td><strong>${escapeHtml(asset.currency)}</strong>${asset.is_dust ? ' <span class="status-badge">dust</span>' : ''}</td>
        <td>${fmtAssetQuantity(asset.available)}</td>
        <td>${fmtAssetQuantity(asset.locked)}</td>
        <td>${fmtAssetQuantity(asset.total)}</td>
        <td>${asset.price_usdt === null || asset.price_usdt === undefined ? '—' : fmtAssetQuantity(asset.price_usdt)}</td>
        <td>${asset.value_usdt === null || asset.value_usdt === undefined ? '—' : fmtMoney(asset.value_usdt)}</td>
      </tr>`).join('')
    : '<tr><td colspan="6" class="empty-state">No non-zero spot assets returned.</td></tr>';

  setPrivateBalanceView('content');
}

async function loadPrivateBalance({ force = false, quiet = false } = {}) {
  if (!state.adminUser || !state.adminAuthorization) {
    clearPrivateBalance();
    return;
  }

  const accountId = privateBalanceTargetAccount();
  $('#privateBalancePanel').classList.remove('hidden');
  if (!accountId) {
    state.privateBalance = null;
    setPrivateBalanceView('select', 'Select one of your assigned accounts above to view its private balance.');
    return;
  }

  const freshClientCache = state.privateBalance
    && state.privateBalanceAccountId === accountId
    && Date.now() - state.privateBalanceFetchedAt < 25_000;
  if (!force && freshClientCache) {
    renderPrivateBalance();
    return;
  }

  const button = $('#refreshPrivateBalance');
  button.disabled = true;
  button.textContent = 'Loading…';
  setPrivateBalanceView('loading');

  try {
    const result = await adminApi(withParams('/api/me/balance', {
      account_id: accountId,
      refresh: force ? 'true' : undefined,
    }));
    state.privateBalance = result;
    state.privateBalanceAccountId = accountId;
    state.privateBalanceFetchedAt = Date.now();
    renderPrivateBalance();
  } catch (error) {
    if (state.adminUser) setPrivateBalanceView('error', error.message || 'Unable to load the private account balance.');
    if (!quiet && state.adminUser) showToast(error.message || 'Unable to load private balance.', true);
  } finally {
    button.disabled = false;
    button.textContent = 'Refresh balance';
  }
}

function setDepositError(message = '') {
  const element = $('#depositError');
  if (!element) return;
  element.textContent = message;
  element.classList.toggle('hidden', !message);
}

function setDepositLoading(loading) {
  $('#depositLoading')?.classList.toggle('hidden', !loading);
}

function clearDepositDetails() {
  state.depositChain = '';
  state.depositDetails = null;
  $('#depositDetails')?.classList.add('hidden');
  $('#depositDetailsPlaceholder')?.classList.remove('hidden');
  if ($('#depositDetailsPlaceholder')) {
    $('#depositDetailsPlaceholder').textContent =
      'Select a network to reveal the address and QR code.';
  }
  if ($('#depositQr')) $('#depositQr').removeAttribute('src');
  if ($('#depositAddress')) $('#depositAddress').textContent = '—';
  if ($('#depositMemo')) $('#depositMemo').textContent = '—';
  $('#depositMemoBlock')?.classList.add('hidden');
  $('#depositDetailsStep')?.classList.add('deposit-step-disabled');
}

function clearDepositState({ keepCatalog = true } = {}) {
  if (!keepCatalog) {
    state.depositCatalog = [];
    state.depositFavorites = [];
  }
  state.depositCurrency = '';
  state.depositNetworks = [];
  clearDepositDetails();
  if ($('#depositCurrencySearch')) $('#depositCurrencySearch').value = '';
  if ($('#depositNetworkList')) {
    $('#depositNetworkList').innerHTML =
      '<div class="deposit-empty">Select a coin first.</div>';
  }
  $('#depositNetworkStep')?.classList.add('deposit-step-disabled');
  setDepositError('');
}

function depositTargetAccount() {
  return privateBalanceTargetAccount();
}

function depositAssetMark(symbol) {
  return escapeHtml(String(symbol || '').slice(0, 3));
}

function renderDepositFavorites() {
  const container = $('#depositFavorites');
  if (!container) return;
  container.innerHTML = state.depositFavorites.map(symbol => `
    <button
      type="button"
      class="deposit-favorite ${state.depositCurrency === symbol ? 'active' : ''}"
      data-deposit-currency="${escapeHtml(symbol)}"
    >${escapeHtml(symbol)}</button>
  `).join('');
}

function renderDepositCurrencies() {
  const container = $('#depositCurrencyList');
  if (!container) return;

  const query = String(
    $('#depositCurrencySearch')?.value || ''
  ).trim().toLowerCase();

  const filtered = state.depositCatalog.filter(item => (
    !query
    || item.currency.toLowerCase().includes(query)
    || String(item.name || '').toLowerCase().includes(query)
  ));

  const visible = filtered.slice(0, 300);

  container.innerHTML = visible.length
    ? visible.map(item => `
      <button
        type="button"
        class="deposit-option ${state.depositCurrency === item.currency ? 'active' : ''}"
        data-deposit-currency="${escapeHtml(item.currency)}"
        ${item.deposit_available ? '' : 'disabled'}
      >
        <span class="deposit-option-main">
          <i class="deposit-coin-mark">${depositAssetMark(item.currency)}</i>
          <span>
            <strong>${escapeHtml(item.currency)}</strong>
            <small>${escapeHtml(item.name || item.currency)}</small>
          </span>
        </span>
        <span class="deposit-option-status ${item.deposit_available ? 'available' : ''}">
          ${item.deposit_available ? 'Deposit available' : 'Unavailable'}
        </span>
      </button>
    `).join('')
    : '<div class="deposit-empty">No matching Gate currencies.</div>';

  const suffix = filtered.length > visible.length
    ? ` · showing first ${visible.length}; refine the search`
    : '';

  $('#depositCurrencyCount').textContent =
    `${filtered.length} matching currenc${filtered.length === 1 ? 'y' : 'ies'}${suffix}`;

  renderDepositFavorites();
}

function renderDepositNetworks() {
  const container = $('#depositNetworkList');
  const networks = state.depositNetworks || [];

  container.innerHTML = networks.length
    ? networks.map(network => `
      <button
        type="button"
        class="deposit-option ${state.depositChain === network.chain ? 'active' : ''}"
        data-deposit-chain="${escapeHtml(network.chain)}"
        ${network.deposit_enabled ? '' : 'disabled'}
      >
        <span class="deposit-option-main">
          <i class="deposit-coin-mark">${depositAssetMark(network.chain)}</i>
          <span>
            <strong>${escapeHtml(network.name || network.chain)}</strong>
            <small>
              ${escapeHtml(network.chain)}
              ${network.contract_address
                ? ` · contract ${escapeHtml(network.contract_address)}`
                : ''}
            </small>
          </span>
        </span>
        <span class="deposit-option-status ${network.deposit_enabled ? 'available' : ''}">
          ${network.deposit_enabled ? 'Available' : 'Deposits disabled'}
        </span>
      </button>
    `).join('')
    : '<div class="deposit-empty">Gate returned no deposit networks for this currency.</div>';

  $('#depositNetworkStep').classList.toggle(
    'deposit-step-disabled',
    !networks.length,
  );
}

async function loadDepositCatalog() {
  if (state.depositCatalog.length) return;

  setDepositLoading(true);
  try {
    const result = await api('/api/deposit/currencies');
    state.depositCatalog = result.currencies || [];
    state.depositFavorites = result.favorites || [];
    renderDepositCurrencies();
  } finally {
    setDepositLoading(false);
  }
}

async function openDepositDialog() {
  if (!state.adminUser || !state.adminAuthorization) {
    openAdminDialog();
    return;
  }

  const accountId = depositTargetAccount();
  if (!accountId) {
    showToast('Select one of your assigned accounts first.', true);
    return;
  }

  clearDepositState({ keepCatalog: true });
  $('#depositAccountLabel').textContent =
    `Deposit to ${accountId}. Addresses are loaded from Gate only after you select a network.`;

  const dialog = $('#depositDialog');
  if (!dialog.open) dialog.showModal();

  try {
    await loadDepositCatalog();
    renderDepositCurrencies();
    setTimeout(() => $('#depositCurrencySearch')?.focus(), 0);
  } catch (error) {
    setDepositError(error.message || 'Unable to load Gate currencies.');
  }
}

function closeDepositDialog() {
  clearDepositState({ keepCatalog: true });
  if ($('#depositDialog')?.open) $('#depositDialog').close();
}

async function selectDepositCurrency(symbol) {
  const item = state.depositCatalog.find(
    entry => entry.currency === symbol,
  );
  if (!item || !item.deposit_available) return;

  state.depositCurrency = symbol;
  state.depositNetworks = [];
  clearDepositDetails();
  state.depositCurrency = symbol;
  renderDepositCurrencies();

  $('#depositNetworkList').innerHTML =
    '<div class="deposit-empty">Loading networks…</div>';
  $('#depositNetworkStep').classList.remove('deposit-step-disabled');
  setDepositError('');

  try {
    const accountId = depositTargetAccount();
    const result = await adminApi(withParams(
      `/api/me/deposit/${encodeURIComponent(symbol)}/networks`,
      { account_id: accountId },
    ));
    state.depositNetworks = result.networks || [];
    renderDepositNetworks();
  } catch (error) {
    state.depositNetworks = [];
    $('#depositNetworkList').innerHTML =
      '<div class="deposit-empty">Unable to load networks.</div>';
    setDepositError(
      error.message || 'Unable to load Gate deposit networks.',
    );
  }
}

async function selectDepositNetwork(chain) {
  const network = state.depositNetworks.find(
    item => item.chain === chain,
  );
  if (
    !network
    || !network.deposit_enabled
    || !state.depositCurrency
  ) return;

  clearDepositDetails();
  state.depositChain = chain;
  renderDepositNetworks();
  $('#depositDetailsStep').classList.remove('deposit-step-disabled');
  $('#depositDetailsPlaceholder').textContent =
    'Loading the account-specific address…';
  setDepositError('');

  try {
    const accountId = depositTargetAccount();
    const result = await adminApi(withParams(
      `/api/me/deposit/${encodeURIComponent(state.depositCurrency)}`,
      {
        account_id: accountId,
        chain,
      },
    ));
    state.depositDetails = result;
    renderDepositDetails();
  } catch (error) {
    $('#depositDetailsPlaceholder').textContent =
      'Select a network to reveal the address and QR code.';
    setDepositError(
      error.message || 'Unable to load the Gate deposit address.',
    );
  }
}

function renderDepositDetails() {
  const result = state.depositDetails;
  const network = result?.network;
  if (!result || !network) return;

  $('#depositSelectedAsset').textContent = result.currency;
  $('#depositSelectedNetwork').textContent =
    network.name || network.chain;
  $('#depositAddress').textContent = network.address || '—';
  $('#depositQr').src = network.qr_svg_data_uri || '';
  $('#depositContract').textContent =
    network.contract_address || 'Native asset / not provided';
  $('#depositMinimum').textContent = result.minimum_deposit_amount
    ? `${result.minimum_deposit_amount} ${result.currency}`
    : 'Not provided';
  $('#depositConfirmations').textContent =
    network.min_confirmations ?? 'Not provided';
  $('#depositWarning').textContent = result.warning || '';

  const memo = network.payment_id;
  $('#depositMemoBlock').classList.toggle('hidden', !memo);

  if (memo) {
    $('#depositMemo').textContent = memo;
    $('#depositMemoLabel').textContent =
      network.payment_name || 'Memo / tag';
  }

  $('#depositDetailsPlaceholder').classList.add('hidden');
  $('#depositDetails').classList.remove('hidden');
}

async function copyDepositValue(kind) {
  const value = kind === 'memo'
    ? state.depositDetails?.network?.payment_id
    : state.depositDetails?.network?.address;

  if (!value) return;

  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const textarea = document.createElement('textarea');
    textarea.value = value;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    textarea.remove();
  }

  showToast(
    `${kind === 'memo' ? 'Memo / tag' : 'Address'} copied.`,
  );
}

function depositHistoryTargetAccount() {
  return privateBalanceTargetAccount();
}

function depositStatusClass(status) {
  return String(status || 'unknown').toLowerCase().replace(/_/g, '-');
}

function clearDepositHistory() {
  state.depositHistory = [];
  $('#depositHistoryBody') && ($('#depositHistoryBody').innerHTML = '');
  $('#depositHistoryTableWrap')?.classList.add('hidden');
  $('#depositHistoryEmpty')?.classList.add('hidden');
  $('#depositHistoryError')?.classList.add('hidden');
  if ($('#depositHistoryCount')) $('#depositHistoryCount').textContent = '0 records';
  if ($('#depositHistorySyncState')) $('#depositHistorySyncState').textContent = 'Not synchronized yet';
}

function renderDepositHistory(payload) {
  const items = payload.items || [];
  state.depositHistory = items;
  $('#depositHistoryBody').innerHTML = items.map(item => `
    <tr>
      <td>${escapeHtml(fmtDate(item.deposited_at))}</td>
      <td><strong>${escapeHtml(item.currency)}</strong></td>
      <td>${escapeHtml(item.chain || '—')}</td>
      <td>${escapeHtml(item.amount)}</td>
      <td><span class="deposit-status ${depositStatusClass(item.status)}">${escapeHtml(item.status)}</span></td>
      <td>${item.txid ? `<code title="${escapeHtml(item.txid)}">${escapeHtml(item.txid)}</code>` : '—'}</td>
    </tr>
  `).join('');
  $('#depositHistoryTableWrap').classList.toggle('hidden', !items.length);
  $('#depositHistoryEmpty').classList.toggle('hidden', Boolean(items.length));
  $('#depositHistoryCount').textContent = `${payload.total || 0} record${payload.total === 1 ? '' : 's'}`;
  const sync = payload.sync || {};
  const syncText = sync.last_success_at
    ? `Last Gate sync ${fmtDate(sync.last_success_at)} · ${sync.status}`
    : sync.last_error
      ? `Sync error: ${sync.last_error}`
      : 'Not synchronized yet';
  $('#depositHistorySyncState').textContent = syncText;
}

async function loadDepositHistory({ quiet = false } = {}) {
  if (!state.adminUser || !state.adminAuthorization) {
    clearDepositHistory();
    return;
  }
  const accountId = depositHistoryTargetAccount();
  if (!accountId) {
    clearDepositHistory();
    return;
  }
  if (!quiet) $('#depositHistoryLoading').classList.remove('hidden');
  $('#depositHistoryError').classList.add('hidden');
  try {
    const payload = await adminApi(withParams('/api/me/deposits', {
      account_id: accountId,
      limit: 25,
      offset: 0,
    }));
    renderDepositHistory(payload);
  } catch (error) {
    $('#depositHistoryError').textContent = error.message || 'Unable to load deposit history.';
    $('#depositHistoryError').classList.remove('hidden');
  } finally {
    $('#depositHistoryLoading').classList.add('hidden');
  }
}

async function syncDepositHistory() {
  if (!state.adminUser || !state.adminAuthorization) {
    openAdminDialog();
    return;
  }
  const accountId = depositHistoryTargetAccount();
  if (!accountId) {
    showToast('Select one assigned account first.', true);
    return;
  }
  const button = $('#syncDepositHistory');
  button.disabled = true;
  button.textContent = 'Syncing…';
  try {
    const result = await adminApi(withParams('/api/me/deposits/sync', {
      account_id: accountId,
    }), { method: 'POST' });
    showToast(`Deposit sync complete: ${result.record_count || 0} Gate record(s).`);
    await loadDepositHistory();
  } catch (error) {
    showToast(error.message || 'Deposit sync failed.', true);
    await loadDepositHistory({ quiet: true });
  } finally {
    button.disabled = false;
    button.textContent = 'Sync Gate deposits';
  }
}



function shortBotControlRequestId(value) {
  const text = String(value || '');

  if (text.length <= 26) {
    return text;
  }

  return (
    `${text.slice(0, 14)}…`
    + `${text.slice(-9)}`
  );
}

function botControlActivityStatusClass(status) {
  const normalized = String(
    status || ''
  ).toLowerCase();

  if (
    [
      'simulated',
      'succeeded',
      'rejected',
      'uncertain',
      'reserved',
      'submitting',
    ].includes(normalized)
  ) {
    return normalized;
  }

  return 'other';
}


function botControlActionLabel(action) {
  if (action === 'spot_grid_create') {
    return 'Create Spot Grid';
  }

  if (action === 'bot_stop') {
    return 'Stop Bot';
  }

  return action || '—';
}



function formatBotControlAttentionAge(seconds) {
  const value = Math.max(
    0,
    Number(seconds || 0),
  );

  if (value < 60) {
    return `${Math.floor(value)}s`;
  }

  if (value < 3600) {
    return `${Math.floor(value / 60)}m`;
  }

  if (value < 86400) {
    return `${Math.floor(value / 3600)}h`;
  }

  return `${Math.floor(value / 86400)}d`;
}


function renderBotControlAttention() {
  const container = $(
    '#botControlAttentionList'
  );

  const badge = $(
    '#botControlAttentionBadge'
  );

  const countElement = $(
    '#botControlAttentionCount'
  );

  const rows = (
    state.botControlAttention
    || []
  );

  const panel = container?.closest(
    '.bot-control-attention-panel'
  );

  panel?.classList.toggle(
    'is-clear',
    rows.length === 0,
  );

  if (badge) {
    badge.textContent = String(
      rows.length
    );

    badge.classList.toggle(
      'hidden',
      rows.length === 0,
    );
  }

  if (countElement) {
    countElement.textContent = String(
      rows.length
    );

    countElement.classList.toggle(
      'is-clear',
      rows.length === 0,
    );
  }

  if (!container) {
    return;
  }

  if (!rows.length) {
    container.innerHTML = (
      '<div class="bot-control-attention-clear">'
      + '<span aria-hidden="true">✓</span>'
      + '<strong>All clear</strong>'
      + '<span>No Bot Control requests need attention.</span>'
      + '</div>'
    );

    return;
  }

  container.innerHTML = rows.map(item => {
    const lock = (
      item.operation_lock
      || {}
    );

    const reconciliation = (
      item.latest_reconciliation
      || {}
    );

    const requestId = String(
      item.request_id
      || ''
    );

    const severity = String(
      item.severity
      || 'medium'
    );

    const lockText = (
      lock.state
        ? (
          `${lock.state} · `
          + `${lock.lock_type || 'lock'}`
        )
        : 'none'
    );

    const reconciliationText = (
      reconciliation.outcome
        ? reconciliationLabel(
            reconciliation.outcome
          )
        : 'not run'
    );

    return (
      `<article class="bot-control-attention-card ${
        escapeHtml(severity)
      }">`

      + '<div class="bot-control-attention-head">'

      + `<span class="bot-control-attention-severity ${
        escapeHtml(severity)
      }">${escapeHtml(severity)}</span>`

      + `<strong>${
        escapeHtml(
          item.account_id || '—'
        )
      } · ${
        escapeHtml(
          botControlActionLabel(
            item.action
          )
        )
      }</strong>`

      + '</div>'

      + '<div class="bot-control-attention-main">'

      + '<div class="bot-control-attention-field">'
      + '<span>Market</span>'
      + `<strong>${escapeHtml(
          item.market || '—'
        )}</strong>`
      + '</div>'

      + '<div class="bot-control-attention-field">'
      + '<span>Status</span>'
      + `<strong>${escapeHtml(
          item.status || '—'
        )}</strong>`
      + '</div>'

      + '<div class="bot-control-attention-field">'
      + '<span>Operation lock</span>'
      + `<strong>${escapeHtml(
          lockText
        )}</strong>`
      + '</div>'

      + '<div class="bot-control-attention-field">'
      + '<span>Reconciliation</span>'
      + `<strong>${escapeHtml(
          reconciliationText
        )}</strong>`
      + '</div>'

      + '<div class="bot-control-attention-field">'
      + '<span>Strategy ID</span>'
      + `<strong>${escapeHtml(
          item.strategy_id || '—'
        )}</strong>`
      + '</div>'

      + '<div class="bot-control-attention-field">'
      + '<span>Operator</span>'
      + `<strong>${escapeHtml(
          item.username || '—'
        )}</strong>`
      + '</div>'

      + '<div class="bot-control-attention-field">'
      + '<span>Age</span>'
      + `<strong>${escapeHtml(
          formatBotControlAttentionAge(
            item.age_seconds
          )
        )}</strong>`
      + '</div>'

      + '<div class="bot-control-attention-field">'
      + '<span>Request</span>'

      + `<button
          type="button"
          class="bot-control-activity-request-button bot-control-activity-request"
          data-bot-control-attention-request="${escapeHtml(requestId)}"
          title="${escapeHtml(requestId)}"
        >${escapeHtml(
          shortBotControlRequestId(
            requestId
          )
        )}</button>`

      + '</div>'

      + '</div>'

      + '<div class="bot-control-attention-recommendation">'
      + '<strong>Recommended action</strong>'
      + `${escapeHtml(
          item.recommended_action
          || 'Review this request.'
        )}`
      + '</div>'

      + '<div class="bot-control-attention-meta">'
      + `Created ${escapeHtml(
          fmtDate(item.created_at)
        )}`

      + (
        item.manual_release_available
          ? ' · Manual release available after review'
          : ''
      )

      + '</div>'

      + (
        item.review_available
          ? (
            '<div class="form-actions">'
            + `<button
                type="button"
                class="text-button"
                data-bot-control-attention-review="${escapeHtml(requestId)}"
              >Mark reviewed</button>`
            + '</div>'
          )
          : ''
      )

      + '</article>'
    );
  }).join('');
}


async function loadBotControlAttention(
  {
    quiet = false,
  } = {},
) {
  if (!botControlAvailable()) {
    state.botControlAttention = [];
    state.botControlAttentionSummary = null;

    renderBotControlAttention();

    return;
  }

  const button = $(
    '#refreshBotControlAttention'
  );

  const errorBox = $(
    '#botControlAttentionError'
  );

  if (button) {
    button.disabled = true;
    button.textContent = 'Loading…';
  }

  if (errorBox) {
    errorBox.textContent = '';
    errorBox.classList.add(
      'hidden'
    );
  }

  try {
    const result = await adminApi(
      '/api/bot-control/attention?limit=50'
    );

    state.botControlAttention = (
      result.items
      || []
    );

    state.botControlAttentionSummary = (
      result.summary
      || null
    );

    renderBotControlAttention();

  } catch (error) {
    if (errorBox) {
      errorBox.textContent = (
        botControlErrorMessage(
          error
        )
      );

      errorBox.classList.remove(
        'hidden'
      );
    }

    if (!quiet) {
      showToast(
        botControlErrorMessage(
          error
        ),
        true,
      );
    }

  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = 'Refresh';
    }
  }
}



async function downloadBotControlAuditExport(
  format,
) {
  if (
    !state.adminUser
    || !state.adminAuthorization
  ) {
    openAdminDialog();
    return;
  }

  const extension = (
    format === 'csv'
      ? 'csv'
      : 'json'
  );

  const button = (
    extension === 'csv'
      ? $('#exportBotControlCsv')
      : $('#exportBotControlJson')
  );

  const originalText = (
    button?.textContent
    || ''
  );

  if (button) {
    button.disabled = true;
    button.textContent = 'Exporting…';
  }

  try {
    const response = await fetch(
      apiUrl(
        `/api/bot-control/export/${
          extension
        }?limit=1000`
      ),
      {
        method: 'GET',
        credentials: 'omit',
        headers: {
          Authorization:
            state.adminAuthorization,
        },
      },
    );

    if (!response.ok) {
      let payload = null;

      try {
        payload = await response.json();
      } catch {
        payload = null;
      }

      let message = (
        payload?.detail?.message
        || payload?.detail
        || `Export failed (${response.status})`
      );

      if (
        typeof message
        !== 'string'
      ) {
        message = JSON.stringify(
          message
        );
      }

      throw new ApiError(
        message,
        response.status,
        payload,
      );
    }

    const blob = (
      await response.blob()
    );

    const url = (
      URL.createObjectURL(
        blob
      )
    );

    const stamp = (
      new Date()
        .toISOString()
        .replaceAll('-', '')
        .replaceAll(':', '')
        .replace(/\.\d{3}Z$/, 'Z')
    );

    const anchor = (
      document.createElement('a')
    );

    anchor.href = url;

    anchor.download = (
      `bot_control_audit_${stamp}.`
      + extension
    );

    document.body.appendChild(
      anchor
    );

    anchor.click();
    anchor.remove();

    URL.revokeObjectURL(
      url
    );

    showToast(
      `Bot Control audit exported as ${
        extension.toUpperCase()
      }.`
    );

  } catch (error) {
    showToast(
      botControlErrorMessage(
        error
      ),
      true,
    );

  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = (
        originalText
      );
    }
  }
}


function formatBotControlUtcDate(value) {
  if (!value) {
    return '—';
  }

  const date = new Date(value);

  if (Number.isNaN(date.valueOf())) {
    return String(value);
  }

  const pad = number => String(
    number
  ).padStart(
    2,
    '0',
  );

  return (
    `${date.getUTCFullYear()}-`
    + `${pad(date.getUTCMonth() + 1)}-`
    + `${pad(date.getUTCDate())} `
    + `${pad(date.getUTCHours())}:`
    + `${pad(date.getUTCMinutes())}:`
    + `${pad(date.getUTCSeconds())}`
  );
}


function renderBotControlActivity() {
  const body = $('#botControlActivityBody');

  if (!body) {
    return;
  }

  const rows = (
    state.botControlActivity
    || []
  );

  const pagination = (
    state.botControlActivityPagination
    || {
      limit: 10,
      offset: 0,
      total: 0,
      hasPrevious: false,
      hasNext: false,
    }
  );

  const limit = Math.max(
    1,
    Number(pagination.limit) || 10,
  );

  const offset = Math.max(
    0,
    Number(pagination.offset) || 0,
  );

  const total = Math.max(
    0,
    Number(pagination.total) || 0,
  );

  if (!rows.length) {
    body.innerHTML = (
      '<tr>'
      + '<td colspan="10" class="empty-state">'
      + 'No Bot Control activity recorded.'
      + '</td>'
      + '</tr>'
    );

  } else {
    body.innerHTML = rows.map(item => {
      const mode = String(
        item.mode || 'pending'
      ).toLowerCase();

      const status = String(
        item.status || 'unknown'
      ).toLowerCase();

      const requestId = String(
        item.request_id || ''
      );

      const investment = (
        item.investment !== null
        && item.investment !== undefined
      )
        ? `${item.investment} USDT`
        : '—';

      return (
        '<tr>'
        + `<td>${escapeHtml(
          formatBotControlUtcDate(
            item.created_at
          )
        )}</td>`
        + `<td><strong>${escapeHtml(item.account_id || '—')}</strong></td>`
        + `<td>${escapeHtml(item.username || '—')}</td>`
        + `<td>${escapeHtml(botControlActionLabel(item.action))}</td>`
        + `<td>${escapeHtml(item.market || '—')}</td>`
        + `<td>${escapeHtml(investment)}</td>`
        + '<td>'
        + (
          `<span class="bot-control-activity-mode ${escapeHtml(mode)}">`
          + `${escapeHtml(mode)}`
          + '</span>'
        )
        + '</td>'
        + '<td>'
        + (
          `<span class="bot-control-activity-status ${
            escapeHtml(
              botControlActivityStatusClass(status)
            )
          }">`
          + `${escapeHtml(status)}`
          + '</span>'
        )
        + '</td>'
        + `<td>${escapeHtml(item.strategy_id || '—')}</td>`
        + '<td>'
        + (
          `<button type="button" `
          + `class="bot-control-activity-request-button `
          + `bot-control-activity-request" `
          + `data-bot-control-request="${escapeHtml(requestId)}" `
          + `title="${escapeHtml(requestId)}">`
          + `${escapeHtml(shortBotControlRequestId(requestId))}`
          + '</button>'
        )
        + '</td>'
        + '</tr>'
      );
    }).join('');
  }

  const footer = $('#botControlActivityFooter');

  if (footer) {
    if (!total) {
      footer.textContent = '0 activity records';

    } else {
      const first = offset + 1;

      const last = Math.min(
        offset + rows.length,
        total,
      );

      footer.textContent = (
        `Showing ${first}–${last} of `
        + `${total} Bot Control records`
      );
    }
  }

  const pageSize = $('#botControlActivityPageSize');

  if (pageSize) {
    pageSize.value = String(limit);
  }

  const pageCount = Math.max(
    1,
    Math.ceil(
      total / limit
    ),
  );

  const pageNumber = Math.min(
    pageCount,
    Math.floor(
      offset / limit
    ) + 1,
  );

  const pageLabel = $('#botControlActivityPage');

  if (pageLabel) {
    pageLabel.textContent = (
      `Page ${pageNumber} of ${pageCount}`
    );
  }

  const previous = $('#botControlActivityPrevious');

  if (previous) {
    previous.disabled = (
      !pagination.hasPrevious
    );
  }

  const next = $('#botControlActivityNext');

  if (next) {
    next.disabled = (
      !pagination.hasNext
    );
  }
}

async function loadBotControlActivity(
  {
    quiet = false,
    limit = null,
    offset = null,
  } = {},
) {
  if (!botControlAvailable()) {
    state.botControlActivity = [];

    state.botControlActivityPagination = {
      limit: 10,
      offset: 0,
      total: 0,
      hasPrevious: false,
      hasNext: false,
    };

    state.botControlAttention = [];
    state.botControlAttentionSummary = null;
    state.botStopPrepared = null;
    state.botStopRequestId = '';

    renderBotControlActivity();
    renderBotControlAttention();

    return;
  }

  const button = $('#refreshBotControlActivity');
  const errorBox = $('#botControlActivityError');

  const current = (
    state.botControlActivityPagination
    || {}
  );

  const requestedLimit = (
    [10, 25, 50].includes(
      Number(limit)
    )
      ? Number(limit)
      : (
        [10, 25, 50].includes(
          Number(current.limit)
        )
          ? Number(current.limit)
          : 10
      )
  );

  const requestedOffset = Math.max(
    0,
    (
      offset === null
      || offset === undefined
    )
      ? (
        Number(current.offset)
        || 0
      )
      : (
        Number(offset)
        || 0
      ),
  );

  if (button) {
    button.disabled = true;
    button.textContent = 'Loading…';
  }

  if (errorBox) {
    errorBox.textContent = '';
    errorBox.classList.add('hidden');
  }

  try {
    const query = (
      `?limit=${encodeURIComponent(requestedLimit)}`
      + `&offset=${encodeURIComponent(requestedOffset)}`
    );

    const result = await adminApi(
      `/api/bot-control/requests${query}`
    );

    state.botControlActivity = (
      result.items
      || []
    );

    state.botControlActivityPagination = {
      limit: Number(
        result.limit
        ?? requestedLimit
      ),

      offset: Number(
        result.offset
        ?? requestedOffset
      ),

      total: Number(
        result.total
        ?? result.count
        ?? 0
      ),

      hasPrevious: (
        result.has_previous === true
      ),

      hasNext: (
        result.has_next === true
      ),
    };

    renderBotControlActivity();

    await loadBotControlAttention({
      quiet: true,
    });

  } catch (error) {
    if (errorBox) {
      errorBox.textContent = (
        botControlErrorMessage(
          error
        )
      );

      errorBox.classList.remove(
        'hidden'
      );
    }

    if (!quiet) {
      showToast(
        botControlErrorMessage(error),
        true,
      );
    }

  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = 'Refresh activity';
    }

    renderBotControlActivity();
  }
}

function reconciliationLabel(value) {
  return String(
    value || 'unknown'
  )
    .replaceAll('_', ' ');
}

function renderBotControlReconciliationHistory(
  rows,
) {
  const element = $(
    '#botControlReconciliationHistory'
  );

  if (!element) return;

  if (!rows?.length) {
    element.innerHTML = (
      '<div class="empty-state">'
      + 'No reconciliation has been run.'
      + '</div>'
    );

    return;
  }

  element.innerHTML = rows.map(row => {
    const details = (
      row.details
      || {}
    );

    const retryAdvice = (
      details.retry_advice
      || 'manual_review'
    );

    return (
      '<div class="bot-control-reconciliation-card">'
      + '<div class="bot-control-reconciliation-head">'
      + `<strong>${escapeHtml(
          reconciliationLabel(row.outcome)
        )}</strong>`
      + `<span class="status-badge">${escapeHtml(
          row.confidence || 'inconclusive'
        )}</span>`
      + '</div>'
      + `<p>${escapeHtml(row.summary || '—')}</p>`
      + '<div class="bot-control-reconciliation-meta">'
      + `Gate status: ${escapeHtml(row.gate_status || '—')}`
      + ' · '
      + `Strategy: ${escapeHtml(row.strategy_id || '—')}`
      + ' · '
      + `Retry: ${escapeHtml(
          reconciliationLabel(retryAdvice)
        )}`
      + ' · '
      + `${escapeHtml(fmtDate(row.created_at))}`
      + '</div>'
      + '</div>'
    );
  }).join('');
}

function renderBotControlRequestDetail(
  detail,
) {
  state.botControlRequestDetail = detail;

  const request = (
    detail.request
    || {}
  );

  const response = (
    detail.response
    || {}
  );

  const simulation = Boolean(
    detail.status === 'simulated'
    || response.simulation
  );

  const requestStatus = String(
    detail.status || 'unknown'
  ).toLowerCase();

  const statusClass = (
    ['succeeded', 'completed'].includes(requestStatus)
      ? 'success'
      : ['rejected', 'failed'].includes(requestStatus)
        ? 'danger'
        : ['uncertain', 'blocked'].includes(requestStatus)
          ? 'warning'
          : ''
  );

  const lock = detail.operation_lock || null;

  const lockState = (
    lock?.state
      ? reconciliationLabel(lock.state)
      : 'No active lock'
  );

  const lockType = (
    lock?.lock_type
      ? reconciliationLabel(lock.lock_type)
      : ''
  );

  const gateHttp = (
    detail.gate_status_code !== null
    && detail.gate_status_code !== undefined
      ? String(detail.gate_status_code)
      : '—'
  );

  $('#botControlRequestSummary').innerHTML = `
    <section class="bot-control-request-card">
      <div class="bot-control-request-heading">
        <div>
          <span class="bot-control-request-label">
            Action
          </span>

          <strong>
            ${escapeHtml(
              botControlActionLabel(detail.action)
            )}
          </strong>
        </div>

        <span
          class="bot-control-request-status ${statusClass}"
        >
          ${escapeHtml(
            reconciliationLabel(detail.status)
          )}
        </span>
      </div>

      <div class="bot-control-request-id">
        <span>Request ID</span>
        <strong>
          ${escapeHtml(detail.request_id || '—')}
        </strong>
      </div>

      <div class="bot-control-request-identity">
        <div>
          <span>Account</span>
          <strong>
            ${escapeHtml(detail.account_id || '—')}
          </strong>
        </div>

        <div>
          <span>User</span>
          <strong>
            ${escapeHtml(detail.username || '—')}
          </strong>
        </div>
      </div>
    </section>

    <section class="bot-control-request-metrics">
      <div class="bot-control-request-metric">
        <span>Strategy ID</span>
        <strong>
          ${escapeHtml(detail.strategy_id || '—')}
        </strong>
      </div>

      <div class="bot-control-request-metric">
        <span>Gate HTTP</span>
        <strong>
          ${escapeHtml(gateHttp)}
        </strong>

        ${
          detail.gate_label
            ? (
              '<small>'
              + escapeHtml(detail.gate_label)
              + '</small>'
            )
            : ''
        }
      </div>

      <div class="bot-control-request-metric">
        <span>Operation lock</span>

        <strong class="bot-control-lock-badge">
          ${escapeHtml(lockState)}
        </strong>

        ${
          lockType
            ? (
              '<small>'
              + escapeHtml(lockType)
              + '</small>'
            )
            : ''
        }
      </div>
    </section>

    <section class="bot-control-request-times">
      <div>
        <span>Created</span>
        <strong>
          ${escapeHtml(fmtDate(detail.created_at))}
        </strong>
      </div>

      <div>
        <span>Completed</span>
        <strong>
          ${
            detail.completed_at
              ? escapeHtml(fmtDate(detail.completed_at))
              : '—'
          }
        </strong>
      </div>
    </section>
  `;

  const errorBox = $('#botControlRequestError');

  if (detail.error) {
    errorBox.textContent = detail.error;
    errorBox.classList.remove('hidden');
  } else {
    errorBox.textContent = '';
    errorBox.classList.add('hidden');
  }

  const notice = $(
    '#botControlReconcileNotice'
  );

  if (simulation) {
    notice.textContent = (
      'Simulation record. Reconciliation will be '
      + 'recorded as not applicable and will not '
      + 'query Gate, because the original write '
      + 'was never sent.'
    );
  } else if (
    detail.status === 'rejected'
  ) {
    notice.textContent = (
      'The original request contains an explicit '
      + 'Gate rejection. Reconciliation is local '
      + 'and no Gate write will occur.'
    );
  } else {
    notice.textContent = (
      'Read-only reconciliation uses the Monitor '
      + 'credential. It can query Gate strategy '
      + 'state but cannot Create or Stop a bot.'
    );
  }

  $('#botControlRequestJson').textContent =
    JSON.stringify(
      request,
      null,
      2,
    );

  $('#botControlResponseJson').textContent =
    JSON.stringify(
      response,
      null,
      2,
    );

  renderBotControlReconciliationHistory(
    detail.reconciliations
    || []
  );
}


function renderBotControlLockResolutions(rows) {
  const element = $(
    '#botControlLockResolutionHistory'
  );

  if (!element) return;

  if (!rows?.length) {
    element.innerHTML = (
      '<div class="empty-state">'
      + 'No lock-resolution decisions recorded.'
      + '</div>'
    );

    return;
  }

  element.innerHTML = rows.map(row => {
    return (
      '<div class="bot-control-reconciliation-card">'
      + '<div class="bot-control-reconciliation-head">'
      + `<strong>${escapeHtml(
          reconciliationLabel(row.decision)
        )}</strong>`
      + `<span class="status-badge">${escapeHtml(
          row.resolution_type || 'unknown'
        )}</span>`
      + '</div>'
      + `<p>${escapeHtml(row.reason || '—')}</p>`
      + '<div class="bot-control-reconciliation-meta">'
      + `By: ${escapeHtml(row.username || '—')}`
      + ' · '
      + `Reconciliation: ${escapeHtml(
          reconciliationLabel(
            row.reconciliation_outcome
          )
        )}`
      + ' · '
      + `Prior lock: ${escapeHtml(row.prior_state || '—')}`
      + ' · '
      + `${escapeHtml(fmtDate(row.created_at))}`
      + '</div>'
      + '</div>'
    );
  }).join('');
}


function updateManualLockReleaseButton() {
  const button = $(
    '#releaseBotControlLock'
  );

  if (!button) return;

  const reason = String(
    $('#manualLockReleaseReason')?.value
    || ''
  ).trim();

  const confirmation = String(
    $('#manualLockReleaseConfirm')?.value
    || ''
  );

  button.disabled = !(
    confirmation === 'RELEASE'
    && reason.length >= 10
  );
}


function renderManualLockRelease(detail) {
  const section = $(
    '#manualLockReleaseSection'
  );

  if (!section) return;

  const reconciliations = (
    detail.reconciliations
    || []
  );

  const latest = (
    reconciliations[0]
    || null
  );

  const lock = (
    detail.operation_lock
    || null
  );

  const eligible = Boolean(
    detail.status === 'uncertain'
    && lock
    && lock.state === 'held'
    && latest
    && latest.outcome !== 'stop_in_progress'
  );

  section.classList.toggle(
    'hidden',
    !eligible,
  );

  $('#manualLockReleaseReason').value = '';
  $('#manualLockReleaseConfirm').value = '';

  updateManualLockReleaseButton();
}


async function releaseCurrentBotControlLock() {
  const detail = (
    state.botControlRequestDetail
  );

  if (!detail?.request_id) {
    return;
  }

  const reason = String(
    $('#manualLockReleaseReason').value
    || ''
  ).trim();

  const confirmation = String(
    $('#manualLockReleaseConfirm').value
    || ''
  );

  if (
    confirmation !== 'RELEASE'
    || reason.length < 10
  ) {
    return;
  }

  const button = $(
    '#releaseBotControlLock'
  );

  button.disabled = true;
  button.textContent = 'Releasing…';

  try {
    const requestId = (
      detail.request_id
    );

    await adminApi(
      `/api/bot-control/requests/${
        encodeURIComponent(requestId)
      }/lock/release`,
      {
        method: 'POST',
        body: JSON.stringify({
          confirmation: 'RELEASE',
          reason,
        }),
      },
    );

    showToast(
      'Operation lock released and audit record created.'
    );

    const refreshed = await adminApi(
      `/api/bot-control/requests/${
        encodeURIComponent(requestId)
      }`
    );

    renderBotControlRequestDetail(
      refreshed
    );

    await loadBotControlActivity({
      quiet: true,
    });

  } catch (error) {
    showToast(
      botControlErrorMessage(error),
      true,
    );

  } finally {
    button.textContent = (
      'Release operation lock'
    );

    updateManualLockReleaseButton();
  }
}


async function openBotControlRequestDetail(
  requestId,
) {
  if (!requestId) return;

  try {
    const detail = await adminApi(
      `/api/bot-control/requests/${
        encodeURIComponent(requestId)
      }`
    );

    renderBotControlRequestDetail(
      detail
    );

    const dialog = $(
      '#botControlRequestDialog'
    );

    /*
     * Always present a newly opened request from the
     * top. Browsers preserve <dialog> scroll position
     * between openings, which can otherwise hide the
     * Request ID / status summary from the operator.
     */
    dialog.scrollTop = 0;

    const content = dialog.querySelector(
      '.bot-control-request-content'
    );

    if (content) {
      content.scrollTop = 0;
    }

    if (!dialog.open) {
      dialog.showModal();
    }

    /*
     * Reset again after showModal() in case the browser
     * restores the previous scroll position while
     * displaying the dialog.
     */
    dialog.scrollTop = 0;

    if (content) {
      content.scrollTop = 0;
    }

  } catch (error) {
    showToast(
      botControlErrorMessage(error),
      true,
    );
  }
}

async function reconcileCurrentBotControlRequest() {
  const detail = (
    state.botControlRequestDetail
  );

  if (!detail?.request_id) {
    return;
  }

  const button = $(
    '#reconcileBotControlRequest'
  );

  button.disabled = true;
  button.textContent = 'Reconciling…';

  try {
    const requestId = (
      detail.request_id
    );

    const result = await adminApi(
      `/api/bot-control/requests/${
        encodeURIComponent(requestId)
      }/reconcile`,
      {
        method: 'POST',
      },
    );

    const lockDecision = (
      result.lock_decision?.decision
      || 'no lock'
    );

    showToast(
      `Reconciliation: ${
        reconciliationLabel(
          result.reconciliation?.outcome
        )
      } · lock: ${
        reconciliationLabel(
          lockDecision
        )
      }`
    );

    const refreshed = await adminApi(
      `/api/bot-control/requests/${
        encodeURIComponent(requestId)
      }`
    );

    renderBotControlRequestDetail(
      refreshed
    );

    await loadBotControlActivity({
      quiet: true,
    });

  } catch (error) {
    showToast(
      botControlErrorMessage(error),
      true,
    );

  } finally {
    button.disabled = false;
    button.textContent = (
      'Reconcile with Gate'
    );
  }
}


function botControlAvailable() {
  return Boolean(
    state.adminUser
    && state.adminAuthorization
    && state.botControlCapabilities?.modes?.bot_control
  );
}

function botCreationEnabled() {
  return Boolean(
    state.health?.allow_bot_create
  );
}

function botCreationSimulation() {
  return Boolean(
    state.health?.bot_create_simulation
  );
}

function botCreationLive() {
  return Boolean(
    botCreationEnabled()
    && !botCreationSimulation()
  );
}

function botCreationMode() {
  if (botCreationLive()) {
    return 'live';
  }

  if (botCreationSimulation()) {
    return 'simulation';
  }

  return 'disabled';
}

function botCreationRequiredConfirmation() {
  return botCreationLive()
    ? 'LIVE CREATE'
    : 'CREATE';
}


function botCreationAvailable() {
  return (
    botCreationEnabled()
    || botCreationSimulation()
  );
}


function botStopEnabled() {
  return Boolean(
    state.health?.allow_bot_stop
  );
}

function botStopSimulation() {
  return Boolean(
    state.health?.bot_stop_simulation
  );
}

function botStopAvailable() {
  return (
    botStopEnabled()
    || botStopSimulation()
  );
}

function botStopLive() {
  return Boolean(
    botStopEnabled()
    && !botStopSimulation()
  );
}

function botStopMode() {
  if (botStopLive()) {
    return 'live';
  }

  if (botStopSimulation()) {
    return 'simulation';
  }

  return 'disabled';
}

function botStopRequiredConfirmation() {
  return botStopLive()
    ? 'LIVE STOP'
    : 'STOP';
}

async function refreshBotControlRuntimeHealth() {
  state.health = await api('/api/health');

  if (state.currentBotData?.bot) {
    updateBotAdminControls(
      state.currentBotData.bot
    );
  }

  renderBotControlAccess();

  return state.health;
}


function botControlErrorMessage(error) {
  const detail = error?.payload?.detail;

  if (
    detail
    && typeof detail === 'object'
    && detail.message
  ) {
    let message = String(
      detail.message
    );

    const retry = Number(
      detail.retry_after_seconds
      || 0
    );

    if (
      error?.status === 429
      && retry > 0
    ) {
      let retryText;

      if (retry < 60) {
        retryText = `${Math.ceil(retry)}s`;

      } else if (retry < 3600) {
        retryText = (
          `${Math.ceil(retry / 60)}m`
        );

      } else {
        retryText = (
          `${Math.ceil(retry / 3600)}h`
        );
      }

      message += (
        `. Try again in ${retryText}.`
      );
    }

    return message;
  }

  return (
    error?.message
    || 'Bot Control request failed.'
  );
}

function clearBotControlSession() {
  state.botControlCapabilities = null;
  state.botControlPrepared = null;
  state.botControlDraft = null;
  state.botControlRequestId = '';
  state.botControlActivity = [];
  state.botControlActivityPagination = {
    limit: 10,
    offset: 0,
    total: 0,
    hasPrevious: false,
    hasNext: false,
  };
  state.botControlRequestDetail = null;

  $('#spotGridReview')?.classList.add('hidden');
  $('#spotGridReviewEmpty')?.classList.remove('hidden');

  const stopDialog = $('#stopBotConfirmDialog');

  if (stopDialog?.open) {
    stopDialog.close();
  }

  const requestDialog = $('#botControlRequestDialog');

  if (requestDialog?.open) {
    requestDialog.close();
  }

  const dialog = $('#spotGridConfirmDialog');

  if (dialog?.open) {
    dialog.close();
  }

  renderBotControlActivity();
  renderBotControlAccess();
}

async function loadBotControlCapabilities() {
  if (
    !state.adminUser
    || !state.adminAuthorization
  ) {
    state.botControlCapabilities = null;
    renderBotControlAccess();
    return;
  }

  try {
    state.botControlCapabilities = await adminApi(
      '/api/auth/capabilities'
    );
  } catch (error) {
    state.botControlCapabilities = null;

    showToast(
      botControlErrorMessage(error),
      true,
    );
  }

  renderBotControlAccess();

  if (botControlAvailable()) {
    await loadBotControlActivity({ quiet: true });
  }

}

function botControlAccounts() {
  return (
    state.botControlCapabilities?.accounts
    || []
  ).filter(
    account => account.bot_control
  );
}


function botControlAccountCapability(accountId) {
  const normalized = String(
    accountId || ''
  )
    .trim()
    .toLowerCase();

  if (!normalized) {
    return null;
  }

  return (
    state.botControlCapabilities?.accounts
    || []
  ).find(
    account => (
      String(
        account.account_id || ''
      )
        .trim()
        .toLowerCase()
      === normalized
    )
  ) || null;
}


function botControlAccountLiveEnabled(accountId) {
  return (
    botControlAccountCapability(
      accountId
    )?.bot_control_live
    === true
  );
}


function selectedBotControlAccountId() {
  return String(
    $('#spotGridAccount')?.value
    || state.botControlDraft?.account_id
    || ''
  )
    .trim()
    .toLowerCase();
}


function formatBotControlSidebarUtc(value) {
  if (!value) {
    return '';
  }

  const date = new Date(value);

  if (Number.isNaN(date.valueOf())) {
    return '';
  }

  const pad = number => String(
    number
  ).padStart(
    2,
    '0',
  );

  return (
    `${pad(date.getUTCHours())}:`
    + `${pad(date.getUTCMinutes())} UTC`
  );
}


function renderSidebarSyncScope(
  latestOverride = null,
) {
  const target = $('#lastSyncSidebar');

  if (!target) {
    return;
  }

  if (state.activeTab === 'bot-control') {
    const accountId = (
      selectedBotControlAccountId()
    );

    const account = (
      state.overview?.accounts
      || []
    ).find(
      item => (
        String(item.id || '').toLowerCase()
        === accountId
      )
    );

    const accountName = (
      account?.name
      || accountId
      || 'Bot Control'
    );

    const syncTime = (
      formatBotControlSidebarUtc(
        account?.last_success_at
      )
    );

    target.textContent = syncTime
      ? `${accountName} · ${syncTime}`
      : `${accountName} · no sync yet`;

    return;
  }

  const latest = (
    latestOverride
    || state.syncRuns?.[0]
    || null
  );

  const accountLabel = (
    state.selectedAccount
      ? (
        state.overview?.selected_account?.name
        || state.selectedAccount
      )
      : 'All accounts'
  );

  target.textContent = latest
    ? (
      `${accountLabel} · `
      + `${fmtDate(
        latest.finished_at
        || latest.started_at
      )}`
    )
    : `${accountLabel} · no sync yet`;
}


function botCreationSubmissionAvailableForAccount(
  accountId,
) {
  /*
   * Simulation deliberately performs no Gate write,
   * so the live-account allowlist is irrelevant to
   * simulation mode.
   */
  if (botCreationSimulation()) {
    return true;
  }

  return Boolean(
    botCreationLive()
    && botControlAccountLiveEnabled(
      accountId
    )
  );
}



function botStopSubmissionAvailableForAccount(
  accountId,
) {
  /*
   * Stop simulation performs no Gate mutation and
   * therefore does not require live-account eligibility.
   */
  if (botStopSimulation()) {
    return true;
  }

  return Boolean(
    botStopLive()
    && botControlAccountLiveEnabled(
      accountId
    )
  );
}


function renderBotControlCreateState() {
  const badge = $('#botControlCreateState');
  const detail = $('#botControlCreateStateDetail');

  if (!badge) {
    return;
  }

  const simulation = botCreationSimulation();

  const liveGloballyEnabled =
    botCreationLive();

  const liveForAccount = Boolean(
    liveGloballyEnabled
    && botControlAccountLiveEnabled(
      selectedBotControlAccountId()
    )
  );

  if (simulation) {
    badge.textContent = 'SIMULATION';

    if (detail) {
      detail.textContent = 'No Gate write';
    }

  } else if (liveForAccount) {
    badge.textContent = 'LIVE';

    if (detail) {
      detail.textContent = 'Armed';
    }

  } else if (liveGloballyEnabled) {
    badge.textContent = 'REVIEW ONLY';

    if (detail) {
      detail.textContent = (
        'Creation not armed for this account'
      );
    }

  } else {
    badge.textContent = 'REVIEW ONLY';

    if (detail) {
      detail.textContent = 'Creation disabled';
    }
  }

  badge.className = (
    `status-badge ${
      liveForAccount
        ? 'warning'
        : simulation
          ? 'running'
          : 'disabled'
    }`
  );
}

function renderBotControlAccess() {
  const nav = $('#botControlNavItem');

  if (!nav) return;

  const available = botControlAvailable();

  nav.classList.toggle(
    'hidden',
    !available,
  );

  nav.setAttribute(
    'aria-hidden',
    String(!available),
  );

  nav.tabIndex = available ? 0 : -1;

  const select = $('#spotGridAccount');
  const accountField = $('#spotGridAccountField');
  const accountChip = $('#spotGridAccountChip');

  if (select) {
    const accounts = botControlAccounts();
    const previous = select.value;

    select.innerHTML = accounts
      .map(account => (
        `<option value="${escapeHtml(account.account_id)}">`
        + `${escapeHtml(account.account_name || account.account_id)}`
        + `</option>`
      ))
      .join('');

    const ids = accounts.map(
      account => account.account_id
    );

    let target = '';

    if (
      state.selectedAccount
      && ids.includes(state.selectedAccount)
    ) {
      target = state.selectedAccount;

    } else if (
      previous
      && ids.includes(previous)
    ) {
      target = previous;

    } else {
      target = ids[0] || '';
    }

    select.value = target;

    const singleAccount = (
      accounts.length === 1
    );

    accountField?.classList.toggle(
      'hidden',
      singleAccount,
    );

    accountField?.setAttribute(
      'aria-hidden',
      String(singleAccount),
    );

    if (accountChip) {
      const account = (
        singleAccount
          ? accounts[0]
          : null
      );

      accountChip.textContent = (
        account
          ? (
            account.account_name
            || account.account_id
          )
          : '—'
      );

      accountChip.classList.toggle(
        'hidden',
        !singleAccount,
      );

      accountChip.setAttribute(
        'aria-hidden',
        String(!singleAccount),
      );
    }
  }

  renderBotControlCreateState();

  updateSpotGridConfirmButton();

  renderSidebarSyncScope();

  if (
    state.activeTab === 'bot-control'
    && !available
  ) {
    switchTab('overview');
  }
}


function resetSpotGridForm() {
  const form = $('#spotGridForm');

  if (!form) {
    return;
  }

  /*
   * Preserve Bot Control account scope while resetting
   * all strategy parameters to their HTML defaults.
   */
  const accountId = (
    selectedBotControlAccountId()
  );

  form.reset();

  const accountSelect = $('#spotGridAccount');

  if (
    accountSelect
    && accountId
    && Array.from(
      accountSelect.options
    ).some(
      option => option.value === accountId
    )
  ) {
    accountSelect.value = accountId;
  }

  form.querySelector(
    '.bot-control-advanced'
  )?.removeAttribute(
    'open'
  );

  state.botControlPrepared = null;
  state.botControlDraft = null;
  state.botControlRequestId = '';

  setSpotGridFormError('');

  $('#spotGridReview')?.classList.add(
    'hidden'
  );

  const empty = $('#spotGridReviewEmpty');

  if (empty) {
    empty.innerHTML = (
      'Enter the strategy parameters and choose '
      + '<strong>Review Spot Grid</strong>.'
    );

    empty.classList.remove(
      'hidden'
    );
  }

  const reviewStatus = $(
    '#spotGridReviewStatus'
  );

  if (reviewStatus) {
    reviewStatus.innerHTML = '';
  }

  const reviewMetrics = $(
    '#spotGridReviewMetrics'
  );

  if (reviewMetrics) {
    reviewMetrics.innerHTML = '';
  }

  const validation = $(
    '#spotGridValidationMessages'
  );

  if (validation) {
    validation.innerHTML = '';
  }

  const payload = $(
    '#spotGridPayloadPreview'
  );

  if (payload) {
    payload.textContent = '';
  }

  const createResult = $(
    '#spotGridCreateResult'
  );

  if (createResult) {
    createResult.textContent = '';
    createResult.classList.add(
      'hidden'
    );
  }

  const confirmationButton = $(
    '#openSpotGridConfirmation'
  );

  if (confirmationButton) {
    confirmationButton.disabled = true;
  }

  const confirmationText = $(
    '#spotGridConfirmText'
  );

  if (confirmationText) {
    confirmationText.value = '';
  }

  const confirmationError = $(
    '#spotGridConfirmError'
  );

  if (confirmationError) {
    confirmationError.textContent = '';
    confirmationError.classList.add(
      'hidden'
    );
  }

  const dialog = $('#spotGridConfirmDialog');

  if (dialog?.open) {
    dialog.close();
  }

  renderBotControlCreateState();
  updateSpotGridConfirmButton();
}

function invalidateSpotGridReview() {
  if (!state.botControlPrepared) return;

  state.botControlPrepared = null;
  state.botControlDraft = null;
  state.botControlRequestId = '';

  $('#spotGridReview')?.classList.add(
    'hidden'
  );

  const empty = $('#spotGridReviewEmpty');

  if (empty) {
    empty.innerHTML = (
      'Parameters changed. Choose '
      + '<strong>Review Spot Grid</strong> again.'
    );

    empty.classList.remove('hidden');
  }
}

function setSpotGridFormError(message = '') {
  const element = $('#spotGridFormError');

  if (!element) return;

  element.textContent = message;
  element.classList.toggle(
    'hidden',
    !message,
  );
}

function optionalFormValue(form, name) {
  const value = String(
    form.get(name) || ''
  ).trim();

  return value || null;
}

function spotGridDraftFromForm(formElement) {
  const form = new FormData(formElement);

  return {
    account_id: String(
      form.get('account_id') || ''
    ).trim(),

    market: String(
      form.get('market') || ''
    ).trim().toUpperCase(),

    money: String(
      form.get('money') || ''
    ).trim(),

    low_price: String(
      form.get('low_price') || ''
    ).trim(),

    high_price: String(
      form.get('high_price') || ''
    ).trim(),

    grid_num: Number(
      form.get('grid_num')
    ),

    price_type: Number(
      form.get('price_type')
    ),

    trigger_price: optionalFormValue(
      form,
      'trigger_price'
    ),

    stop_profit: optionalFormValue(
      form,
      'stop_profit'
    ),

    stop_loss: optionalFormValue(
      form,
      'stop_loss'
    ),
  };
}

async function prepareSpotGrid(event) {
  event.preventDefault();

  if (!botControlAvailable()) {
    openAdminDialog();
    return;
  }

  const formElement = event.currentTarget;
  const button = $('#prepareSpotGridButton');

  setSpotGridFormError('');

  state.botControlPrepared = null;
  state.botControlDraft = null;
  state.botControlRequestId = '';

  const draft = spotGridDraftFromForm(
    formElement
  );

  button.disabled = true;
  button.textContent = 'Checking Gate…';

  try {
    const result = await adminApi(
      '/api/bot-control/spot-grid/prepare',
      {
        method: 'POST',
        body: JSON.stringify(draft),
      },
    );

    state.botControlDraft = draft;
    state.botControlPrepared = result;

    renderSpotGridReview();
  } catch (error) {
    setSpotGridFormError(
      botControlErrorMessage(error)
    );
  } finally {
    button.disabled = false;
    button.textContent = 'Review Spot Grid';
  }
}

function reviewMetric(
  label,
  value,
) {
  return (
    '<div class="bot-control-review-item">'
    + `<span>${escapeHtml(label)}</span>`
    + `<strong>${escapeHtml(value ?? '—')}</strong>`
    + '</div>'
  );
}

function renderSpotGridReview() {
  const prepared = state.botControlPrepared;

  if (!prepared) return;

  $('#spotGridReviewEmpty')?.classList.add(
    'hidden'
  );

  $('#spotGridReview')?.classList.remove(
    'hidden'
  );

  const market = prepared.market || {};
  const snapshot = (
    prepared.market_snapshot
    || {}
  );
  const balance = prepared.balance || {};
  const grid = prepared.grid || {};

  const ready = Boolean(
    prepared.can_create
  );

  $('#spotGridReviewStatus').innerHTML = (
    `<div class="bot-control-message ${ready ? 'success' : 'error'}">`
    + (
      ready
        ? (
          'Preflight passed. No Gate write was performed. '
          + 'Review the values below before final confirmation.'
        )
        : (
          'Preflight failed. No Gate write was performed.'
        )
    )
    + '</div>'
  );

  $('#spotGridReviewMetrics').innerHTML = [
    reviewMetric(
      'Account',
      prepared.account?.name
      || prepared.account?.id,
    ),

    reviewMetric(
      'Market',
      market.id,
    ),

    reviewMetric(
      'Current price',
      snapshot.last
        ? `${snapshot.last} ${market.quote || ''}`
        : '—',
    ),

    reviewMetric(
      'Investment',
      `${balance.requested_investment || '—'} ${market.quote || ''}`,
    ),

    reviewMetric(
      'Available balance',
      `${balance.available || '—'} ${balance.currency || ''}`,
    ),

    reviewMetric(
      'Remaining balance',
      balance.remaining_after_investment !== null
      && balance.remaining_after_investment !== undefined
        ? (
          `${balance.remaining_after_investment} `
          + `${balance.currency || ''}`
        )
        : '—',
    ),

    reviewMetric(
      'Price range',
      (
        `${state.botControlDraft?.low_price || '—'}`
        + ' → '
        + `${state.botControlDraft?.high_price || '—'}`
        + ` ${market.quote || ''}`
      ),
    ),

    reviewMetric(
      'Number of grids',
      String(
        state.botControlDraft?.grid_num
        ?? '—'
      ),
    ),

    reviewMetric(
      'Grid type',
      grid.price_type || '—',
    ),

    reviewMetric(
      'Grid spacing',
      grid.price_type === 'geometric'
        ? (
          grid.geometric_step_pct
            ? `${grid.geometric_step_pct}%`
            : '—'
        )
        : (
          grid.arithmetic_price_step
          || '—'
        ),
    ),

    reviewMetric(
      'Approx. quote / grid',
      grid.approx_quote_per_grid
        ? (
          `${grid.approx_quote_per_grid} `
          + `${market.quote || ''}`
        )
        : '—',
    ),

    reviewMetric(
      'Gate market status',
      market.trade_status || '—',
    ),
  ].join('');

  const errors = prepared.errors || [];
  const warnings = prepared.warnings || [];

  const messages = [];

  errors.forEach(message => {
    messages.push(
      '<div class="bot-control-message error">'
      + `${escapeHtml(message)}`
      + '</div>'
    );
  });

  warnings.forEach(message => {
    messages.push(
      '<div class="bot-control-message warning">'
      + `${escapeHtml(message)}`
      + '</div>'
    );
  });

  if (
    !errors.length
    && !warnings.length
  ) {
    messages.push(
      '<div class="bot-control-message success">'
      + 'No validation warnings.'
      + '</div>'
    );
  }

  $('#spotGridValidationMessages').innerHTML =
    messages.join('');

  $('#spotGridPayloadPreview').textContent =
    JSON.stringify(
      prepared.gate_create_payload_preview,
      null,
      2,
    );

  $('#openSpotGridConfirmation').disabled = (
    !ready
    || !botCreationSubmissionAvailableForAccount(
      state.botControlDraft?.account_id
      || selectedBotControlAccountId()
    )
  );

  $('#spotGridCreateResult').classList.add(
    'hidden'
  );
}

function confirmRow(label, value) {
  return (
    '<div class="bot-control-confirm-row">'
    + `<span>${escapeHtml(label)}</span>`
    + `<strong>${escapeHtml(value ?? '—')}</strong>`
    + '</div>'
  );
}

function openSpotGridConfirmation() {
  const prepared = state.botControlPrepared;
  const draft = state.botControlDraft;

  if (
    !prepared?.can_create
    || !draft
  ) {
    return;
  }

  const accountId = String(
    draft.account_id || ''
  )
    .trim()
    .toLowerCase();

  if (
    !botCreationSubmissionAvailableForAccount(
      accountId
    )
  ) {
    showToast(
      botCreationLive()
        ? (
          'LIVE Bot creation is not enabled '
          + 'for this account.'
        )
        : (
          'Bot creation is currently disabled '
          + 'on the server.'
        ),
      true,
    );

    return;
  }

  const market = prepared.market || {};
  const balance = prepared.balance || {};

  const optionalRows = [];

  if (draft.trigger_price) {
    optionalRows.push(
      confirmRow(
        'Trigger price',
        `${draft.trigger_price} ${market.quote || ''}`,
      ),
    );
  }

  if (draft.stop_profit) {
    optionalRows.push(
      confirmRow(
        'Take-profit price',
        `${draft.stop_profit} ${market.quote || ''}`,
      ),
    );
  }

  if (draft.stop_loss) {
    optionalRows.push(
      confirmRow(
        'Stop-loss price',
        `${draft.stop_loss} ${market.quote || ''}`,
      ),
    );
  }

  $('#spotGridConfirmSummary').innerHTML = [
    confirmRow(
      'Account',
      prepared.account?.name
      || prepared.account?.id,
    ),

    confirmRow(
      'Market',
      market.id,
    ),

    confirmRow(
      'Current market price',
      prepared.market_snapshot?.last
        ? (
          `${prepared.market_snapshot.last} `
          + `${market.quote || ''}`
        )
        : '—',
    ),

    confirmRow(
      'Investment',
      `${draft.money} ${market.quote || ''}`,
    ),

    confirmRow(
      'Available before creation',
      `${balance.available || '—'} ${balance.currency || ''}`,
    ),

    confirmRow(
      'Remaining after investment',
      balance.remaining_after_investment !== null
      && balance.remaining_after_investment !== undefined
        ? (
          `${balance.remaining_after_investment} `
          + `${balance.currency || ''}`
        )
        : '—',
    ),

    confirmRow(
      'Price range',
      (
        `${draft.low_price} → ${draft.high_price} `
        + `${market.quote || ''}`
      ),
    ),

    confirmRow(
      'Number of grids',
      String(draft.grid_num),
    ),

    confirmRow(
      'Grid type',
      Number(draft.price_type) === 0
        ? 'Arithmetic'
        : 'Geometric',
    ),

    ...optionalRows,
  ].join('');

  const simulation = botCreationSimulation();

  const liveGloballyEnabled =
    botCreationLive();

  const live = Boolean(
    liveGloballyEnabled
    && botControlAccountLiveEnabled(
      accountId
    )
  );

  const notice = $('#botCreateDisabledNotice');

  notice.classList.toggle(
    'enabled',
    live,
  );

  notice.textContent = live
    ? (
      'LIVE Bot creation is ENABLED. Submitting this '
      + 'confirmation can create a real Gate Spot Grid.'
    )
    : simulation
      ? (
        'SIMULATION MODE. This will exercise the complete '
        + 'Bot Control workflow and audit trail, but NO '
        + 'request will be sent to Gate to create a bot.'
      )
      : liveGloballyEnabled
        ? (
          'LIVE Bot creation is not enabled for this '
          + 'account. No Gate write can be submitted '
          + 'for this account.'
        )
        : (
          'Bot creation is currently disabled on the '
          + 'server. No Gate write can be submitted.'
        );

  const requiredConfirmation =
    botCreationRequiredConfirmation();

  $('#spotGridRequiredConfirmation').textContent =
    requiredConfirmation;

  $('#spotGridConfirmText').placeholder =
    requiredConfirmation;

  $('#spotGridConfirmText').value = '';
  $('#spotGridConfirmError').textContent = '';
  $('#spotGridConfirmError').classList.add(
    'hidden'
  );

  updateSpotGridConfirmButton();

  const dialog = $('#spotGridConfirmDialog');

  if (!dialog.open) {
    dialog.showModal();
  }

  setTimeout(
    () => $('#spotGridConfirmText')?.focus(),
    0,
  );
}

function updateSpotGridConfirmButton() {
  const button = $('#confirmSpotGridCreate');

  if (!button) return;

  button.disabled = !(
    botCreationSubmissionAvailableForAccount(
      state.botControlDraft?.account_id
      || selectedBotControlAccountId()
    )
    && state.botControlPrepared?.can_create
    && $('#spotGridConfirmText')?.value
      === botCreationRequiredConfirmation()
  );

  button.textContent = botCreationSimulation()
    && !botCreationEnabled()
      ? 'Simulate Spot Grid'
      : 'Create Spot Grid';
}

function generateBotControlRequestId(prefix = 'bot-control') {
  if (
    window.crypto
    && typeof window.crypto.randomUUID === 'function'
  ) {
    return (
      `${prefix}-${window.crypto.randomUUID()}`
    );
  }

  return (
    `${prefix}-${Date.now()}-`
    + Math.random().toString(16).slice(2)
  );
}

async function submitSpotGridCreate() {
  if (
    !state.botControlPrepared?.can_create
    || !state.botControlDraft
  ) {
    return;
  }

  const accountId = String(
    state.botControlDraft.account_id || ''
  )
    .trim()
    .toLowerCase();

  if (
    !botCreationSubmissionAvailableForAccount(
      accountId
    )
  ) {
    return;
  }

  const button =
    $('#confirmSpotGridCreate');

  const errorBox =
    $('#spotGridConfirmError');

  /*
   * Re-read server safety state immediately before
   * submission. An already-open CREATE dialog must
   * never retain stale live/simulation state.
   */
  const modeBefore =
    botCreationMode();

  const accountLiveBefore =
    botCreationSubmissionAvailableForAccount(
      accountId
    );

  try {
    await refreshBotControlRuntimeHealth();

    /*
     * Health contains the global Bot Control arm.
     * Auth capabilities contain the account-specific
     * live policy. Re-read BOTH before any Create POST.
     */
    state.botControlCapabilities = await adminApi(
      '/api/auth/capabilities'
    );

    renderBotControlAccess();

  } catch (error) {
    errorBox.textContent = (
      'Unable to refresh Bot Control safety state. '
      + 'No Create request was submitted.'
    );

    errorBox.classList.remove(
      'hidden'
    );

    return;
  }

  const modeAfter =
    botCreationMode();

  const accountLiveAfter =
    botCreationSubmissionAvailableForAccount(
      accountId
    );

  if (
    modeAfter !== modeBefore
    || accountLiveAfter !== accountLiveBefore
    || !accountLiveAfter
  ) {
    /*
     * Stronger than trying to mutate an already-open
     * confirmation: close it and force the operator to
     * prepare/review again.
     */
    $('#spotGridConfirmDialog').close();

    showToast(
      'Bot Control mode changed on the server. '
      + 'No Create request was submitted. '
      + 'Review and open confirmation again.',
      true,
    );

    return;
  }

  if (
    !botCreationSubmissionAvailableForAccount(
      accountId
    )
  ) {
    return;
  }

  const requiredConfirmation =
    botCreationRequiredConfirmation();

  if (
    $('#spotGridConfirmText').value
    !== requiredConfirmation
  ) {
    return;
  }

  if (!state.botControlRequestId) {
    state.botControlRequestId =
      generateBotControlRequestId(
        'spot-grid'
      );
  }

  const requestId =
    state.botControlRequestId;

  const payload = {
    ...state.botControlDraft,
    request_id: requestId,
    confirmation: requiredConfirmation,
  };

  button.disabled = true;

  button.textContent = (
    botCreationLive()
      ? 'Submitting to Gate…'
      : 'Simulating…'
  );

  errorBox.textContent = '';

  errorBox.classList.add(
    'hidden'
  );

  let result;

  /*
   * ONLY the actual Create mutation belongs in this
   * try/catch.
   *
   * Once adminApi() returns successfully, later UI
   * refresh failures must never make the operator
   * believe the Gate submission itself failed.
   */
  try {
    result = await adminApi(
      '/api/bot-control/spot-grid/create',
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    );

  } catch (error) {
    /*
     * Keep the SAME request ID. The backend audit and
     * idempotency layer decides whether replay is safe.
     */
    errorBox.textContent =
      botControlErrorMessage(error);

    errorBox.classList.remove(
      'hidden'
    );

    updateSpotGridConfirmButton();
    return;
  }

  const simulated = Boolean(
    result.simulation
    || result.status === 'simulated'
  );

  $('#spotGridConfirmDialog').close();

  /*
   * Persist the raw result immediately.
   */
  $('#apiInspector').textContent =
    JSON.stringify(
      result,
      null,
      2,
    );

  const resultBox =
    $('#spotGridCreateResult');

  resultBox.innerHTML = (
    `<strong>${
      simulated
        ? (
          'Simulation completed. '
          + 'No Gate write performed.'
        )
        : 'Gate submission completed.'
    }</strong>`
    + '<br>'
    + `Request ID: ${
      escapeHtml(requestId)
    }`
    + '<br>'
    + (
      simulated
        ? 'Strategy ID: none · simulation only'
        : (
          `Strategy ID: ${
            escapeHtml(
              result.strategy?.strategy_id
              || result.gate?.data?.strategy_id
              || 'pending'
            )
          }`
        )
    )
  );

  resultBox.classList.remove(
    'hidden'
  );

  showToast(
    simulated
      ? (
        'Spot Grid simulation completed. '
        + `Request ${requestId}.`
      )
      : (
        'Spot Grid creation submitted to Gate. '
        + `Request ${requestId}.`
      )
  );

  /*
   * Open the persistent audit record immediately.
   * The dialog now also resets its scroll position to
   * the top when opened.
   */
  await openBotControlRequestDetail(
    requestId
  );

  /*
   * Everything below is secondary refresh work.
   * Failure here must NOT be reported as Create
   * submission failure.
   */
  try {
    await loadBotControlActivity({
      quiet: true,
    });

  } catch (error) {
    showToast(
      'Create was submitted successfully, but Bot '
      + 'Control Activity could not be refreshed. '
      + `Request ${requestId}.`,
      true,
    );
  }

  try {
    await loadCore();

  } catch (error) {
    showToast(
      'Create was submitted successfully, but the '
      + 'dashboard could not be refreshed. '
      + `Request ${requestId}.`,
      true,
    );
  }

  updateSpotGridConfirmButton();
}


function treasuryErrorMessage(error) {
  const detail = error?.payload?.detail;

  if (
    detail
    && typeof detail === 'object'
    && detail.message
  ) {
    let message = String(detail.message);

    const retry = Number(
      detail.retry_after_seconds || 0
    );

    if (
      error?.status === 429
      && retry > 0
    ) {
      const retryText = (
        retry < 60
          ? `${Math.ceil(retry)}s`
          : retry < 3600
            ? `${Math.ceil(retry / 60)}m`
            : `${Math.ceil(retry / 3600)}h`
      );

      message += `. Try again in ${retryText}.`;
    }

    return message;
  }

  if (typeof detail === 'string' && detail) {
    return detail;
  }

  return (
    error?.message
    || 'Treasury request failed.'
  );
}


function treasuryStatusClass(value) {
  const status = String(
    value || 'unknown'
  ).toLowerCase();

  if (status === 'success') {
    return 'success';
  }

  if (
    status === 'failed'
    || status === 'rejected'
    || status === 'blocked'
  ) {
    return status;
  }

  if (
    status === 'pending'
    || status === 'uncertain'
    || status === 'attention'
    || status === 'submitting'
    || status === 'validating'
  ) {
    return status;
  }

  return '';
}


function treasuryOperationType(item) {
  const operation = String(
    item?.request?.operation || ''
  )
    .trim()
    .toLowerCase();

  if (operation === 'subaccount_to_main') {
    return 'Internal transfer';
  }

  if (
    operation === 'main_to_subaccount'
    || operation === 'return_to_subaccount'
    || operation === 'return_transfer'
  ) {
    return 'Return transfer';
  }

  if (
    operation === 'withdrawal'
    || operation === 'external_withdrawal'
  ) {
    return 'Withdrawal';
  }

  /*
   * Legacy Treasury simulations predate the explicit
   * request.operation field. Their persisted direction
   * still identifies the transfer safely.
   */
  const direction = String(
    item?.direction || ''
  )
    .trim()
    .toLowerCase();

  if (direction === 'from') {
    return 'Internal transfer';
  }

  if (direction === 'to') {
    return 'Return transfer';
  }

  if (operation) {
    return reconciliationLabel(operation);
  }

  return 'Treasury operation';
}


function treasuryAmount(value, currency = '') {
  if (
    value === null
    || value === undefined
    || value === ''
  ) {
    return '—';
  }

  let rendered = String(value);

  if (rendered.includes('.')) {
    rendered = rendered
      .replace(/0+$/, '')
      .replace(/\.$/, '');
  }

  return (
    `${rendered}${currency ? ` ${currency}` : ''}`
  );
}


function shortTreasuryRequestId(value) {
  const id = String(value || '');

  if (id.length <= 22) {
    return id || '—';
  }

  return `${id.slice(0, 12)}…${id.slice(-7)}`;
}


function shortTreasuryGateId(value) {
  const id = String(value || '');

  if (!id) return '—';

  if (id.length <= 18) {
    return id;
  }

  return `${id.slice(0, 9)}…${id.slice(-6)}`;
}


function renderTreasurySafety() {
  const health = state.health || {};

  const configured = Boolean(
    health.treasury_configured
  );

  const transfersEnabled = Boolean(
    health.treasury_transfers_enabled
  );

  const withdrawalsEnabled = Boolean(
    health.treasury_withdrawals_enabled
  );

  const phase = String(
    health.treasury_phase || '—'
  );

  const badge = $('#treasurySafetyBadge');

  if (badge) {
    badge.textContent = transfersEnabled
      ? 'LIVE TRANSFERS ENABLED'
      : 'LIVE TRANSFERS DISABLED';

    badge.classList.toggle(
      'safe',
      !transfersEnabled
    );

    badge.classList.toggle(
      'danger',
      transfersEnabled
    );
  }

  if ($('#treasuryConfigured')) {
    $('#treasuryConfigured').textContent = (
      configured ? 'Configured' : 'Unavailable'
    );
  }

  if ($('#treasuryPhase')) {
    $('#treasuryPhase').textContent = phase;
  }

  if ($('#treasuryTransferState')) {
    $('#treasuryTransferState').textContent = (
      transfersEnabled ? 'ENABLED' : 'DISABLED'
    );
  }

  if ($('#treasuryWithdrawalState')) {
    $('#treasuryWithdrawalState').textContent = (
      withdrawalsEnabled ? 'ENABLED' : 'DISABLED'
    );
  }

  if ($('#treasuryLockCount')) {
    $('#treasuryLockCount').textContent = String(
      state.treasuryLocks?.length || 0
    );
  }
}


function shortTreasuryId(value) {
  const text = String(value || '');

  if (text.length <= 22) {
    return text;
  }

  return `${text.slice(0, 12)}…${text.slice(-7)}`;
}


function treasuryOwnershipEntryType(value) {
  const type = String(value || '')
    .trim()
    .toLowerCase();

  const labels = {
    internal_transfer_credit: 'Internal transfer credit',
    withdrawal_debit: 'Withdrawal debit',
    return_transfer_debit: 'Return transfer debit',
    correction_credit: 'Correction credit',
    correction_debit: 'Correction debit',
  };

  return (
    labels[type]
    || reconciliationLabel(type || 'unknown')
  );
}


function treasurySignedAmount(
  value,
  currency = '',
) {
  const text = treasuryAmount(
    value,
    currency,
  );

  const number = Number(value);

  if (
    Number.isFinite(number)
    && number > 0
  ) {
    return `+${text}`;
  }

  return text;
}


function treasuryOwnershipLabels(rows = []) {
  const user = state.adminUser;

  const generic = {
    title: 'Main-held economic ownership',
    subtitle: (
      'Funds physically held by the Gate main account '
      + 'but economically owned by a dashboard account.'
    ),
    amountHeader: 'Main-held amount',
    empty: 'No main-held ownership balances.',
  };

  if (
    !user
    || user.role === 'super_admin'
  ) {
    return generic;
  }

  const accountIds = new Set(
    (user.account_ids || []).map(
      value => String(value || '').trim()
    )
  );

  let visibleAsOwner = false;
  let visibleAsCustodian = false;

  for (const item of rows) {
    const owner = String(
      item.owner_account_id || ''
    ).trim();

    const custody = String(
      item.custody_account_id || ''
    ).trim();

    if (accountIds.has(owner)) {
      visibleAsOwner = true;
    }

    if (
      accountIds.has(custody)
      && !accountIds.has(owner)
    ) {
      visibleAsCustodian = true;
    }
  }

  if (
    visibleAsCustodian
    && !visibleAsOwner
  ) {
    return {
      title: 'Custody liabilities',
      subtitle: (
        'Funds physically held by this Gate account '
        + 'but economically owned by other dashboard accounts.'
      ),
      amountHeader: 'Custody amount',
      empty: 'No custody liabilities.',
    };
  }

  if (
    visibleAsOwner
    && !visibleAsCustodian
  ) {
    return {
      title: 'Main-held economic ownership',
      subtitle: (
        'Funds economically owned by this dashboard account '
        + 'but physically held by the Gate main account.'
      ),
      amountHeader: 'Main-held amount',
      empty: 'No main-held ownership balances.',
    };
  }

  return generic;
}


function applyTreasuryOwnershipLabels(rows = []) {
  const labels = treasuryOwnershipLabels(rows);

  const title = $('#treasuryOwnershipTitle');
  const subtitle = $('#treasuryOwnershipSubtitle');
  const amountHeader = $(
    '#treasuryOwnershipAmountHeader'
  );

  if (title) {
    title.textContent = labels.title;
  }

  if (subtitle) {
    subtitle.textContent = labels.subtitle;
  }

  if (amountHeader) {
    amountHeader.textContent = labels.amountHeader;
  }

  return labels;
}



function treasuryIsUserOwnershipTransfer(item) {
  const operation = String(
    item?.request?.operation || ''
  ).trim().toLowerCase();

  const direction = String(
    item?.direction || ''
  ).trim().toLowerCase();

  return (
    operation === 'user_ownership_transfer'
    || direction === 'ownership'
  );
}


function treasuryUserTransferParticipantLabel(item) {
  const accountId = String(
    item?.account_id || ''
  );

  const usernames = (
    item?.usernames || []
  ).filter(Boolean);

  return usernames.length
    ? `${accountId} (${usernames.join(', ')})`
    : accountId;
}


function treasuryUserTransferSourceRows() {
  return (
    state.treasuryUserTransferParticipants || []
  ).filter(item => Boolean(item.can_source));
}


function treasuryUserTransferDestinationRows(source) {
  return (
    state.treasuryUserTransferParticipants || []
  ).filter(item => (
    Boolean(item.can_receive)
    && String(item.account_id || '') !== source
  ));
}


function treasuryUserTransferBalanceRows(source) {
  const participant = (
    state.treasuryUserTransferParticipants || []
  ).find(item => (
    String(item.account_id || '') === source
  ));

  return (
    participant?.available_balances || []
  ).filter(item => (
    Number(item.available || 0) > 0
  ));
}

function generateTreasuryUserTransferRequestId() {
  const timestamp = Date.now().toString(36);

  const random = new Uint32Array(2);
  crypto.getRandomValues(random);

  const suffix = Array.from(random)
    .map(value => (
      value.toString(16).padStart(8, '0')
    ))
    .join('');

  return `user-ui-${timestamp}-${suffix}`;
}


function setTreasuryUserTransferFormLocked(locked) {
  [
    '#treasuryUserTransferSource',
    '#treasuryUserTransferDestination',
    '#treasuryUserTransferCurrency',
    '#treasuryUserTransferAmount',
    '#treasuryUserTransferPreviewButton',
  ].forEach(selector => {
    const element = $(selector);

    if (element) {
      element.disabled = Boolean(locked);
    }
  });
}


function renderTreasuryUserTransferParticipants() {
  const sourceSelect = $('#treasuryUserTransferSource');
  const destinationSelect = $(
    '#treasuryUserTransferDestination'
  );
  const currencySelect = $(
    '#treasuryUserTransferCurrency'
  );

  if (
    !sourceSelect
    || !destinationSelect
    || !currencySelect
  ) {
    return;
  }

  const sources = treasuryUserTransferSourceRows();
  const previousSource = sourceSelect.value;

  sourceSelect.innerHTML = sources.length
    ? sources.map(item => (
        `<option value="${escapeHtml(
          item.account_id
        )}">${escapeHtml(
          treasuryUserTransferParticipantLabel(item)
        )}</option>`
      )).join('')
    : (
        '<option value="">'
        + 'No authorized source accounts'
        + '</option>'
      );

  const sourceIds = sources.map(
    item => String(item.account_id || '')
  );

  let source = '';

  if (
    previousSource
    && sourceIds.includes(previousSource)
  ) {
    source = previousSource;

  } else if (
    state.selectedAccount
    && sourceIds.includes(state.selectedAccount)
  ) {
    source = state.selectedAccount;

  } else {
    source = sourceIds[0] || '';
  }

  sourceSelect.value = source;
  sourceSelect.disabled = sourceIds.length <= 1;

  const destinations = (
    treasuryUserTransferDestinationRows(source)
  );

  const previousDestination = (
    destinationSelect.value
  );

  destinationSelect.innerHTML = destinations.length
    ? destinations.map(item => (
        `<option value="${escapeHtml(
          item.account_id
        )}">${escapeHtml(
          treasuryUserTransferParticipantLabel(item)
        )}</option>`
      )).join('')
    : (
        '<option value="">'
        + 'No registered recipients'
        + '</option>'
      );

  const destinationIds = destinations.map(
    item => String(item.account_id || '')
  );

  destinationSelect.value = (
    previousDestination
    && destinationIds.includes(
      previousDestination
    )
      ? previousDestination
      : destinationIds[0] || ''
  );

  destinationSelect.disabled = (
    !destinationIds.length
  );

  const balances = (
    treasuryUserTransferBalanceRows(source)
  );

  const previousCurrency = currencySelect.value;

  currencySelect.innerHTML = balances.length
    ? balances.map(item => {
        const currency = String(
          item.currency || ''
        );

        return (
          `<option value="${escapeHtml(currency)}">`
          + `${escapeHtml(currency)} · `
          + `${escapeHtml(
            treasuryAmount(
              item.available,
              currency
            )
          )} available`
          + '</option>'
        );
      }).join('')
    : (
        '<option value="">'
        + 'No available Gate spot assets'
        + '</option>'
      );

  const currencies = balances.map(
    item => String(item.currency || '')
  );

  currencySelect.value = (
    previousCurrency
    && currencies.includes(previousCurrency)
      ? previousCurrency
      : currencies[0] || ''
  );

  currencySelect.disabled = !currencies.length;

  const stateElement = $('#treasuryUserTransferState');

  if (stateElement) {
    stateElement.textContent = (
      state.treasuryUserTransfersEnabled
        ? 'LIVE ENABLED'
        : 'Transfers disabled'
    );
  }

  updateTreasuryUserTransferExecuteButton();
}



function treasuryUserTransferPathLabel(value) {
  const path = String(value || '').trim().toLowerCase();

  const labels = {
    subaccount_to_subaccount: 'Subaccount → Subaccount',
    subaccount_to_main: 'Subaccount → Main',
    main_to_subaccount: 'Main → Subaccount',
  };

  return labels[path] || path || '—';
}


function treasuryUserTransferOutcomeHtml(snapshot) {
  const outcome = snapshot?.executionResult;

  if (!outcome) {
    return '';
  }

  const kind = String(
    outcome.kind || ''
  ).toLowerCase();

  const success = kind === 'success';

  const amount = treasuryAmount(
    snapshot.amount,
    snapshot.currency
  );

  const requestId = String(
    snapshot.requestId || ''
  );

  const gateTransferId = String(
    outcome.gateTransferId || ''
  );

  return `
    <div class="treasury-user-transfer-outcome ${
      success ? 'success' : 'uncertain'
    }">
      <div class="treasury-user-transfer-outcome-icon">
        ${success ? '✓' : '!'}
      </div>

      <div class="treasury-user-transfer-outcome-body">
        <strong>
          ${
            success
              ? 'Transfer completed'
              : 'Reconciliation required'
          }
        </strong>

        <p>
          ${
            success
              ? (
                  `${escapeHtml(amount)} was transferred `
                  + `from <b>${escapeHtml(
                      snapshot.source
                    )}</b> → `
                  + `<b>${escapeHtml(
                      snapshot.destination
                    )}</b>. `
                  + 'This request is complete and '
                  + 'cannot be submitted again.'
                )
              : (
                  'The outcome of this request is not '
                  + 'definitive. Do not retry it and do '
                  + 'not create a replacement transfer. '
                  + 'Reconcile the original request first.'
                )
          }
        </p>

        <div class="treasury-user-transfer-outcome-meta">
          ${
            gateTransferId
              ? (
                  '<span>Gate transfer ID '
                  + `<strong>${escapeHtml(
                      gateTransferId
                    )}</strong></span>`
                )
              : ''
          }

          <span>
            Request
            <strong>${escapeHtml(requestId)}</strong>
          </span>
        </div>
      </div>

      <div class="treasury-user-transfer-outcome-actions">
        <button
          type="button"
          class="button secondary"
          data-user-transfer-view-request="${escapeHtml(
            requestId
          )}"
        >
          View in Treasury activity
        </button>

        ${
          success
            ? `
              <button
                type="button"
                class="button"
                data-user-transfer-new
              >
                New transfer
              </button>
            `
            : ''
        }
      </div>
    </div>
  `;
}


function renderTreasuryUserTransferPreview() {
  const container = $('#treasuryUserTransferPreview');
  const confirmationBlock = $(
    '#treasuryUserTransferConfirmationBlock'
  );

  if (!container || !confirmationBlock) {
    return;
  }

  const confirmationInput = $(
    '#treasuryUserTransferConfirmation'
  );

  const requiredElement = $(
    '#treasuryUserTransferRequiredConfirmation'
  );

  const confirmationText = $(
    '#treasuryUserTransferConfirmationText'
  );

  const executeButton = $(
    '#executeTreasuryUserTransfer'
  );

  const snapshot = state.treasuryUserTransferPreview;
  const executionResult = snapshot?.executionResult || null;

  if (!snapshot) {
    container.innerHTML = (
      '<div class="treasury-empty">'
      + 'Select a registered recipient and run a review.'
      + '</div>'
    );

    confirmationBlock.classList.add('hidden');

    if (confirmationInput) {
      confirmationInput.value = '';
      confirmationInput.disabled = true;
    }

    if (requiredElement) {
      requiredElement.textContent = '—';
    }

    if (executeButton) {
      executeButton.disabled = true;
      executeButton.textContent = 'Transfer funds';
    }

    return;
  }

  const response = snapshot.response || {};
  const preview = response.preview || {};

  const blockers = (
    preview.operation_blockers || []
  );

  const status = String(
    response.status || ''
  ).toLowerCase();

  const required = String(
    response.required_confirmation || ''
  );

  const executionImplemented = Boolean(
    response.execution_implemented
  );

  const liveEnabled = Boolean(
    state.treasuryUserTransfersEnabled
    && response.user_transfers_enabled
    && executionImplemented
  );

  const ready = Boolean(
    status === 'ready'
    && blockers.length === 0
  );

  const blockerText = blockers.length
    ? blockers.map(item => (
        item.message || item.type || 'Blocked'
      )).join(', ')
    : 'NONE';

  const pathLabel = treasuryUserTransferPathLabel(
    preview.transfer_path
  );

  const gateWriteClass = ready
    ? 'warning'
    : 'neutral';

  const blockerClass = blockers.length
    ? 'danger'
    : 'success';

  const implementationClass = executionImplemented
    ? 'success'
    : 'danger';

  const armClass = liveEnabled
    ? 'danger'
    : 'safe';

  container.innerHTML = `
    ${treasuryUserTransferOutcomeHtml(snapshot)}

    <div class="treasury-user-transfer-preview-grid">
      <div class="treasury-user-transfer-card">
        <span>Source account</span>
        <strong>${escapeHtml(
          preview.source_account_id || '—'
        )}</strong>
      </div>

      <div class="treasury-user-transfer-card">
        <span>Recipient account</span>
        <strong>${escapeHtml(
          preview.destination_account_id || '—'
        )}</strong>
      </div>

      <div class="treasury-user-transfer-card">
        <span>Asset</span>
        <strong>${escapeHtml(
          preview.currency || '—'
        )}</strong>
      </div>

      <div class="treasury-user-transfer-card">
        <span>Amount</span>
        <strong class="treasury-user-transfer-number">
          ${escapeHtml(
            treasuryAmount(
              preview.amount,
              preview.currency
            )
          )}
        </strong>
      </div>

      <div class="treasury-user-transfer-card">
        <span>Available before</span>
        <strong class="treasury-user-transfer-number">
          ${escapeHtml(
            treasuryAmount(
              preview.source_available_before,
              preview.currency
            )
          )}
        </strong>
      </div>

      <div class="treasury-user-transfer-card">
        <span>Available after</span>
        <strong class="treasury-user-transfer-number">
          ${escapeHtml(
            treasuryAmount(
              preview.source_available_after,
              preview.currency
            )
          )}
        </strong>
      </div>

      <div class="treasury-user-transfer-card">
        <span>Gate transfer path</span>
        <strong>${escapeHtml(pathLabel)}</strong>
      </div>

      <div class="treasury-user-transfer-card">
        <span>Gate write</span>
        <strong>
          <span class="treasury-user-transfer-chip ${gateWriteClass}">
            ${ready
              ? 'REQUIRED ON EXECUTION'
              : 'NOT PERFORMED'}
          </span>
        </strong>
      </div>

      <div class="treasury-user-transfer-card">
        <span>Operation blockers</span>
        <strong>
          <span class="treasury-user-transfer-chip ${blockerClass}">
            ${escapeHtml(blockerText)}
          </span>
        </strong>
      </div>

      <div class="treasury-user-transfer-card">
        <span>Execution</span>
        <strong>
          <span class="treasury-user-transfer-chip ${implementationClass}">
            ${executionImplemented
              ? 'IMPLEMENTED'
              : 'NOT IMPLEMENTED'}
          </span>
        </strong>
      </div>

      <div class="treasury-user-transfer-card treasury-user-transfer-arm-card">
        <span>Live transfer arm</span>
        <strong>
          <span class="treasury-user-transfer-chip ${armClass}">
            ${liveEnabled ? 'ENABLED' : 'DISABLED'}
          </span>
        </strong>
      </div>
    </div>
  `;

  const showConfirmation = Boolean(
    ready
    && executionImplemented
    && required
  );

  if (!showConfirmation) {
    confirmationBlock.classList.add('hidden');

    if (requiredElement) {
      requiredElement.textContent = '—';
    }

    if (confirmationInput) {
      confirmationInput.value = '';
      confirmationInput.disabled = true;
    }

    if (executeButton) {
      executeButton.disabled = true;
      executeButton.textContent = 'Transfer funds';
    }

    return;
  }

  confirmationBlock.classList.remove('hidden');

  if (requiredElement) {
    requiredElement.textContent = required;
  }

  if (confirmationText) {
    if (executionResult?.kind === 'success') {
      confirmationText.textContent = (
        'This transfer completed successfully. '
        + 'Use New transfer to create another request.'
      );

    } else if (executionResult) {
      confirmationText.textContent = (
        'This request requires reconciliation. '
        + 'Do not retry or create a replacement transfer.'
      );

    } else {
      confirmationText.textContent = liveEnabled
        ? (
            'Type the exact confirmation below '
            + 'before transferring.'
          )
        : (
            'Transfers are currently disabled. '
            + 'The exact confirmation is shown '
            + 'for validation only.'
          );
    }
  }

  if (confirmationInput) {
    confirmationInput.disabled = Boolean(
      executionResult
      || !liveEnabled
      || state.treasuryUserTransferExecutionAttempted
    );
  }

  if (executeButton) {
    if (executionResult?.kind === 'success') {
      executeButton.textContent = 'Transfer completed ✓';
      executeButton.disabled = true;

    } else if (executionResult) {
      executeButton.textContent = (
        'Reconciliation required'
      );
      executeButton.disabled = true;

    } else {
      executeButton.textContent = (
        state.treasuryUserTransferExecutionAttempted
          ? 'Reconciliation required'
          : (
              liveEnabled
                ? 'Transfer funds'
                : 'Transfers disabled'
            )
      );
    }
  }

  if (executionResult) {
    setTreasuryUserTransferFormLocked(true);
    return;
  }

  updateTreasuryUserTransferExecuteButton();
}


function clearTreasuryUserTransferPreview() {
  state.treasuryUserTransferPreview = null;
  state.treasuryUserTransferExecutionAttempted = false;

  setTreasuryUserTransferFormLocked(false);
  renderTreasuryUserTransferPreview();
}


async function startNewTreasuryUserTransfer() {
  const snapshot = state.treasuryUserTransferPreview;

  if (
    snapshot?.executionResult?.kind !== 'success'
  ) {
    return;
  }

  const amount = $('#treasuryUserTransferAmount');
  const confirmation = $(
    '#treasuryUserTransferConfirmation'
  );

  const errorBox = $('#treasuryUserTransferError');

  if (amount) {
    amount.value = '';
  }

  if (confirmation) {
    confirmation.value = '';
  }

  if (errorBox) {
    errorBox.textContent = '';
    errorBox.classList.add('hidden');
  }

  clearTreasuryUserTransferPreview();

  await loadTreasuryOverview({
    quiet: true,
  });

  $('#treasuryUserTransferAmount')?.focus();
}


function updateTreasuryUserTransferExecuteButton() {
  const button = $('#executeTreasuryUserTransfer');

  if (!button) return;

  const snapshot = state.treasuryUserTransferPreview;
  const executionResult = snapshot?.executionResult;

  if (executionResult?.kind === 'success') {
    button.textContent = 'Transfer completed ✓';
    button.disabled = true;
    return;
  }

  if (executionResult) {
    button.textContent = 'Reconciliation required';
    button.disabled = true;
    return;
  }

  const response = snapshot?.response || {};

  const confirmation = String(
    $('#treasuryUserTransferConfirmation')?.value
    || ''
  );

  const required = String(
    response.required_confirmation || ''
  );

  const status = String(
    response.status || ''
  ).toLowerCase();

  const liveEnabled = Boolean(
    state.treasuryUserTransfersEnabled
    && response.user_transfers_enabled
    && response.execution_implemented
  );

  button.disabled = !(
    snapshot
    && liveEnabled
    && status === 'ready'
    && response.can_execute
    && !state.treasuryUserTransferExecutionAttempted
    && required
    && confirmation === required
  );
}


async function runTreasuryUserTransferPreview(event) {
  event?.preventDefault();

  const source = String(
    $('#treasuryUserTransferSource')?.value
    || ''
  );

  const destination = String(
    $('#treasuryUserTransferDestination')?.value
    || ''
  );

  const currency = String(
    $('#treasuryUserTransferCurrency')?.value
    || ''
  ).toUpperCase();

  const amount = String(
    $('#treasuryUserTransferAmount')?.value
    || ''
  ).trim();

  const button = $('#treasuryUserTransferPreviewButton');
  const errorBox = $('#treasuryUserTransferError');

  errorBox?.classList.add('hidden');

  if (
    !source
    || !destination
    || !currency
    || !amount
  ) {
    return;
  }

  button.disabled = true;
  button.textContent = 'Reviewing…';

  state.treasuryUserTransferPreview = null;
  state.treasuryUserTransferExecutionAttempted = false;

  renderTreasuryUserTransferPreview();

  try {
    const response = await adminApi(
      '/api/treasury/user-transfers/preview',
      {
        method: 'POST',
        body: JSON.stringify({
          source_account_id: source,
          destination_account_id: destination,
          currency,
          amount,
        }),
      },
    );

    if (response.gate_write_performed) {
      throw new Error(
        'Safety invariant failed: user-transfer '
        + 'preview reported a Gate write.'
      );
    }

    state.treasuryUserTransferPreview = {
      source,
      destination,
      currency,
      amount,
      requestId: (
        generateTreasuryUserTransferRequestId()
      ),
      response,
    };

    if ($('#treasuryUserTransferConfirmation')) {
      $('#treasuryUserTransferConfirmation').value = '';
    }

    renderTreasuryUserTransferPreview();

  } catch (error) {
    const message = treasuryErrorMessage(error);

    if (errorBox) {
      errorBox.textContent = message;
      errorBox.classList.remove('hidden');
    }

    showToast(message, true);

  } finally {
    button.disabled = false;
    button.textContent = 'Review transfer';
  }
}


async function executeTreasuryUserTransfer() {
  const snapshot = state.treasuryUserTransferPreview;

  if (
    !snapshot
    || state.treasuryUserTransferExecutionAttempted
  ) {
    return;
  }

  const response = snapshot.response || {};

  const required = String(
    response.required_confirmation || ''
  );

  const confirmation = String(
    $('#treasuryUserTransferConfirmation')?.value
    || ''
  );

  const liveEnabled = Boolean(
    state.treasuryUserTransfersEnabled
    && response.user_transfers_enabled
    && response.execution_implemented
  );

  if (
    !liveEnabled
    || !response.can_execute
    || !required
    || confirmation !== required
  ) {
    return;
  }

  const button = $('#executeTreasuryUserTransfer');
  const errorBox = $('#treasuryUserTransferError');

  if (!button) return;

  button.disabled = true;
  button.textContent = 'Transferring…';

  errorBox?.classList.add('hidden');

  state.treasuryUserTransferExecutionAttempted = true;

  // From this point onward the exact request must remain
  // immutable until the outcome is definitive.
  setTreasuryUserTransferFormLocked(true);

  if ($('#treasuryUserTransferConfirmation')) {
    $('#treasuryUserTransferConfirmation').disabled = true;
  }

  try {
    const result = await adminApi(
      '/api/treasury/user-transfers/execute',
      {
        method: 'POST',
        body: JSON.stringify({
          request_id: snapshot.requestId,
          source_account_id: snapshot.source,
          destination_account_id: snapshot.destination,
          currency: snapshot.currency,
          amount: snapshot.amount,
          confirmation,
        }),
      },
    );

    const status = String(
      result.status || ''
    ).toLowerCase();

    if (status === 'success') {
      if (
        !result.gate_write_performed
        && !result.audit?.write_performed
      ) {
        throw new Error(
          'Safety invariant failed: successful '
          + 'user transfer has no recorded Gate write.'
        );
      }

      snapshot.executionResult = {
        kind: 'success',
        status: 'success',
        gateTransferId: (
          result.gate_transfer_id
          || result.tx_id
          || result.audit?.gate_transfer_id
          || result.audit?.tx_id
          || ''
        ),
      };

      showToast(
        `Transferred ${
          treasuryAmount(
            result.amount || snapshot.amount,
            result.currency || snapshot.currency
          )
        } from ${
          result.source_account_id || snapshot.source
        } to ${
          result.destination_account_id
          || snapshot.destination
        }.`
      );

      renderTreasuryUserTransferPreview();

      await loadTreasuryOverview({
        quiet: true,
      });

      setTreasuryUserTransferFormLocked(true);
      renderTreasuryUserTransferPreview();

      return;
    }

    const terminal = [
      'failed',
      'rejected',
      'blocked',
      'preflight_failed',
    ].includes(status);

    if (terminal) {
      showToast(
        `User transfer finished with status ${status}.`,
        true,
      );

      clearTreasuryUserTransferPreview();

      await loadTreasuryOverview({
        quiet: true,
      });

      return;
    }

    const retainedMessage = (
      `Transfer status is ${status || 'uncertain'}. `
      + `Request ${snapshot.requestId} is retained. `
      + 'Do not retry this transfer or create a '
      + 'replacement request. Reconciliation is required.'
    );

    snapshot.executionResult = {
      kind: 'uncertain',
      status: status || 'uncertain',
      gateTransferId: (
        result.gate_transfer_id
        || result.tx_id
        || result.audit?.gate_transfer_id
        || result.audit?.tx_id
        || ''
      ),
    };

    renderTreasuryUserTransferPreview();

    if (errorBox) {
      errorBox.textContent = retainedMessage;
      errorBox.classList.remove('hidden');
    }

    button.textContent = 'Reconciliation required';
    button.disabled = true;

    showToast(retainedMessage, true);

  } catch (error) {
    const message = treasuryErrorMessage(error);

    const detail = (
      error?.payload?.detail || {}
    );

    const auditStatus = String(
      detail?.audit?.status
      || detail?.status
      || ''
    ).toLowerCase();

    const successful = (
      auditStatus === 'success'
    );

    const terminalFailure = [
      'failed',
      'rejected',
      'blocked',
      'preflight_failed',
    ].includes(auditStatus);

    const explicitNoGateWrite = (
      detail?.gate_write_performed === false
    );

    if (successful) {
      snapshot.executionResult = {
        kind: 'success',
        status: 'success',
        gateTransferId: (
          detail?.gate_transfer_id
          || detail?.tx_id
          || detail?.audit?.gate_transfer_id
          || detail?.audit?.tx_id
          || ''
        ),
      };

      if (errorBox) {
        errorBox.textContent = (
          'The response path returned an error, but '
          + 'the persistent audit record confirms that '
          + 'the transfer succeeded. Do not retry it.'
        );

        errorBox.classList.remove('hidden');
      }

      showToast(
        'Transfer completed. Persistent audit confirms '
        + 'Gate success.'
      );

      renderTreasuryUserTransferPreview();

      try {
        await loadTreasuryOverview({
          quiet: true,
        });
      } catch (_refreshError) {
        // Preserve the definitive completed request.
      }

      setTreasuryUserTransferFormLocked(true);
      renderTreasuryUserTransferPreview();

      return;
    }

    if (errorBox) {
      if (
        explicitNoGateWrite
        || terminalFailure
      ) {
        errorBox.textContent = message;

      } else {
        errorBox.textContent = (
          `${message} Request ${
            snapshot.requestId
          } is retained. Do not retry or create a `
          + 'replacement transfer. Reconciliation '
          + 'is required.'
        );
      }

      errorBox.classList.remove('hidden');
    }

    showToast(message, true);

    if (
      explicitNoGateWrite
      || terminalFailure
    ) {
      clearTreasuryUserTransferPreview();

      try {
        await loadTreasuryOverview({
          quiet: true,
        });
      } catch (_refreshError) {
        // Preserve original operation error.
      }

    } else {
      snapshot.executionResult = {
        kind: 'uncertain',
        status: auditStatus || 'uncertain',
        gateTransferId: (
          detail?.gate_transfer_id
          || detail?.tx_id
          || detail?.audit?.gate_transfer_id
          || detail?.audit?.tx_id
          || ''
        ),
      };

      renderTreasuryUserTransferPreview();

      button.textContent = 'Reconciliation required';
      button.disabled = true;
    }

    return;

  } finally {
    const executionKind = String(
      snapshot.executionResult?.kind || ''
    ).toLowerCase();

    if (executionKind === 'success') {
      setTreasuryUserTransferFormLocked(true);
      button.textContent = 'Transfer completed ✓';
      button.disabled = true;

    } else if (executionKind) {
      setTreasuryUserTransferFormLocked(true);
      button.textContent = 'Reconciliation required';
      button.disabled = true;

    } else {
      if (!state.treasuryUserTransferPreview) {
        setTreasuryUserTransferFormLocked(false);
      }

      if (state.treasuryUserTransferPreview) {
        if (
          state.treasuryUserTransferExecutionAttempted
        ) {
          button.textContent = 'Reconciliation required';
          button.disabled = true;

        } else {
          button.textContent = 'Transfer funds';
          updateTreasuryUserTransferExecuteButton();
        }
      }
    }
  }
}


function invalidateTreasuryUserTransferPreview() {
  if (
    state.treasuryUserTransferExecutionAttempted
    && state.treasuryUserTransferPreview
  ) {
    return;
  }

  clearTreasuryUserTransferPreview();
}


function treasuryApprovedWithdrawalDestinations() {
  return (
    state.treasuryWithdrawalDestinations || []
  ).filter(item => (
    String(item.status || '').toLowerCase()
    === 'approved'
  ));
}


function treasurySelectedWithdrawalDestination() {
  const id = String(
    $('#treasuryWithdrawalDestination')?.value
    || ''
  );

  return treasuryApprovedWithdrawalDestinations()
    .find(item => (
      String(item.destination_id || '') === id
    )) || null;
}


function clearTreasuryWithdrawalPreflight() {
  state.treasuryWithdrawalPreflight = null;

  renderTreasuryWithdrawalPreflight();
}


function renderTreasuryWithdrawalDestinations() {
  const select = $('#treasuryWithdrawalDestination');

  if (!select) return;

  const rows = treasuryApprovedWithdrawalDestinations();
  const previous = select.value;

  if (!rows.length) {
    select.innerHTML = (
      '<option value="">'
      + 'No approved destinations available'
      + '</option>'
    );

    select.disabled = true;

  } else {
    select.disabled = false;

    select.innerHTML = rows.map(item => {
      const destinationId = String(
        item.destination_id || ''
      );

      const label = String(
        item.label
        || shortTreasuryGateId(item.address)
        || destinationId
      );

      const text = [
        item.owner_account_id || '—',
        item.currency || '—',
        item.chain || '—',
        label,
      ].join(' · ');

      return (
        `<option value="${escapeHtml(destinationId)}">`
        + `${escapeHtml(text)}`
        + '</option>'
      );
    }).join('');

    const availableIds = rows.map(
      item => String(item.destination_id || '')
    );

    if (
      previous
      && availableIds.includes(previous)
    ) {
      select.value = previous;
    }
  }

  const count = $('#treasuryWithdrawalDestinationCount');

  if (count) {
    count.textContent = (
      `${rows.length} approved destination${
        rows.length === 1 ? '' : 's'
      }`
    );
  }

  renderTreasuryWithdrawalDestinationSummary();
}


function renderTreasuryWithdrawalDestinationSummary() {
  const element = $(
    '#treasuryWithdrawalDestinationSummary'
  );

  if (!element) return;

  const item = treasurySelectedWithdrawalDestination();

  if (!item) {
    element.innerHTML = (
      '<div class="treasury-empty">'
      + 'Select an approved destination.'
      + '</div>'
    );

    return;
  }

  const address = String(item.address || '');

  element.innerHTML = (
    '<div class="treasury-withdrawal-summary-field">'
    + '<span>Economic owner</span>'
    + `<strong>${escapeHtml(
        item.owner_account_id || '—'
      )}</strong>`
    + '</div>'

    + '<div class="treasury-withdrawal-summary-field">'
    + '<span>Asset</span>'
    + `<strong>${escapeHtml(
        item.currency || '—'
      )}</strong>`
    + '</div>'

    + '<div class="treasury-withdrawal-summary-field">'
    + '<span>Network</span>'
    + `<strong>${escapeHtml(
        item.chain || '—'
      )}</strong>`
    + '</div>'

    + '<div class="treasury-withdrawal-summary-field">'
    + '<span>Address</span>'
    + `<strong title="${escapeHtml(address)}">${
        escapeHtml(
          shortTreasuryGateId(address)
        )
      }</strong>`
    + '</div>'

    + '<div class="treasury-withdrawal-summary-field">'
    + '<span>Memo / tag</span>'
    + `<strong>${escapeHtml(
        item.memo || 'None'
      )}</strong>`
    + '</div>'
  );
}


function treasuryWithdrawalPreflightMatchesForm() {
  const snapshot = state.treasuryWithdrawalPreflight;
  const destination = treasurySelectedWithdrawalDestination();

  if (!snapshot || !destination) {
    return false;
  }

  const amount = String(
    $('#treasuryWithdrawalAmount')?.value
    || ''
  ).trim();

  return Boolean(
    snapshot.destinationId
      === String(destination.destination_id || '')
    && snapshot.owner
      === String(destination.owner_account_id || '')
    && snapshot.currency
      === String(destination.currency || '').toUpperCase()
    && snapshot.amount === amount
  );
}


function renderTreasuryWithdrawalPreflight() {
  const element = $('#treasuryWithdrawalPreflight');
  const createButton = $(
    '#createTreasuryWithdrawalRequest'
  );

  if (!element) return;

  const snapshot = state.treasuryWithdrawalPreflight;

  if (!snapshot) {
    element.innerHTML = (
      '<div class="treasury-empty">'
      + 'Run a preflight to review Gate limits, fee, '
      + 'recipient estimate, ownership and JIT requirements.'
      + '</div>'
    );

    if (createButton) {
      createButton.disabled = true;
    }

    return;
  }

  const response = snapshot.response || {};
  const preflight = response.preflight || {};
  const fee = preflight.fee || {};
  const funding = preflight.funding || {};
  const eligibility = (
    preflight.gate_address_eligibility || {}
  );

  const valid = Boolean(
    preflight.preflight_valid
    && treasuryWithdrawalPreflightMatchesForm()
  );

  const errors = (
    preflight.errors || []
  ).map(value => String(value));

  element.innerHTML = (
    `<div class="treasury-withdrawal-preflight-head ${
      valid ? 'valid' : 'invalid'
    }">`
    + `<strong>${
        valid
          ? 'Preflight passed'
          : 'Preflight blocked'
      }</strong>`
    + `<span>${
        valid
          ? 'No Gate write performed'
          : escapeHtml(
              errors.length
                ? errors.join(', ')
                : 'Safety checks did not pass'
            )
      }</span>`
    + '</div>'

    + '<div class="treasury-withdrawal-preflight-grid">'

    + '<div>'
    + '<span>Requested</span>'
    + `<strong>${escapeHtml(
        treasuryAmount(
          snapshot.amount,
          snapshot.currency
        )
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Estimated fee</span>'
    + `<strong>${escapeHtml(
        treasuryAmount(
          fee.estimated_fee,
          snapshot.currency
        )
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Recipient estimate</span>'
    + `<strong>${escapeHtml(
        treasuryAmount(
          fee.recipient_amount_estimate,
          snapshot.currency
        )
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Main-held ownership</span>'
    + `<strong>${escapeHtml(
        treasuryAmount(
          funding.owner_main_held,
          snapshot.currency
        )
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Conservative funding</span>'
    + `<strong>${escapeHtml(
        treasuryAmount(
          funding.conservative_funding_required,
          snapshot.currency
        )
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>JIT required</span>'
    + `<strong>${
        funding.jit_required ? 'Yes' : 'No'
      }</strong>`
    + '</div>'

    + '<div>'
    + '<span>Minimum JIT</span>'
    + `<strong>${escapeHtml(
        treasuryAmount(
          funding.minimum_jit_transfer,
          snapshot.currency
        )
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Address policy</span>'
    + `<strong>${escapeHtml(
        eligibility.address_policy || '—'
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Eligible via</span>'
    + `<strong>${escapeHtml(
        eligibility.eligible_via || '—'
      )}</strong>`
    + '</div>'

    + '</div>'
  );

  if (createButton) {
    createButton.disabled = !valid;
  }
}


function treasuryWithdrawalRequestStatusClass(value) {
  const status = String(
    value || ''
  ).toLowerCase();

  if (status === 'withdrawal_settled') {
    return 'success';
  }

  if (
    status === 'withdrawal_failed'
    || status === 'blocked'
    || status === 'cancelled'
    || status === 'jit_failed'
  ) {
    return 'failed';
  }

  if (
    status === 'withdrawal_submitting'
    || status === 'withdrawal_submitted'
    || status === 'withdrawal_reconciling'
    || status === 'jit_executing'
    || status === 'jit_reconciling'
  ) {
    return 'pending';
  }

  if (
    status === 'withdrawal_done_unsettled'
    || status === 'jit_ready'
    || status === 'jit_prepared'
    || status === 'confirmed_ready'
    || status === 'reserved'
  ) {
    return 'warning';
  }

  return '';
}


function renderTreasuryWithdrawalRequests() {
  const body = $('#treasuryWithdrawalRequestBody');

  if (!body) return;

  const rows = (
    state.treasuryWithdrawalRequests || []
  );

  if (!rows.length) {
    body.innerHTML = (
      '<tr>'
      + '<td colspan="8" class="empty-state">'
      + 'No withdrawal requests recorded.'
      + '</td>'
      + '</tr>'
    );

  } else {
    body.innerHTML = rows.map(item => {
      const destinationId = String(
        item.destination_id || ''
      );

      const requestId = String(
        item.request_id || ''
      );

      const status = String(
        item.status || 'unknown'
      );

      return (
        '<tr>'
        + `<td>${escapeHtml(
            fmtDate(item.created_at)
          )}</td>`

        + `<td><strong>${escapeHtml(
            item.owner_account_id || '—'
          )}</strong></td>`

        + `<td title="${escapeHtml(destinationId)}">${
            escapeHtml(
              shortTreasuryRequestId(destinationId)
            )
          }</td>`

        + `<td>${escapeHtml(
            treasuryAmount(
              item.amount,
              item.currency
            )
          )}</td>`

        + `<td>${escapeHtml(
            treasuryAmount(
              item.estimated_fee,
              item.currency
            )
          )}</td>`

        + '<td>'
        + `<span class="treasury-status ${
            escapeHtml(
              treasuryWithdrawalRequestStatusClass(
                status
              )
            )
          }">${escapeHtml(status)}</span>`
        + '</td>'

        + `<td>${escapeHtml(
            item.gate_status || '—'
          )}</td>`

        + '<td>'
        + `<button
            type="button"
            class="treasury-request-link"
            data-treasury-withdrawal-request="${
              escapeHtml(requestId)
            }"
            title="${escapeHtml(requestId)}"
          >${
            escapeHtml(
              shortTreasuryRequestId(requestId)
            )
          }</button>`
        + '</td>'

        + '</tr>'
      );
    }).join('');
  }

  const count = $('#treasuryWithdrawalRequestCount');

  if (count) {
    count.textContent = (
      `${rows.length} request${
        rows.length === 1 ? '' : 's'
      }`
    );
  }
}


function generateTreasuryWithdrawalRequestId() {
  const timestamp = Date.now().toString(36);

  const random = new Uint32Array(2);
  crypto.getRandomValues(random);

  const suffix = Array.from(random)
    .map(value => (
      value.toString(16).padStart(8, '0')
    ))
    .join('');

  return `wd-ui-${timestamp}-${suffix}`;
}


async function runTreasuryWithdrawalPreflight(event) {
  event?.preventDefault();

  const destination = treasurySelectedWithdrawalDestination();
  const amount = String(
    $('#treasuryWithdrawalAmount')?.value
    || ''
  ).trim();

  const button = $('#treasuryWithdrawalPreflightButton');
  const errorBox = $('#treasuryWithdrawalFormError');

  errorBox?.classList.add('hidden');

  if (!destination || !amount) {
    return;
  }

  const owner = String(
    destination.owner_account_id || ''
  );

  const currency = String(
    destination.currency || ''
  ).toUpperCase();

  const destinationId = String(
    destination.destination_id || ''
  );

  if (
    !owner
    || !currency
    || !destinationId
  ) {
    return;
  }

  button.disabled = true;
  button.textContent = 'Checking…';

  state.treasuryWithdrawalPreflight = null;
  renderTreasuryWithdrawalPreflight();

  try {
    const params = new URLSearchParams({
      owner_account_id: owner,
      destination_id: destinationId,
      amount,
    });

    const response = await adminApi(
      `/api/treasury/withdrawals/preflight/${
        encodeURIComponent(currency)
      }?${params.toString()}`
    );

    state.treasuryWithdrawalPreflight = {
      owner,
      currency,
      destinationId,
      amount,
      requestId: generateTreasuryWithdrawalRequestId(),
      response,
    };

    renderTreasuryWithdrawalPreflight();

  } catch (error) {
    const message = treasuryErrorMessage(error);

    if (errorBox) {
      errorBox.textContent = message;
      errorBox.classList.remove('hidden');
    }

    showToast(message, true);

  } finally {
    button.disabled = false;
    button.textContent = 'Run safety preflight';
  }
}


async function createTreasuryWithdrawalRequest() {
  const snapshot = state.treasuryWithdrawalPreflight;
  const button = $('#createTreasuryWithdrawalRequest');
  const errorBox = $('#treasuryWithdrawalFormError');

  if (
    !snapshot
    || !treasuryWithdrawalPreflightMatchesForm()
    || !snapshot.response?.preflight?.preflight_valid
  ) {
    return;
  }

  button.disabled = true;
  button.textContent = 'Creating…';

  errorBox?.classList.add('hidden');

  const requestId = String(
    snapshot.requestId || ''
  );

  if (!requestId) {
    return;
  }

  try {
    const result = await adminApi(
      '/api/treasury/withdrawals/requests/simulate',
      {
        method: 'POST',
        body: JSON.stringify({
          request_id: requestId,
          owner_account_id: snapshot.owner,
          destination_id: snapshot.destinationId,
          currency: snapshot.currency,
          amount: snapshot.amount,
        }),
      },
    );

    const audit = result.audit || {};

    if (
      result.gate_write_performed
      || audit.gate_write_performed
      || audit.write_performed
    ) {
      throw new Error(
        'Safety invariant failed: request creation '
        + 'reported a Gate write.'
      );
    }

    if (
      result.audit_recorded !== true
      || !audit.request_id
      || String(audit.request_id) !== requestId
    ) {
      throw new Error(
        'Withdrawal request was not recorded. '
        + 'The safety preflight may have changed; '
        + 'run a fresh preflight and try again.'
      );
    }

    state.treasuryWithdrawalPreflight = null;
    renderTreasuryWithdrawalPreflight();

    showToast(
      `Withdrawal request created: ${requestId}`
    );

    await loadTreasuryOverview({
      quiet: true,
    });

  } catch (error) {
    const message = treasuryErrorMessage(error);

    if (errorBox) {
      errorBox.textContent = message;
      errorBox.classList.remove('hidden');
    }

    showToast(message, true);

  } finally {
    button.textContent = 'Create withdrawal request';

    renderTreasuryWithdrawalPreflight();
  }
}


function invalidateTreasuryWithdrawalPreflight() {
  clearTreasuryWithdrawalPreflight();
  renderTreasuryWithdrawalDestinationSummary();
}



function treasuryCompactDecimal(value) {
  let text = String(
    value === null || value === undefined
      ? ''
      : value
  ).trim();

  if (text.includes('.')) {
    text = text
      .replace(/0+$/, '')
      .replace(/\.$/, '');
  }

  return text;
}


function treasuryWithdrawalReserveConfirmation(item) {
  return (
    `RESERVE WITHDRAWAL ${
      String(item?.request_id || '')
    }`
  );
}


function treasuryWithdrawalConfirmConfirmation(item) {
  return [
    'CONFIRM WITHDRAWAL',
    String(item?.request_id || ''),
    String(item?.owner_account_id || ''),
    String(item?.currency || ''),
    treasuryCompactDecimal(item?.amount),
    String(item?.chain || ''),
    String(item?.destination_id || ''),
  ].join(' ');
}


function treasuryWithdrawalJitPrepareConfirmation(item) {
  return (
    `PREPARE WITHDRAWAL JIT ${
      String(item?.request_id || '')
    }`
  );
}


function treasuryWithdrawalLifecycleConfirmation(
  item
) {
  const status = String(
    item?.status || ''
  ).toLowerCase();

  if (status === 'simulated') {
    return treasuryWithdrawalReserveConfirmation(
      item
    );
  }

  if (status === 'reserved') {
    return (
      state.treasuryWithdrawalRequiredConfirmation
      || treasuryWithdrawalConfirmConfirmation(item)
    );
  }

  if (status === 'confirmed_ready') {
    return treasuryWithdrawalJitPrepareConfirmation(
      item
    );
  }

  return '';
}


function updateTreasuryWithdrawalLifecycleButtons() {
  const payload = (
    state.treasuryWithdrawalRequestDetail
  );

  const item = payload?.item || {};

  const status = String(
    item.status || ''
  ).toLowerCase();

  const required = (
    treasuryWithdrawalLifecycleConfirmation(item)
  );

  const typed = String(
    $('#treasuryWithdrawalConfirmation')?.value
    || ''
  );

  const exact = Boolean(
    required && typed === required
  );

  const reserve = $(
    '#reserveTreasuryWithdrawalRequest'
  );

  const confirm = $(
    '#confirmTreasuryWithdrawalRequest'
  );

  const prepareJit = $(
    '#prepareTreasuryWithdrawalJit'
  );

  if (reserve) {
    reserve.classList.toggle(
      'hidden',
      status !== 'simulated'
    );

    reserve.disabled = !(
      status === 'simulated' && exact
    );
  }

  if (confirm) {
    confirm.classList.toggle(
      'hidden',
      status !== 'reserved'
    );

    confirm.disabled = !(
      status === 'reserved' && exact
    );
  }

  if (prepareJit) {
    prepareJit.classList.toggle(
      'hidden',
      status !== 'confirmed_ready'
    );

    prepareJit.disabled = !(
      status === 'confirmed_ready' && exact
    );
  }
}


function renderTreasuryWithdrawalEvents(rows = []) {
  const element = $('#treasuryWithdrawalEventHistory');

  if (!element) return;

  if (!rows.length) {
    element.innerHTML = (
      '<div class="treasury-empty">'
      + 'No withdrawal lifecycle events.'
      + '</div>'
    );

    return;
  }

  element.innerHTML = rows.map(row => {
    const details = row.details || {};

    return (
      '<article class="treasury-history-card">'
      + '<div class="treasury-history-head">'
      + `<strong>${escapeHtml(
          reconciliationLabel(
            row.action || 'unknown'
          )
        )}</strong>`
      + `<span>${escapeHtml(
          row.username || '—'
        )}</span>`
      + '</div>'
      + `<div class="treasury-history-meta">${
          escapeHtml(fmtDate(row.created_at))
        }</div>`
      + (
          Object.keys(details).length
            ? (
                '<details class="treasury-json-details">'
                + '<summary>Event details</summary>'
                + `<pre class="treasury-json">${
                    escapeHtml(
                      JSON.stringify(
                        details,
                        null,
                        2
                      )
                    )
                  }</pre>`
                + '</details>'
              )
            : ''
        )
      + '</article>'
    );
  }).join('');
}



function renderTreasuryWithdrawalJitExecutionPreview(
  payload
) {
  const element = $(
    '#treasuryWithdrawalJitExecutionPreview'
  );

  if (!element) return;

  const item = payload?.item || {};
  const preview = (
    payload?.jit_execution_preview
  );

  const status = String(
    item.status || ''
  ).toLowerCase();

  const previewVisible = Boolean(
    status === 'jit_prepared'
    && preview
  );

  const reconcileVisible = (
    status === 'jit_executing'
    || status === 'jit_reconciling'
  );

  const visible = (
    previewVisible
    || reconcileVisible
  );

  element.classList.toggle(
    'hidden',
    !visible
  );

  if (!visible) {
    element.innerHTML = '';
    return;
  }

  if (reconcileVisible) {
    element.innerHTML = (
      '<div class="treasury-section-header">'
      + '<div>'
      + '<h3>JIT reconciliation required</h3>'
      + '<p>'
      + 'The JIT transfer may have crossed the Gate '
      + 'submission boundary. Do not execute again.'
      + '</p>'
      + '</div>'
      + '</div>'

      + '<div class="treasury-withdrawal-safety-note">'
      + 'Reconciliation performs the existing safe '
      + 'recovery path and does not submit a second '
      + 'Treasury transfer.'
      + '</div>'

      + '<div class="treasury-withdrawal-actions">'
      + '<button '
      + 'type="button" '
      + 'class="button secondary" '
      + 'id="reconcileTreasuryWithdrawalJit">'
      + 'Reconcile JIT'
      + '</button>'
      + '</div>'
    );

    return;
  }

  if (!preview.available) {
    element.innerHTML = (
      '<strong>JIT execution preview unavailable</strong>'
      + `<p>${escapeHtml(
          preview.error
          || preview.reason
          || 'Stored JIT preparation data is incomplete.'
        )}</p>`
    );

    return;
  }

  const plan = preview.jit_plan || {};

  const barriersOpen = Boolean(
    preview.application_barriers_open
  );

  const confirmation = String(
    preview.required_confirmation || ''
  );

  element.innerHTML = (
    '<div class="treasury-section-header">'
    + '<div>'
    + '<h3>JIT execution</h3>'
    + '<p>'
    + 'The transfer amount is recalculated by a fresh '
    + 'Gate preflight immediately before execution.'
    + '</p>'
    + '</div>'
    + '</div>'

    + '<div class="treasury-request-grid">'

    + '<div>'
    + '<span>Source</span>'
    + `<strong>${escapeHtml(
        plan.source_account_id || '—'
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Custody</span>'
    + `<strong>${escapeHtml(
        plan.custody_account_id || '—'
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Currency</span>'
    + `<strong>${escapeHtml(
        plan.currency || '—'
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>JIT required</span>'
    + `<strong>${
        plan.jit_required ? 'Yes' : 'No'
      }</strong>`
    + '</div>'

    + '<div>'
    + '<span>JIT amount preview</span>'
    + `<strong>${escapeHtml(
        treasuryAmount(
          plan.jit_amount_preview,
          plan.currency
        )
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Live transfer arm</span>'
    + `<strong>${
        preview.live_transfers_armed
          ? 'ARMED'
          : 'DISABLED'
      }</strong>`
    + '</div>'

    + '<div>'
    + '<span>Source allowlist</span>'
    + `<strong>${
        preview.source_account_live_enabled
          ? 'Allowed'
          : 'Blocked'
      }</strong>`
    + '</div>'

    + '<div>'
    + '<span>Application barriers</span>'
    + `<strong>${
        barriersOpen
          ? 'Open'
          : 'Blocked'
      }</strong>`
    + '</div>'

    + '</div>'

    + '<div class="treasury-withdrawal-safety-note">'
    + 'The amount above is not execution authority. '
    + 'The server recomputes the JIT plan before '
    + 'crossing the transfer boundary.'
    + '</div>'

    + '<label>'
    + 'Exact money-moving confirmation'
    + `<code>${escapeHtml(
        confirmation || '—'
      )}</code>`
    + '<input '
    + 'id="treasuryWithdrawalJitExecutionConfirmation" '
    + 'type="text" '
    + 'autocomplete="off" '
    + 'spellcheck="false">'
    + '</label>'

    + '<div class="treasury-withdrawal-actions">'
    + '<button '
    + 'type="button" '
    + 'class="button" '
    + 'id="executeTreasuryWithdrawalJit" '
    + 'disabled>'
    + 'Execute JIT transfer'
    + '</button>'
    + '</div>'

    + '<div class="treasury-withdrawal-safety-note">'
    + (
        barriersOpen
          ? (
              'Application barriers are open. Execution '
              + 'still requires the exact confirmation.'
            )
          : (
              'Execution remains blocked while the live '
              + 'Treasury transfer arm is disabled.'
            )
      )
    + '</div>'
  );

  const input = $(
    '#treasuryWithdrawalJitExecutionConfirmation'
  );

  const button = $(
    '#executeTreasuryWithdrawalJit'
  );

  const update = () => {
    if (!button) return;

    button.disabled = !(
      barriersOpen
      && confirmation
      && String(input?.value || '')
        === confirmation
    );
  };

  input?.addEventListener(
    'input',
    update,
  );

  update();
}



function renderTreasuryWithdrawalExternalExecutionPreview(
  payload
) {
  const element = $(
    '#treasuryWithdrawalExternalExecutionPreview'
  );

  if (!element) return;

  const item = payload?.item || {};
  const preview = (
    payload?.external_execution_preview
  );

  const status = String(
    item.status || ''
  ).toLowerCase();

  const executionVisible = Boolean(
    status === 'jit_ready'
    && preview
  );

  const reconciliationVisible = (
    status === 'withdrawal_submitting'
    || status === 'withdrawal_submitted'
    || status === 'withdrawal_reconciling'
  );

  const doneVisible = (
    status === 'withdrawal_done_unsettled'
  );

  const failedVisible = (
    status === 'withdrawal_failed'
  );

  const visible = (
    executionVisible
    || reconciliationVisible
    || doneVisible
    || failedVisible
  );

  element.classList.toggle(
    'hidden',
    !visible
  );

  if (!visible) {
    element.innerHTML = '';
    return;
  }

  if (reconciliationVisible) {
    element.innerHTML = (
      '<div class="treasury-section-header">'
      + '<div>'
      + '<h3>External withdrawal reconciliation</h3>'
      + '<p>'
      + 'Submission has crossed or may have crossed '
      + 'the Gate write boundary. Do not execute again.'
      + '</p>'
      + '</div>'
      + '</div>'

      + '<div class="treasury-withdrawal-safety-note">'
      + 'Use reconciliation only. It performs Gate reads '
      + 'and never submits a second withdrawal.'
      + '</div>'

      + '<div class="treasury-withdrawal-actions">'
      + '<button '
      + 'type="button" '
      + 'class="button secondary" '
      + 'id="reconcileTreasuryExternalWithdrawal">'
      + 'Reconcile withdrawal'
      + '</button>'
      + '</div>'
    );

    return;
  }

  if (doneVisible) {
    element.innerHTML = (
      '<div class="treasury-section-header">'
      + '<div>'
      + '<h3>External withdrawal confirmed</h3>'
      + '<p>'
      + 'Gate reconciliation is definitive. Ownership '
      + 'settlement remains a separate super-admin step.'
      + '</p>'
      + '</div>'
      + '</div>'
    );

    return;
  }

  if (failedVisible) {
    element.innerHTML = (
      '<div class="treasury-section-header">'
      + '<div>'
      + '<h3>External withdrawal failed</h3>'
      + '<p>'
      + 'This request is terminal. Do not resubmit it.'
      + '</p>'
      + '</div>'
      + '</div>'
    );

    return;
  }

  if (!preview?.available) {
    element.innerHTML = (
      '<strong>'
      + 'External withdrawal preview unavailable'
      + '</strong>'
      + `<p>${escapeHtml(
          preview?.error
          || preview?.reason
          || 'Withdrawal execution data is incomplete.'
        )}</p>`
    );

    return;
  }

  const barriersOpen = Boolean(
    preview.application_barriers_open
  );

  const confirmation = String(
    preview.required_confirmation || ''
  );

  element.innerHTML = (
    '<div class="treasury-section-header">'
    + '<div>'
    + '<h3>External withdrawal execution</h3>'
    + '<p>'
    + 'The server performs a fresh Gate preflight '
    + 'before crossing the withdrawal boundary.'
    + '</p>'
    + '</div>'
    + '</div>'

    + '<div class="treasury-request-grid">'

    + '<div>'
    + '<span>Owner</span>'
    + `<strong>${escapeHtml(
        preview.owner_account_id || '—'
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Amount</span>'
    + `<strong>${escapeHtml(
        treasuryAmount(
          preview.amount,
          preview.currency
        )
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Estimated fee</span>'
    + `<strong>${escapeHtml(
        treasuryAmount(
          preview.estimated_fee,
          preview.currency
        )
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Network</span>'
    + `<strong>${escapeHtml(
        preview.chain || '—'
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Destination</span>'
    + `<strong>${escapeHtml(
        shortTreasuryRequestId(
          preview.destination_id || ''
        )
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Live withdrawal arm</span>'
    + `<strong>${
        preview.live_withdrawals_armed
          ? 'ARMED'
          : 'DISABLED'
      }</strong>`
    + '</div>'

    + '<div>'
    + '<span>Owner allowlist</span>'
    + `<strong>${
        preview.owner_account_live_enabled
          ? 'Allowed'
          : 'Blocked'
      }</strong>`
    + '</div>'

    + '<div>'
    + '<span>Application barriers</span>'
    + `<strong>${
        barriersOpen
          ? 'Open'
          : 'Blocked'
      }</strong>`
    + '</div>'

    + '</div>'

    + '<div class="treasury-withdrawal-safety-note">'
    + 'A fresh server-side preflight must still match '
    + 'the immutable destination, fee and funding '
    + 'snapshot before Gate submission.'
    + '</div>'

    + '<label>'
    + 'Exact money-moving confirmation'
    + `<code>${escapeHtml(
        confirmation || '—'
      )}</code>`
    + '<input '
    + 'id="treasuryExternalWithdrawalConfirmation" '
    + 'type="text" '
    + 'autocomplete="off" '
    + 'spellcheck="false">'
    + '</label>'

    + '<div class="treasury-withdrawal-actions">'
    + '<button '
    + 'type="button" '
    + 'class="button" '
    + 'id="executeTreasuryExternalWithdrawal" '
    + 'disabled>'
    + 'Execute external withdrawal'
    + '</button>'
    + '</div>'

    + '<div class="treasury-withdrawal-safety-note">'
    + (
        barriersOpen
          ? (
              'Application barriers are open. '
              + 'Exact confirmation is still required.'
            )
          : (
              'Execution remains blocked while live '
              + 'external withdrawals are disarmed.'
            )
      )
    + '</div>'
  );

  const input = $(
    '#treasuryExternalWithdrawalConfirmation'
  );

  const button = $(
    '#executeTreasuryExternalWithdrawal'
  );

  const update = () => {
    if (!button) return;

    button.disabled = !(
      barriersOpen
      && confirmation
      && String(input?.value || '')
        === confirmation
    );
  };

  input?.addEventListener(
    'input',
    update,
  );

  update();
}



function renderTreasuryWithdrawalSettlementPreview(
  payload
) {
  const element = $(
    '#treasuryWithdrawalSettlementPreview'
  );

  if (!element) return;

  const item = payload?.item || {};
  const preview = payload?.settlement_preview;

  const status = String(
    item.status || ''
  ).toLowerCase();

  const visible = (
    status === 'withdrawal_done_unsettled'
    || status === 'withdrawal_settled'
  );

  element.classList.toggle(
    'hidden',
    !visible
  );

  if (!visible) {
    element.innerHTML = '';
    return;
  }

  if (status === 'withdrawal_settled') {
    element.innerHTML = (
      '<div class="treasury-section-header">'
      + '<div>'
      + '<h3>Ownership settled</h3>'
      + '<p>'
      + 'The Gate withdrawal and local economic '
      + 'ownership settlement are complete.'
      + '</p>'
      + '</div>'
      + '</div>'
    );

    return;
  }

  const isSuperAdmin = (
    state.adminUser?.role === 'super_admin'
  );

  if (!isSuperAdmin) {
    element.innerHTML = (
      '<div class="treasury-section-header">'
      + '<div>'
      + '<h3>Ownership settlement pending</h3>'
      + '<p>'
      + 'A super administrator must settle the '
      + 'definitive Gate withdrawal.'
      + '</p>'
      + '</div>'
      + '</div>'
    );

    return;
  }

  if (!preview?.available) {
    element.innerHTML = (
      '<strong>Settlement preview unavailable</strong>'
      + `<p>${escapeHtml(
          preview?.error
          || preview?.reason
          || 'Settlement evidence is incomplete.'
        )}</p>`
    );

    return;
  }

  const confirmation = String(
    preview.required_confirmation || ''
  );

  const settlementAllowed = Boolean(
    preview.settlement_allowed
  );

  element.innerHTML = (
    '<div class="treasury-section-header">'
    + '<div>'
    + '<h3>Settle withdrawal ownership</h3>'
    + '<p>'
    + 'Final super-admin accounting step after '
    + 'definitive Gate completion.'
    + '</p>'
    + '</div>'
    + '</div>'

    + '<div class="treasury-request-grid">'

    + '<div>'
    + '<span>Owner</span>'
    + `<strong>${escapeHtml(
        preview.owner_account_id || '—'
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Debit amount</span>'
    + `<strong>${escapeHtml(
        treasuryAmount(
          preview.amount,
          preview.currency
        )
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Gate fee evidence</span>'
    + `<strong>${escapeHtml(
        treasuryAmount(
          (
            preview.gate_fee
            ?? preview.estimated_fee
          ),
          preview.currency
        )
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Gate status</span>'
    + `<strong>${escapeHtml(
        preview.gate_status || '—'
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Gate withdrawal ID</span>'
    + `<strong>${escapeHtml(
        preview.gate_withdrawal_id || '—'
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Order ID</span>'
    + `<strong>${escapeHtml(
        preview.gate_withdraw_order_id || '—'
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Block</span>'
    + `<strong>${escapeHtml(
        preview.gate_block_number || '—'
      )}</strong>`
    + '</div>'

    + '<div>'
    + '<span>Live withdrawal arm</span>'
    + `<strong>${
        preview.withdrawals_live_armed
          ? 'ARMED'
          : 'DISABLED'
      }</strong>`
    + '</div>'

    + '</div>'

    + '<div class="treasury-withdrawal-safety-note">'
    + 'Settlement debits economic ownership by the '
    + 'Gate withdrawal amount. The Gate fee remains '
    + 'evidence and is not an additional ownership debit.'
    + '</div>'

    + '<label>'
    + 'Exact settlement confirmation'
    + `<code>${escapeHtml(
        confirmation || '—'
      )}</code>`
    + '<input '
    + 'id="treasuryWithdrawalSettlementConfirmation" '
    + 'type="text" '
    + 'autocomplete="off" '
    + 'spellcheck="false">'
    + '</label>'

    + '<div class="treasury-withdrawal-actions">'
    + '<button '
    + 'type="button" '
    + 'class="button" '
    + 'id="settleTreasuryWithdrawal" '
    + 'disabled>'
    + 'Settle ownership'
    + '</button>'
    + '</div>'

    + '<div class="treasury-withdrawal-safety-note">'
    + (
        settlementAllowed
          ? (
              'Live withdrawals are disarmed. '
              + 'Settlement may proceed after exact '
              + 'confirmation.'
            )
          : (
              'Settlement is blocked while live '
              + 'withdrawals are armed.'
            )
      )
    + '</div>'
  );

  const input = $(
    '#treasuryWithdrawalSettlementConfirmation'
  );

  const button = $(
    '#settleTreasuryWithdrawal'
  );

  const update = () => {
    if (!button) return;

    button.disabled = !(
      settlementAllowed
      && confirmation
      && String(input?.value || '')
        === confirmation
    );
  };

  input?.addEventListener(
    'input',
    update,
  );

  update();
}


function renderTreasuryWithdrawalRequestDetail(
  payload
) {
  state.treasuryWithdrawalRequestDetail = payload;

  renderTreasuryWithdrawalJitExecutionPreview(
    payload
  );

  renderTreasuryWithdrawalExternalExecutionPreview(
    payload
  );

  renderTreasuryWithdrawalSettlementPreview(
    payload
  );

  const item = payload?.item || {};
  const lock = payload?.operation_lock || null;

  const status = String(
    item.status || 'unknown'
  ).toLowerCase();

  const requestId = String(
    item.request_id || ''
  );

  const address = String(
    item.address || ''
  );

  $('#treasuryWithdrawalRequestSummary').innerHTML = `
    <article class="treasury-request-card">
      <div class="treasury-request-heading">
        <div>
          <h3>
            ${escapeHtml(
              treasuryAmount(
                item.amount,
                item.currency
              )
            )}
          </h3>

          <small>
            External withdrawal lifecycle
          </small>
        </div>

        <span
          class="treasury-status ${
            escapeHtml(
              treasuryWithdrawalRequestStatusClass(
                status
              )
            )
          }"
        >
          ${escapeHtml(status)}
        </span>
      </div>

      <div class="treasury-request-id">
        <span>Request ID</span>
        <strong>${escapeHtml(requestId || '—')}</strong>
      </div>

      <div class="treasury-request-grid">
        <div>
          <span>Economic owner</span>
          <strong>${escapeHtml(
            item.owner_account_id || '—'
          )}</strong>
        </div>

        <div>
          <span>Custody</span>
          <strong>${escapeHtml(
            item.custody_account_id || '—'
          )}</strong>
        </div>

        <div>
          <span>Asset</span>
          <strong>${escapeHtml(
            item.currency || '—'
          )}</strong>
        </div>

        <div>
          <span>Network</span>
          <strong>${escapeHtml(
            item.chain || '—'
          )}</strong>
        </div>

        <div>
          <span>Destination</span>
          <strong>${escapeHtml(
            shortTreasuryRequestId(
              item.destination_id || ''
            )
          )}</strong>
        </div>

        <div>
          <span>Address</span>
          <strong title="${escapeHtml(address)}">
            ${escapeHtml(
              shortTreasuryGateId(address)
            )}
          </strong>
        </div>

        <div>
          <span>Estimated fee</span>
          <strong>${escapeHtml(
            treasuryAmount(
              item.estimated_fee,
              item.currency
            )
          )}</strong>
        </div>

        <div>
          <span>JIT required</span>
          <strong>${
            item.jit_required ? 'Yes' : 'No'
          }</strong>
        </div>

        <div>
          <span>Minimum JIT</span>
          <strong>${escapeHtml(
            treasuryAmount(
              item.minimum_jit_transfer,
              item.currency
            )
          )}</strong>
        </div>

        <div>
          <span>Gate status</span>
          <strong>${escapeHtml(
            item.gate_status || '—'
          )}</strong>
        </div>
      </div>
    </article>
  `;

  const errorBox = $(
    '#treasuryWithdrawalRequestError'
  );

  if (item.error) {
    errorBox.textContent = item.error;
    errorBox.classList.remove('hidden');
  } else {
    errorBox.textContent = '';
    errorBox.classList.add('hidden');
  }

  const lockElement = $(
    '#treasuryWithdrawalLockDetail'
  );

  if (lock) {
    lockElement.innerHTML = (
      '<article class="treasury-lock-card">'
      + '<div class="treasury-lock-field">'
      + '<span>State</span>'
      + `<strong>${escapeHtml(
          lock.state || 'held'
        )}</strong>`
      + '</div>'
      + '<div class="treasury-lock-field">'
      + '<span>Custody</span>'
      + `<strong>${escapeHtml(
          lock.custody_account_id || '—'
        )}</strong>`
      + '</div>'
      + '<div class="treasury-lock-field">'
      + '<span>Currency</span>'
      + `<strong>${escapeHtml(
          lock.currency || '—'
        )}</strong>`
      + '</div>'
      + '</article>'
    );
  } else {
    lockElement.innerHTML = (
      '<div class="treasury-empty">'
      + 'No active withdrawal lock.'
      + '</div>'
    );
  }

  renderTreasuryWithdrawalEvents(
    payload?.events || []
  );

  $('#treasuryWithdrawalRequestJson').textContent = (
    JSON.stringify(item, null, 2)
  );

  const required = (
    treasuryWithdrawalLifecycleConfirmation(item)
  );

  const confirmationBlock = $(
    '#treasuryWithdrawalConfirmationBlock'
  );

  const lifecycleNotice = $(
    '#treasuryWithdrawalLifecycleNotice'
  );

  const actionable = (
    status === 'simulated'
    || status === 'reserved'
    || status === 'confirmed_ready'
  );

  confirmationBlock?.classList.toggle(
    'hidden',
    !actionable
  );

  if ($('#treasuryWithdrawalRequiredConfirmation')) {
    $('#treasuryWithdrawalRequiredConfirmation')
      .textContent = required;
  }

  if ($('#treasuryWithdrawalConfirmation')) {
    $('#treasuryWithdrawalConfirmation').value = '';
  }

  if (lifecycleNotice) {
    if (status === 'simulated') {
      lifecycleNotice.textContent = (
        'Reserve performs a fresh Gate GET-only '
        + 'preflight and acquires the withdrawal '
        + 'custody/currency lock.'
      );

    } else if (status === 'reserved') {
      lifecycleNotice.textContent = (
        'Confirm performs another fresh Gate GET-only '
        + 'preflight. No external withdrawal is '
        + 'submitted.'
      );

    } else if (status === 'confirmed_ready') {
      lifecycleNotice.textContent = (
        'Prepare JIT performs another fresh Gate '
        + 'GET-only preflight and persists the '
        + 'deterministic JIT plan. No transfer is '
        + 'submitted.'
      );

    } else if (
      status === 'withdrawal_done_unsettled'
    ) {
      lifecycleNotice.textContent = (
        'Gate withdrawal is definitively complete. '
        + 'Economic ownership settlement is pending.'
      );

    } else if (
      status === 'withdrawal_settled'
    ) {
      lifecycleNotice.textContent = (
        'Withdrawal lifecycle complete. Gate withdrawal '
        + 'and economic ownership settlement are complete.'
      );

    } else if (
      status === 'withdrawal_failed'
    ) {
      lifecycleNotice.textContent = (
        'Withdrawal failed definitively. This request '
        + 'is terminal and cannot be resubmitted.'
      );

    } else {
      lifecycleNotice.textContent = (
        'This withdrawal request is view-only in the '
        + 'current Treasury UI.'
      );
    }
  }

  updateTreasuryWithdrawalLifecycleButtons();
}


async function openTreasuryWithdrawalRequestDetail(
  requestId
) {
  if (!requestId) return;

  try {
    state.treasuryWithdrawalRequiredConfirmation = '';

    const payload = await adminApi(
      `/api/treasury/withdrawals/requests/${
        encodeURIComponent(requestId)
      }`
    );

    renderTreasuryWithdrawalRequestDetail(payload);

    const dialog = $(
      '#treasuryWithdrawalRequestDialog'
    );

    const content = dialog?.querySelector(
      '.treasury-request-content'
    );

    if (content) {
      content.scrollTop = 0;
    }

    if (dialog && !dialog.open) {
      dialog.showModal();
    }

  } catch (error) {
    showToast(
      treasuryErrorMessage(error),
      true,
    );
  }
}


async function refreshTreasuryWithdrawalRequestDetail(
  requestId
) {
  const payload = await adminApi(
    `/api/treasury/withdrawals/requests/${
      encodeURIComponent(requestId)
    }`
  );

  renderTreasuryWithdrawalRequestDetail(payload);
}


async function reserveCurrentTreasuryWithdrawal() {
  const payload = (
    state.treasuryWithdrawalRequestDetail
  );

  const item = payload?.item || {};

  if (
    String(item.status || '').toLowerCase()
    !== 'simulated'
  ) {
    return;
  }

  const requestId = String(
    item.request_id || ''
  );

  const confirmation = String(
    $('#treasuryWithdrawalConfirmation')?.value
    || ''
  );

  const required = (
    treasuryWithdrawalReserveConfirmation(item)
  );

  if (
    !requestId
    || confirmation !== required
  ) {
    return;
  }

  const button = $(
    '#reserveTreasuryWithdrawalRequest'
  );

  button.disabled = true;
  button.textContent = 'Reserving…';

  try {
    const result = await adminApi(
      `/api/treasury/withdrawals/requests/${
        encodeURIComponent(requestId)
      }/reserve`,
      {
        method: 'POST',
        body: JSON.stringify({
          confirmation,
        }),
      },
    );

    if (result.gate_write_performed) {
      throw new Error(
        'Safety invariant failed: reservation '
        + 'reported a Gate write.'
      );
    }

    state.treasuryWithdrawalRequiredConfirmation = (
      String(result.required_confirmation || '')
    );

    showToast(
      'Withdrawal reserved. No Gate write performed.'
    );

    await refreshTreasuryWithdrawalRequestDetail(
      requestId
    );

    await loadTreasuryOverview({
      quiet: true,
    });

  } catch (error) {
    showToast(
      treasuryErrorMessage(error),
      true,
    );

    try {
      await refreshTreasuryWithdrawalRequestDetail(
        requestId
      );

      await loadTreasuryOverview({
        quiet: true,
      });
    } catch (_refreshError) {
      // Preserve the original operation error.
    }

  } finally {
    button.textContent = 'Reserve withdrawal';
    updateTreasuryWithdrawalLifecycleButtons();
  }
}


async function confirmCurrentTreasuryWithdrawal() {
  const payload = (
    state.treasuryWithdrawalRequestDetail
  );

  const item = payload?.item || {};

  if (
    String(item.status || '').toLowerCase()
    !== 'reserved'
  ) {
    return;
  }

  const requestId = String(
    item.request_id || ''
  );

  const confirmation = String(
    $('#treasuryWithdrawalConfirmation')?.value
    || ''
  );

  const required = (
    treasuryWithdrawalLifecycleConfirmation(item)
  );

  if (
    !requestId
    || confirmation !== required
  ) {
    return;
  }

  const button = $(
    '#confirmTreasuryWithdrawalRequest'
  );

  button.disabled = true;
  button.textContent = 'Confirming…';

  try {
    const result = await adminApi(
      `/api/treasury/withdrawals/requests/${
        encodeURIComponent(requestId)
      }/confirm`,
      {
        method: 'POST',
        body: JSON.stringify({
          confirmation,
        }),
      },
    );

    if (result.gate_write_performed) {
      throw new Error(
        'Safety invariant failed: confirmation '
        + 'reported a Gate write.'
      );
    }

    state.treasuryWithdrawalRequiredConfirmation = '';

    showToast(
      'Withdrawal confirmed. No Gate write performed.'
    );

    await refreshTreasuryWithdrawalRequestDetail(
      requestId
    );

    await loadTreasuryOverview({
      quiet: true,
    });

  } catch (error) {
    showToast(
      treasuryErrorMessage(error),
      true,
    );

    try {
      await refreshTreasuryWithdrawalRequestDetail(
        requestId
      );

      await loadTreasuryOverview({
        quiet: true,
      });
    } catch (_refreshError) {
      // A blocked confirmation may have changed state.
    }

  } finally {
    button.textContent = 'Confirm withdrawal';
    updateTreasuryWithdrawalLifecycleButtons();
  }
}



async function prepareCurrentTreasuryWithdrawalJit() {
  const payload = (
    state.treasuryWithdrawalRequestDetail
  );

  const item = payload?.item || {};

  if (
    String(item.status || '').toLowerCase()
    !== 'confirmed_ready'
  ) {
    return;
  }

  const requestId = String(
    item.request_id || ''
  );

  const confirmation = String(
    $('#treasuryWithdrawalConfirmation')?.value
    || ''
  );

  const required = (
    treasuryWithdrawalJitPrepareConfirmation(item)
  );

  if (
    !requestId
    || confirmation !== required
  ) {
    return;
  }

  const button = $(
    '#prepareTreasuryWithdrawalJit'
  );

  button.disabled = true;
  button.textContent = 'Preparing JIT…';

  try {
    const result = await adminApi(
      `/api/treasury/withdrawals/requests/${
        encodeURIComponent(requestId)
      }/jit/prepare`,
      {
        method: 'POST',
        body: JSON.stringify({
          confirmation,
        }),
      },
    );

    if (
      result.gate_write_performed !== false
      || result.transfer_audit_created !== false
    ) {
      throw new Error(
        'Safety invariant failed: JIT preparation '
        + 'reported a money-movement write.'
      );
    }

    if (
      result.status !== 'jit_prepared'
      || result.jit_execution_enabled !== false
      || result.executable !== false
    ) {
      throw new Error(
        'Safety invariant failed: unexpected '
        + 'JIT preparation response.'
      );
    }

    showToast(
      'JIT plan prepared. No Gate write performed.'
    );

    await refreshTreasuryWithdrawalRequestDetail(
      requestId
    );

    await loadTreasuryOverview({
      quiet: true,
    });

  } catch (error) {
    showToast(
      treasuryErrorMessage(error),
      true,
    );

    try {
      await refreshTreasuryWithdrawalRequestDetail(
        requestId
      );

      await loadTreasuryOverview({
        quiet: true,
      });
    } catch (_refreshError) {
      // Fresh preflight may have blocked and changed state.
    }

  } finally {
    button.textContent = 'Prepare JIT';
    updateTreasuryWithdrawalLifecycleButtons();
  }
}



async function executeCurrentTreasuryWithdrawalJit() {
  const payload = (
    state.treasuryWithdrawalRequestDetail
  );

  const item = payload?.item || {};
  const preview = (
    payload?.jit_execution_preview
    || {}
  );

  if (
    String(item.status || '').toLowerCase()
    !== 'jit_prepared'
    || !preview.application_barriers_open
  ) {
    return;
  }

  const requestId = String(
    item.request_id || ''
  );

  const required = String(
    preview.required_confirmation || ''
  );

  const confirmation = String(
    $('#treasuryWithdrawalJitExecutionConfirmation')
      ?.value
    || ''
  );

  if (
    !requestId
    || !required
    || confirmation !== required
  ) {
    return;
  }

  const button = $(
    '#executeTreasuryWithdrawalJit'
  );

  if (button) {
    button.disabled = true;
    button.textContent = 'Executing JIT…';
  }

  try {
    const result = await adminApi(
      `/api/treasury/withdrawals/requests/${
        encodeURIComponent(requestId)
      }/jit/execute`,
      {
        method: 'POST',
        body: JSON.stringify({
          confirmation,
        }),
      },
    );

    showToast(
      result.gate_write_performed
        ? 'JIT transfer submitted. Verify definitive state.'
        : 'JIT stage completed without a Gate write.'
    );

  } catch (error) {
    showToast(
      treasuryErrorMessage(error),
      true,
    );

    // Never retry automatically. The server state decides
    // whether reconciliation is required.
  }

  try {
    await refreshTreasuryWithdrawalRequestDetail(
      requestId
    );

    await loadTreasuryOverview({
      quiet: true,
    });
  } catch (_refreshError) {
    // Preserve the money-movement outcome for manual review.
  }
}


async function reconcileCurrentTreasuryWithdrawalJit() {
  const payload = (
    state.treasuryWithdrawalRequestDetail
  );

  const item = payload?.item || {};

  const status = String(
    item.status || ''
  ).toLowerCase();

  if (
    status !== 'jit_executing'
    && status !== 'jit_reconciling'
  ) {
    return;
  }

  const requestId = String(
    item.request_id || ''
  );

  if (!requestId) return;

  const button = $(
    '#reconcileTreasuryWithdrawalJit'
  );

  if (button) {
    button.disabled = true;
    button.textContent = 'Reconciling…';
  }

  try {
    const result = await adminApi(
      `/api/treasury/withdrawals/requests/${
        encodeURIComponent(requestId)
      }/jit/reconcile`,
      {
        method: 'POST',
      },
    );

    if (result.gate_write_performed) {
      throw new Error(
        'Safety invariant failed: JIT reconciliation '
        + 'reported a Gate write.'
      );
    }

    showToast(
      'JIT reconciliation completed.'
    );

  } catch (error) {
    showToast(
      treasuryErrorMessage(error),
      true,
    );
  }

  try {
    await refreshTreasuryWithdrawalRequestDetail(
      requestId
    );

    await loadTreasuryOverview({
      quiet: true,
    });
  } catch (_refreshError) {
    // Leave the visible state unchanged for manual review.
  }
}



async function executeCurrentTreasuryExternalWithdrawal() {
  const payload = (
    state.treasuryWithdrawalRequestDetail
  );

  const item = payload?.item || {};
  const preview = (
    payload?.external_execution_preview
    || {}
  );

  if (
    String(item.status || '').toLowerCase()
      !== 'jit_ready'
    || !preview.application_barriers_open
  ) {
    return;
  }

  const requestId = String(
    item.request_id || ''
  );

  const required = String(
    preview.required_confirmation || ''
  );

  const confirmation = String(
    $('#treasuryExternalWithdrawalConfirmation')
      ?.value
    || ''
  );

  if (
    !requestId
    || !required
    || confirmation !== required
  ) {
    return;
  }

  const button = $(
    '#executeTreasuryExternalWithdrawal'
  );

  if (button) {
    button.disabled = true;
    button.textContent = 'Submitting withdrawal…';
  }

  try {
    const result = await adminApi(
      `/api/treasury/withdrawals/requests/${
        encodeURIComponent(requestId)
      }/execute`,
      {
        method: 'POST',
        body: JSON.stringify({
          confirmation,
        }),
      },
    );

    showToast(
      result.gate_write_performed
        ? (
            'Withdrawal submission crossed the Gate '
            + 'write boundary. Reconciliation required.'
          )
        : (
            'Withdrawal stage completed without '
            + 'a Gate write.'
          )
    );

  } catch (error) {
    showToast(
      treasuryErrorMessage(error),
      true,
    );

    // Never retry automatically. Refresh the persisted
    // state and use reconciliation if submission began.
  }

  try {
    await refreshTreasuryWithdrawalRequestDetail(
      requestId
    );

    await loadTreasuryOverview({
      quiet: true,
    });
  } catch (_refreshError) {
    // Preserve visible state for manual review.
  }
}


async function reconcileCurrentTreasuryExternalWithdrawal() {
  const payload = (
    state.treasuryWithdrawalRequestDetail
  );

  const item = payload?.item || {};

  const status = String(
    item.status || ''
  ).toLowerCase();

  if (
    status !== 'withdrawal_submitting'
    && status !== 'withdrawal_submitted'
    && status !== 'withdrawal_reconciling'
  ) {
    return;
  }

  const requestId = String(
    item.request_id || ''
  );

  if (!requestId) return;

  const button = $(
    '#reconcileTreasuryExternalWithdrawal'
  );

  if (button) {
    button.disabled = true;
    button.textContent = 'Reconciling…';
  }

  try {
    const result = await adminApi(
      `/api/treasury/withdrawals/requests/${
        encodeURIComponent(requestId)
      }/reconcile`,
      {
        method: 'POST',
      },
    );

    if (result.gate_write_performed) {
      throw new Error(
        'Safety invariant failed: withdrawal '
        + 'reconciliation reported a Gate write.'
      );
    }

    showToast(
      'Withdrawal reconciliation completed.'
    );

  } catch (error) {
    showToast(
      treasuryErrorMessage(error),
      true,
    );
  }

  try {
    await refreshTreasuryWithdrawalRequestDetail(
      requestId
    );

    await loadTreasuryOverview({
      quiet: true,
    });
  } catch (_refreshError) {
    // Leave request available for manual review.
  }
}



async function settleCurrentTreasuryWithdrawal() {
  const payload = (
    state.treasuryWithdrawalRequestDetail
  );

  const item = payload?.item || {};
  const preview = (
    payload?.settlement_preview || {}
  );

  if (
    state.adminUser?.role !== 'super_admin'
    || String(item.status || '').toLowerCase()
      !== 'withdrawal_done_unsettled'
    || !preview.settlement_allowed
  ) {
    return;
  }

  const requestId = String(
    item.request_id || ''
  );

  const required = String(
    preview.required_confirmation || ''
  );

  const confirmation = String(
    $('#treasuryWithdrawalSettlementConfirmation')
      ?.value
    || ''
  );

  if (
    !requestId
    || !required
    || confirmation !== required
  ) {
    return;
  }

  const button = $('#settleTreasuryWithdrawal');

  if (button) {
    button.disabled = true;
    button.textContent = 'Settling…';
  }

  try {
    const result = await adminApi(
      `/api/treasury/withdrawals/requests/${
        encodeURIComponent(requestId)
      }/settle`,
      {
        method: 'POST',
        body: JSON.stringify({
          confirmation,
        }),
      },
    );

    if (result.gate_write_performed) {
      throw new Error(
        'Safety invariant failed: settlement '
        + 'reported a Gate write.'
      );
    }

    if (
      result.status !== 'withdrawal_settled'
    ) {
      throw new Error(
        'Settlement did not reach withdrawal_settled.'
      );
    }

    showToast(
      result.state_changed
        ? 'Withdrawal ownership settled.'
        : 'Withdrawal was already settled.'
    );

  } catch (error) {
    showToast(
      treasuryErrorMessage(error),
      true,
    );
  }

  try {
    await refreshTreasuryWithdrawalRequestDetail(
      requestId
    );

    await loadTreasuryOverview({
      quiet: true,
    });
  } catch (_refreshError) {
    // Preserve settlement outcome for manual review.
  }
}


function renderTreasuryOwnershipBalances() {
  const body = $(
    '#treasuryOwnershipBalanceBody'
  );

  if (!body) return;

  const rows = (
    state.treasuryOwnershipBalances || []
  );

  const labels = applyTreasuryOwnershipLabels(
    rows
  );

  if (!rows.length) {
    body.innerHTML = (
      '<tr>'
      + '<td colspan="4" class="empty-state">'
      + escapeHtml(labels.empty)
      + '</td>'
      + '</tr>'
    );

    if ($('#treasuryOwnershipBalanceCount')) {
      $('#treasuryOwnershipBalanceCount')
        .textContent = '0 balances';
    }

    return;
  }

  body.innerHTML = rows.map(item => {
    return (
      '<tr>'
      + `<td><strong>${escapeHtml(
          item.owner_account_id || '—'
        )}</strong></td>`
      + `<td>${escapeHtml(
          item.custody_account_id || '—'
        )}</td>`
      + `<td>${escapeHtml(
          item.currency || '—'
        )}</td>`
      + `<td><strong>${escapeHtml(
          treasuryAmount(
            item.main_held_amount,
            item.currency,
          )
        )}</strong></td>`
      + '</tr>'
    );
  }).join('');

  if ($('#treasuryOwnershipBalanceCount')) {
    $('#treasuryOwnershipBalanceCount')
      .textContent = (
        `${rows.length} ${
          rows.length === 1
            ? 'balance'
            : 'balances'
        }`
      );
  }
}


function renderTreasuryOwnershipLedger() {
  const body = $(
    '#treasuryOwnershipLedgerBody'
  );

  if (!body) return;

  const rows = (
    state.treasuryOwnershipLedger || []
  );

  if (!rows.length) {
    body.innerHTML = (
      '<tr>'
      + '<td colspan="7" class="empty-state">'
      + 'No ownership ledger entries.'
      + '</td>'
      + '</tr>'
    );

    if ($('#treasuryOwnershipLedgerCount')) {
      $('#treasuryOwnershipLedgerCount')
        .textContent = '0 entries';
    }

    return;
  }

  body.innerHTML = rows.map(item => {
    const requestId = String(
      item.source_request_id || ''
    );

    return (
      '<tr>'
      + `<td>${escapeHtml(
          fmtDate(item.created_at)
        )}</td>`
      + `<td><strong>${escapeHtml(
          item.owner_account_id || '—'
        )}</strong></td>`
      + `<td>${escapeHtml(
          item.custody_account_id || '—'
        )}</td>`
      + `<td>${escapeHtml(
          item.currency || '—'
        )}</td>`
      + `<td><strong>${escapeHtml(
          treasurySignedAmount(
            item.delta_amount,
            item.currency,
          )
        )}</strong></td>`
      + `<td>${escapeHtml(
          treasuryOwnershipEntryType(
            item.entry_type
          )
        )}</td>`
      + `<td>${
          requestId
            ? `<button
                 type="button"
                 class="treasury-request-link"
                 data-treasury-request="${escapeHtml(
                   requestId
                 )}"
               >${escapeHtml(
                 shortTreasuryId(requestId)
               )}</button>`
            : '—'
        }</td>`
      + '</tr>'
    );
  }).join('');

  if ($('#treasuryOwnershipLedgerCount')) {
    $('#treasuryOwnershipLedgerCount')
      .textContent = (
        `${rows.length} ${
          rows.length === 1
            ? 'entry'
            : 'entries'
        }`
      );
  }
}


function renderTreasuryLocks() {
  const container = $('#treasuryLockList');

  if (!container) return;

  const rows = state.treasuryLocks || [];

  if (!rows.length) {
    container.innerHTML = (
      '<div class="treasury-empty">'
      + 'No active Treasury locks.'
      + '</div>'
    );

    renderTreasurySafety();
    return;
  }

  container.innerHTML = rows.map(lock => {
    const requestId = String(
      lock.owner_request_id || ''
    );

    return (
      '<article class="treasury-lock-card">'
      + '<div class="treasury-lock-field">'
      + '<span>Source</span>'
      + `<strong>${escapeHtml(
          lock.source_account_id || '—'
        )}</strong>`
      + '</div>'
      + '<div class="treasury-lock-field">'
      + '<span>Currency</span>'
      + `<strong>${escapeHtml(
          lock.currency || '—'
        )}</strong>`
      + '</div>'
      + '<div class="treasury-lock-field">'
      + '<span>Request</span>'
      + `<strong title="${escapeHtml(requestId)}">`
      + `${escapeHtml(
          shortTreasuryRequestId(requestId)
        )}</strong>`
      + '</div>'
      + (
        requestId
          ? (
              `<button type="button" `
              + `class="button secondary" `
              + `data-treasury-request="${
                  escapeHtml(requestId)
                }">`
              + 'Review'
              + '</button>'
            )
          : ''
      )
      + '</article>'
    );
  }).join('');

  renderTreasurySafety();
}


function renderTreasuryTransfers() {
  const body = $('#treasuryActivityBody');

  if (!body) return;

  const rows = state.treasuryTransfers || [];

  if (!rows.length) {
    body.innerHTML = (
      '<tr>'
      + '<td colspan="9" class="empty-state">'
      + 'No Treasury transfer activity recorded.'
      + '</td>'
      + '</tr>'
    );

    if ($('#treasuryActivityCount')) {
      $('#treasuryActivityCount').textContent = (
        '0 records'
      );
    }

    return;
  }

  body.innerHTML = rows.map(item => {
    const requestId = String(
      item.request_id || ''
    );

    const mode = item.simulation
      ? 'simulation'
      : 'live';

    const status = String(
      item.status || 'unknown'
    ).toLowerCase();

    const gateId = String(
      item.gate_transfer_id || ''
    );

    return (
      '<tr>'
      + `<td>${escapeHtml(
          fmtDate(item.created_at)
        )}</td>`
      + `<td><span class="treasury-type">${escapeHtml(
          treasuryOperationType(item)
        )}</span></td>`
      + `<td><strong>${escapeHtml(
          item.source_account_id || '—'
        )}</strong></td>`
      + `<td>${escapeHtml(
          item.destination_account_id || '—'
        )}</td>`
      + `<td>${escapeHtml(
          treasuryAmount(
            item.amount,
            item.currency
          )
        )}</td>`
      + '<td>'
      + `<span class="treasury-mode ${
          escapeHtml(mode)
        }">${escapeHtml(mode)}</span>`
      + '</td>'
      + '<td>'
      + `<span class="treasury-status ${
          escapeHtml(
            treasuryStatusClass(status)
          )
        }">${escapeHtml(status)}</span>`
      + '</td>'
      + `<td title="${escapeHtml(gateId)}">`
      + `${escapeHtml(
          shortTreasuryGateId(gateId)
        )}</td>`
      + '<td>'
      + `<button type="button" `
      + `class="treasury-request-button" `
      + `data-treasury-request="${
          escapeHtml(requestId)
        }" `
      + `title="${escapeHtml(requestId)}">`
      + `${escapeHtml(
          shortTreasuryRequestId(requestId)
        )}`
      + '</button>'
      + '</td>'
      + '</tr>'
    );
  }).join('');

  if ($('#treasuryActivityCount')) {
    $('#treasuryActivityCount').textContent = (
      `${rows.length} recent record${
        rows.length === 1 ? '' : 's'
      }`
    );
  }
}


function renderTreasuryReconciliations(rows) {
  const element = $(
    '#treasuryReconciliationHistory'
  );

  if (!element) return;

  if (!rows?.length) {
    element.innerHTML = (
      '<div class="treasury-empty">'
      + 'No reconciliation has been recorded.'
      + '</div>'
    );

    return;
  }

  element.innerHTML = rows.map(row => (
    '<article class="treasury-history-card">'
    + '<div class="treasury-history-head">'
    + `<strong>${escapeHtml(
        reconciliationLabel(row.outcome)
      )}</strong>`
    + `<span class="treasury-status ${
        escapeHtml(
          treasuryStatusClass(row.outcome)
        )
      }">${escapeHtml(
        row.confidence || 'inconclusive'
      )}</span>`
    + '</div>'
    + `<p>${escapeHtml(
        row.summary || '—'
      )}</p>`
    + '<div class="treasury-history-meta">'
    + `Gate status: ${escapeHtml(
        row.gate_status || '—'
      )}`
    + ' · '
    + `TX: ${escapeHtml(
        row.tx_id || '—'
      )}`
    + ' · '
    + `${escapeHtml(
        fmtDate(row.created_at)
      )}`
    + '</div>'
    + '</article>'
  )).join('');
}


function renderTreasuryLockResolutions(rows) {
  const element = $(
    '#treasuryLockResolutionHistory'
  );

  if (!element) return;

  if (!rows?.length) {
    element.innerHTML = (
      '<div class="treasury-empty">'
      + 'No manual lock-resolution decisions.'
      + '</div>'
    );

    return;
  }

  element.innerHTML = rows.map(row => (
    '<article class="treasury-history-card">'
    + '<div class="treasury-history-head">'
    + `<strong>${escapeHtml(
        reconciliationLabel(row.decision)
      )}</strong>`
    + `<span>${escapeHtml(
        row.username || '—'
      )}</span>`
    + '</div>'
    + `<p>${escapeHtml(
        row.reason || '—'
      )}</p>`
    + '<div class="treasury-history-meta">'
    + `Prior request: ${escapeHtml(
        row.prior_request_status || '—'
      )}`
    + ' · '
    + `Prior lock: ${escapeHtml(
        row.prior_lock_state || '—'
      )}`
    + ' · '
    + `Reconciliation: ${escapeHtml(
        reconciliationLabel(
          row.reconciliation_outcome
        )
      )}`
    + ' · '
    + `${escapeHtml(
        fmtDate(row.created_at)
      )}`
    + '</div>'
    + '</article>'
  )).join('');
}


function treasuryManualReleaseEligible(payload) {
  const item = payload?.item || {};
  const lock = payload?.operation_lock || null;
  const reconciliations = (
    payload?.reconciliations || []
  );

  const hasInconclusive = (
    reconciliations.length > 0
    && reconciliations.some(
      row => String(
        row.confidence || ''
      ).toLowerCase() === 'inconclusive'
    )
  );

  return Boolean(
    state.adminUser?.role === 'super_admin'
    && String(item.status || '').toLowerCase()
      === 'uncertain'
    && lock
    && String(lock.state || '').toLowerCase()
      === 'held'
    && hasInconclusive
    && !state.health?.treasury_transfers_enabled
  );
}


function updateTreasuryReleaseButton() {
  const detail = state.treasuryRequestDetail;
  const item = detail?.item || {};
  const requestId = String(
    item.request_id || ''
  );

  const required = (
    `RELEASE TREASURY LOCK ${requestId}`
  );

  const confirmation = String(
    $('#treasuryReleaseConfirmation')?.value
    || ''
  );

  const reason = String(
    $('#treasuryReleaseReason')?.value
    || ''
  ).trim();

  const button = $('#releaseTreasuryLock');

  if (!button) return;

  button.disabled = !(
    treasuryManualReleaseEligible(detail)
    && confirmation === required
    && reason.length >= 20
  );
}


function renderTreasuryRequestDetail(payload) {
  state.treasuryRequestDetail = payload;

  const item = payload?.item || {};
  const lock = payload?.operation_lock || null;

  const status = String(
    item.status || 'unknown'
  ).toLowerCase();

  const mode = item.simulation
    ? 'Simulation'
    : 'Live';

  const lockText = lock
    ? `${lock.state || 'held'} · ${
        lock.source_account_id || '—'
      } ${lock.currency || ''}`
    : 'No active lock';

  $('#treasuryRequestSummary').innerHTML = `
    <article class="treasury-request-card">
      <div class="treasury-request-heading">
        <div>
          <h3>
            ${escapeHtml(
              treasuryAmount(
                item.amount,
                item.currency
              )
            )}
          </h3>
          <small>
            ${escapeHtml(mode)} transfer
          </small>
        </div>

        <span
          class="treasury-status ${
            escapeHtml(
              treasuryStatusClass(status)
            )
          }"
        >
          ${escapeHtml(status)}
        </span>
      </div>

      <div class="treasury-request-id">
        <span>Request ID</span>
        <strong>
          ${escapeHtml(
            item.request_id || '—'
          )}
        </strong>
      </div>

      <div class="treasury-request-grid">
        <div>
          <span>Type</span>
          <strong>
            ${escapeHtml(
              treasuryOperationType(item)
            )}
          </strong>
        </div>

        <div>
          <span>Source</span>
          <strong>
            ${escapeHtml(
              item.source_account_id || '—'
            )}
          </strong>
        </div>

        <div>
          <span>Destination</span>
          <strong>
            ${escapeHtml(
              item.destination_account_id || '—'
            )}
          </strong>
        </div>

        <div>
          <span>User</span>
          <strong>
            ${escapeHtml(
              item.username || '—'
            )}
          </strong>
        </div>

        <div>
          <span>Gate transfer ID</span>
          <strong>
            ${escapeHtml(
              item.gate_transfer_id || '—'
            )}
          </strong>
        </div>

        <div>
          <span>Client order ID</span>
          <strong>
            ${escapeHtml(
              item.client_order_id || '—'
            )}
          </strong>
        </div>

        <div>
          <span>Operation lock</span>
          <strong>
            ${escapeHtml(lockText)}
          </strong>
        </div>
      </div>

      <div class="treasury-request-times">
        <div>
          <span>Created</span>
          <strong>
            ${escapeHtml(
              fmtDate(item.created_at)
            )}
          </strong>
        </div>

        <div>
          <span>Updated</span>
          <strong>
            ${escapeHtml(
              fmtDate(item.updated_at)
            )}
          </strong>
        </div>

        <div>
          <span>Completed</span>
          <strong>
            ${
              item.completed_at
                ? escapeHtml(
                    fmtDate(item.completed_at)
                  )
                : '—'
            }
          </strong>
        </div>
      </div>
    </article>
  `;

  const errorBox = $('#treasuryRequestError');

  if (item.error) {
    errorBox.textContent = item.error;
    errorBox.classList.remove('hidden');
  } else {
    errorBox.textContent = '';
    errorBox.classList.add('hidden');
  }

  renderTreasuryReconciliations(
    payload?.reconciliations || []
  );

  renderTreasuryLockResolutions(
    payload?.lock_resolutions || []
  );

  $('#treasuryRequestJson').textContent = (
    JSON.stringify(
      item.request || {},
      null,
      2,
    )
  );

  $('#treasuryResponseJson').textContent = (
    JSON.stringify(
      item.response || {},
      null,
      2,
    )
  );

  const terminal = [
    'success',
    'failed',
    'rejected',
    'blocked',
  ].includes(status);

  const reconcileButton = $(
    '#reconcileTreasuryRequest'
  );

  reconcileButton?.classList.toggle(
    'hidden',
    Boolean(item.simulation || terminal)
  );

  const releaseSection = $(
    '#treasuryManualReleaseSection'
  );

  const releaseEligible = (
    treasuryManualReleaseEligible(payload)
  );

  releaseSection?.classList.toggle(
    'hidden',
    !releaseEligible
  );

  const required = (
    `RELEASE TREASURY LOCK ${
      item.request_id || ''
    }`
  );

  if ($('#treasuryReleaseRequired')) {
    $('#treasuryReleaseRequired').textContent = (
      required
    );
  }

  if ($('#treasuryReleaseReason')) {
    $('#treasuryReleaseReason').value = '';
  }

  if ($('#treasuryReleaseConfirmation')) {
    $('#treasuryReleaseConfirmation').value = '';
  }

  updateTreasuryReleaseButton();
}


async function loadTreasuryOverview(
  {
    quiet = false,
  } = {},
) {
  if (
    !state.adminUser
    || !state.adminAuthorization
  ) {
    state.treasuryTransfers = [];
    state.treasuryLocks = [];
    state.treasuryOwnershipBalances = [];
    state.treasuryOwnershipLedger = [];
    state.treasuryWithdrawalDestinations = [];
    state.treasuryWithdrawalRequests = [];
    state.treasuryWithdrawalPreflight = null;
    state.treasuryUserTransferParticipants = [];
    state.treasuryUserTransfersEnabled = false;
    state.treasuryUserTransferPreview = null;
    state.treasuryUserTransferExecutionAttempted = false;

    renderTreasuryTransfers();
    renderTreasuryLocks();
    renderTreasuryOwnershipBalances();
    renderTreasuryOwnershipLedger();
    renderTreasuryWithdrawalDestinations();
    renderTreasuryWithdrawalRequests();
    renderTreasuryWithdrawalPreflight();
    renderTreasuryUserTransferParticipants();
    renderTreasuryUserTransferPreview();
    return;
  }

  const button = $('#refreshTreasury');
  const errorBox = $('#treasuryError');

  if (button) {
    button.disabled = true;
    button.textContent = 'Loading…';
  }

  errorBox?.classList.add('hidden');

  try {
    const [
      health,
      userTransferParticipants,
      requests,
      locks,
      ownershipBalances,
      ownershipLedger,
      withdrawalDestinations,
      withdrawalRequests,
    ] = await Promise.all([
      api('/api/health'),
      adminApi(
        '/api/treasury/user-transfers/participants'
      ),
      adminApi(
        '/api/treasury/transfers/requests?limit=50'
      ),
      adminApi(
        '/api/treasury/transfers/locks'
      ),
      adminApi(
        '/api/treasury/ownership/balances'
      ),
      adminApi(
        '/api/treasury/ownership/ledger?limit=200'
      ),
      adminApi(
        '/api/treasury/withdrawals/'
        + 'destinations?status=approved&limit=100'
      ),
      adminApi(
        '/api/treasury/withdrawals/'
        + 'requests?limit=50'
      ),
    ]);

    state.health = health;

    state.treasuryUserTransferParticipants = (
      userTransferParticipants.items
      || userTransferParticipants.participants
      || []
    );

    state.treasuryUserTransfersEnabled = Boolean(
      userTransferParticipants.user_transfers_enabled
    );

    state.treasuryTransfers = (
      requests.items || []
    );

    state.treasuryLocks = (
      locks.items || []
    );

    state.treasuryOwnershipBalances = (
      ownershipBalances.items || []
    );

    state.treasuryOwnershipLedger = (
      ownershipLedger.items || []
    );

    state.treasuryWithdrawalDestinations = (
      withdrawalDestinations.items || []
    );

    state.treasuryWithdrawalRequests = (
      withdrawalRequests.items || []
    );

    renderTreasurySafety();
    renderTreasuryOwnershipBalances();
    renderTreasuryOwnershipLedger();
    renderTreasuryWithdrawalDestinations();
    renderTreasuryWithdrawalRequests();
    renderTreasuryWithdrawalPreflight();
    renderTreasuryUserTransferParticipants();
    renderTreasuryUserTransferPreview();
    renderTreasuryLocks();
    renderTreasuryTransfers();

  } catch (error) {
    const message = treasuryErrorMessage(error);

    if (errorBox) {
      errorBox.textContent = message;
      errorBox.classList.remove('hidden');
    }

    if (!quiet) {
      showToast(message, true);
    }

  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = 'Refresh Treasury';
    }
  }
}


async function openTreasuryRequestDetail(
  requestId,
) {
  if (!requestId) return;

  try {
    const payload = await adminApi(
      `/api/treasury/transfers/requests/${
        encodeURIComponent(requestId)
      }`
    );

    renderTreasuryRequestDetail(payload);

    const dialog = $('#treasuryRequestDialog');

    dialog.scrollTop = 0;

    const content = dialog.querySelector(
      '.treasury-request-content'
    );

    if (content) {
      content.scrollTop = 0;
    }

    if (!dialog.open) {
      dialog.showModal();
    }

    dialog.scrollTop = 0;

  } catch (error) {
    showToast(
      treasuryErrorMessage(error),
      true,
    );
  }
}


async function reconcileCurrentTreasuryRequest() {
  const payload = state.treasuryRequestDetail;
  const item = payload?.item || {};

  if (!item.request_id) return;

  const button = $('#reconcileTreasuryRequest');

  button.disabled = true;
  button.textContent = 'Reconciling…';

  try {
    const requestId = item.request_id;

    const result = await adminApi(
      `/api/treasury/transfers/${
        encodeURIComponent(requestId)
      }/reconcile`,
      {
        method: 'POST',
      },
    );

    showToast(
      `Treasury reconciliation: ${
        reconciliationLabel(
          result.reconciliation?.outcome
          || result.status
        )
      }.`
    );

    const refreshed = await adminApi(
      `/api/treasury/transfers/requests/${
        encodeURIComponent(requestId)
      }`
    );

    renderTreasuryRequestDetail(refreshed);

    await loadTreasuryOverview({
      quiet: true,
    });

  } catch (error) {
    showToast(
      treasuryErrorMessage(error),
      true,
    );

  } finally {
    button.disabled = false;
    button.textContent = 'Reconcile with Gate';
  }
}


async function releaseCurrentTreasuryLock() {
  const payload = state.treasuryRequestDetail;
  const item = payload?.item || {};

  if (!item.request_id) return;

  const requestId = String(item.request_id);

  const required = (
    `RELEASE TREASURY LOCK ${requestId}`
  );

  const confirmation = String(
    $('#treasuryReleaseConfirmation')?.value
    || ''
  );

  const reason = String(
    $('#treasuryReleaseReason')?.value
    || ''
  ).trim();

  if (
    confirmation !== required
    || reason.length < 20
  ) {
    return;
  }

  const button = $('#releaseTreasuryLock');

  button.disabled = true;
  button.textContent = 'Releasing…';

  try {
    await adminApi(
      `/api/treasury/transfers/${
        encodeURIComponent(requestId)
      }/lock/release`,
      {
        method: 'POST',
        body: JSON.stringify({
          confirmation,
          reason,
        }),
      },
    );

    showToast(
      'Treasury lock released; audit record created.'
    );

    const refreshed = await adminApi(
      `/api/treasury/transfers/requests/${
        encodeURIComponent(requestId)
      }`
    );

    renderTreasuryRequestDetail(refreshed);

    await loadTreasuryOverview({
      quiet: true,
    });

  } catch (error) {
    showToast(
      treasuryErrorMessage(error),
      true,
    );

  } finally {
    button.textContent = (
      'Release unresolved lock'
    );

    updateTreasuryReleaseButton();
  }
}


function switchTab(tab, { updateHash = true } = {}) {
  const titles = {
    overview: ['Overview', 'Native Gate.io bot performance and portfolio history'],
    bots: ['Trading bots', 'Inspect every mapped field and Gate’s dynamic response data'],
    'bot-control': ['Bot Control', 'Prepare, review and safely submit native Gate trading bots'],
    alerts: ['Alerts', 'Local rules evaluated after each bot snapshot'],
    wallet: ['Wallet', 'Private balances, deposits and account-scoped wallet activity'],
    trading: ['Trading', 'Live Gate spot chart, order book and account-scoped market view'],
    system: ['System', 'Connection status, collector runs and safe API inspection'],
  };

  let target = String(tab || 'overview')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, '');

  if (!titles[target] || !document.querySelector(`#tab-${target}`)) {
    target = 'overview';
  }
  if (
    ['wallet', 'trading'].includes(target)
    && (
      !state.adminUser
      || !state.adminAuthorization
    )
  ) {
    target = 'overview';
  }

  if (
    target === 'bot-control'
    && !botControlAvailable()
  ) {
    target = 'overview';
  }

  state.activeTab = target;

  renderSidebarSyncScope();

  const globalAccountSelector = $(
    '#globalAccountSelector'
  );

  const globalAccountVisible = (
    target !== 'trading'
    && target !== 'bot-control'
  );

  globalAccountSelector?.classList.toggle(
    'hidden',
    !globalAccountVisible,
  );

  globalAccountSelector?.setAttribute(
    'aria-hidden',
    String(!globalAccountVisible),
  );

  $$('.nav-item').forEach(button => {
    button.classList.toggle('active', button.dataset.tab === target);
  });
  $$('.tab-panel').forEach(panel => {
    panel.classList.toggle('active', panel.id === `tab-${target}`);
  });

  $('#pageTitle').textContent = titles[target][0];
  $('#pageSubtitle').textContent = titles[target][1];

  if (updateHash && window.location.hash !== `#${target}`) {
    history.replaceState(null, '', `#${target}`);
  }

  if (
    target === 'wallet'
    && state.adminUser
    && state.adminAuthorization
  ) {
    void Promise.all([
      loadPrivateBalance({ quiet: true }),
      loadDepositHistory({ quiet: true }),
      loadTreasuryOverview({ quiet: true }),
    ]);
  }

  if (
    target === 'trading'
    && state.adminUser
    && state.adminAuthorization
  ) {
    window.activateTradingTab?.();
  }
}
function setMetric(selector, value, formatter = fmtMoney, classValue = value) {
  const el = $(selector);
  el.textContent = formatter(value);
  el.classList.remove('positive', 'negative');

  if (classValue !== null && classValue !== undefined) {
    const metricClass = valueClass(classValue);
    if (metricClass) el.classList.add(metricClass);
  }
}

function renderOverview() {
  if (!state.overview) return;
  const { totals, counts, periods = {}, latest_sync: latest } = state.overview;
  setMetric('#totalInvest', totals.invest_amount, fmtMoney, null);
  setMetric('#currentValue', totals.current_value, fmtMoney, null);
  setMetric('#totalPnl', totals.pnl, fmtMoney, totals.pnl);
  setMetric('#gridProfit', totals.grid_profit, fmtMoney, totals.grid_profit);
  const displayCounts = {
    running: 0,
    waiting: 0,
    paused: 0,
    stopped: 0,
    other: 0,
  };

  state.bots.forEach(bot => {
    const displayStatus = botDisplayStatus(bot).key;

    if (displayStatus === 'running') {
      displayCounts.running += 1;
    } else if (displayStatus === 'waiting-trigger') {
      displayCounts.waiting += 1;
    } else if (
      displayStatus === 'paused'
      || displayStatus === 'suspended'
    ) {
      displayCounts.paused += 1;
    } else if (
      displayStatus === 'stopped'
      || displayStatus === 'finished'
    ) {
      displayCounts.stopped += 1;
    } else {
      displayCounts.other += 1;
    }
  });

  const displayTotal = Object.values(
    displayCounts
  ).reduce(
    (totalCount, count) => totalCount + count,
    0,
  );

  const activeSummary = [
    `${displayCounts.running} running`,
  ];

  if (displayCounts.waiting > 0) {
    activeSummary.push(
      `${displayCounts.waiting} waiting`,
    );
  }

  activeSummary.push(`${displayTotal} tracked`);

  $('#activeBotCount').textContent =
    activeSummary.join(' · ');

  const day = periods['24h'] || {};

  $('#portfolioDelta').textContent =
    day.value_change === null
    || day.value_change === undefined
      ? `Invested ${fmtMoney(totals.invest_amount)}`
      : (
        `24h ${fmtMoney(day.value_change)} `
        + `(${fmtPct(day.value_change_pct)})`
      );

  $('#portfolioDelta').className =
    valueClass(day.value_change);

  $('#totalRoi').textContent =
    `ROI ${fmtPct(totals.roi_pct)}`;

  $('#totalRoi').className =
    valueClass(totals.roi_pct);

  $('#floatingPnl').textContent =
    `Unrealized ${fmtMoney(totals.floating_pnl)}`;

  $('#floatingPnl').className =
    valueClass(totals.floating_pnl);

  $('#ringTotal').textContent = displayTotal;

  const ringTotal = Math.max(1, displayTotal);

  const runDegrees =
    displayCounts.running / ringTotal * 360;

  const waitDegrees =
    runDegrees
    + displayCounts.waiting / ringTotal * 360;

  const pauseDegrees =
    waitDegrees
    + displayCounts.paused / ringTotal * 360;

  const stopDegrees =
    pauseDegrees
    + displayCounts.stopped / ringTotal * 360;

  const statusRing = $('#statusRing');

  statusRing.style.setProperty(
    '--run',
    `${runDegrees}deg`,
  );

  statusRing.style.setProperty(
    '--wait',
    `${waitDegrees}deg`,
  );

  statusRing.style.setProperty(
    '--pause',
    `${pauseDegrees}deg`,
  );

  statusRing.style.setProperty(
    '--stop',
    `${stopDegrees}deg`,
  );

  const statuses = [
    [
      'Running',
      displayCounts.running,
      'var(--positive)',
    ],
    [
      'Waiting',
      displayCounts.waiting,
      '#f3c76a',
    ],
    [
      'Paused',
      displayCounts.paused,
      'var(--warning)',
    ],
    [
      'Stopped',
      displayCounts.stopped,
      '#53655e',
    ],
    [
      'Other',
      displayCounts.other,
      'var(--negative)',
    ],
  ];

  $('#statusList').innerHTML = statuses
    .map(([label, count, color]) => (
      `<div class="status-row">`
      + `<span>`
      + `<i class="dot" style="background:${color}"></i>`
      + `${label}`
      + `</span>`
      + `<b>${count}</b>`
      + `</div>`
    ))
    .join('');

  const leaders = [...state.bots]
    .filter(
      bot => botDisplayStatus(bot).key === 'running'
    )
    .sort(
      (a, b) => (
        b.profit_rate
        ?? b.pnl_rate
        ?? -Infinity
      ) - (
        a.profit_rate
        ?? a.pnl_rate
        ?? -Infinity
      )
    )
    .slice(0, 4);
  $('#leaderCards').innerHTML = leaders.length
    ? leaders.map(bot => {
      const rate =
        bot.profit_rate
        ?? bot.pnl_rate;

      const profit =
        bot.total_profit
        ?? bot.pnl;

      return `
        <button
          class="leader row-button"
          data-bot-id="${bot.id}"
        >
          <span class="leader-copy">
            <b class="leader-name">
              ${escapeHtml(bot.strategy_name)}
            </b>
            <small class="leader-meta">
              ${escapeHtml(bot.account_name)}
              · ${escapeHtml(bot.market)}
              · ${strategyLabel(bot.strategy_type)}
            </small>
          </span>

          <span
            class="leader-result ${valueClass(rate)}"
          >
            <strong>${fmtRatioPct(rate)}</strong>
            <small>${fmtMoney(profit)}</small>
          </span>
        </button>
      `;
    }).join('')
    : '<div class="empty-state">No running bots yet.</div>';

  renderSidebarSyncScope(
    latest
  );
  renderOverviewAlerts();
  drawPortfolioChart();
}

function chartAxisMoney(value) {
  const number = Number(value);

  if (!Number.isFinite(number)) return '—';

  const absolute = Math.abs(number);
  const digits = absolute < 10 ? 2 : absolute < 100 ? 1 : 0;

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(number);
}

function chartScaleRange(values, includeZero = false) {
  const valid = values
    .map(Number)
    .filter(Number.isFinite);

  if (!valid.length) {
    return { min: 0, max: 1 };
  }

  let min = Math.min(...valid);
  let max = Math.max(...valid);

  if (includeZero) {
    min = Math.min(min, 0);
    max = Math.max(max, 0);
  }

  if (min === max) {
    const expansion = Math.abs(min) * 0.05 || 1;
    min -= expansion;
    max += expansion;
  }

  const margin = (max - min) * 0.08;

  return {
    min: min - margin,
    max: max + margin,
  };
}

function chartTimeLabel(timestamp, totalSpan) {
  const date = new Date(timestamp);

  let options;

  if (totalSpan <= 48 * 60 * 60 * 1000) {
    options = {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    };
  } else if (totalSpan >= 180 * 24 * 60 * 60 * 1000) {
    options = {
      month: 'short',
      year: '2-digit',
    };
  } else {
    options = {
      month: 'short',
      day: 'numeric',
    };
  }

  return new Intl.DateTimeFormat(
    undefined,
    options,
  ).format(date);
}

function drawSeriesChart(
  canvas,
  points,
  series,
  options = {},
) {
  const rect = canvas.getBoundingClientRect();

  if (!rect.width || !rect.height) return;

  const ratio = window.devicePixelRatio || 1;

  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);

  const ctx = canvas.getContext('2d');
  ctx.scale(ratio, ratio);

  const width = rect.width;
  const height = rect.height;

  const pad = {
    left: 86,
    right: 86,
    top: 20,
    bottom: 52,
  };

  const plotW = Math.max(
    1,
    width - pad.left - pad.right,
  );

  const plotH = Math.max(
    1,
    height - pad.top - pad.bottom,
  );

  const css = getComputedStyle(
    document.documentElement,
  );

  const muted = css
    .getPropertyValue('--muted')
    .trim();

  const border = css
    .getPropertyValue('--border')
    .trim();

  const surface = css
    .getPropertyValue('--surface')
    .trim();

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = surface;
  ctx.fillRect(0, 0, width, height);

  const chartPoints = points
    .filter(point => {
      const timestamp = new Date(
        point.captured_at,
      ).valueOf();

      return Number.isFinite(timestamp);
    })
    .sort(
      (a, b) => (
        new Date(a.captured_at).valueOf()
        - new Date(b.captured_at).valueOf()
      ),
    );

  if (!chartPoints.length) {
    canvas._chartMeta = null;
    return;
  }

  const timestamps = chartPoints.map(
    point => new Date(
      point.captured_at,
    ).valueOf(),
  );

  const xMin = Math.min(...timestamps);
  const xMax = Math.max(...timestamps);
  const xSpan = Math.max(1, xMax - xMin);

  const x = timestamp => (
    pad.left
    + ((timestamp - xMin) / xSpan) * plotW
  );

  const normalizedSeries = series.map(
    (item, index) => ({
      ...item,
      axis: item.axis
        || (index === 0 ? 'left' : 'right'),
    }),
  );

  const leftValues = [];
  const rightValues = [];

  normalizedSeries.forEach(item => {
    chartPoints.forEach(point => {
      const value = Number(point[item.key]);

      if (!Number.isFinite(value)) return;

      if (item.axis === 'right') {
        rightValues.push(value);
      } else {
        leftValues.push(value);
      }
    });
  });

  const leftRange = chartScaleRange(
    leftValues,
    Boolean(options.leftIncludeZero),
  );

  const rightRange = chartScaleRange(
    rightValues,
    options.rightIncludeZero !== false,
  );

  const yFor = (value, axis) => {
    const range = axis === 'right'
      ? rightRange
      : leftRange;

    return (
      pad.top
      + (
        1
        - (value - range.min)
        / (range.max - range.min)
      ) * plotH
    );
  };

  ctx.font = '11px system-ui';
  ctx.lineWidth = 1;

  const tickCount = 4;

  for (let index = 0; index <= tickCount; index++) {
    const fraction = index / tickCount;
    const yPosition = pad.top + plotH * fraction;

    ctx.strokeStyle = border;
    ctx.beginPath();
    ctx.moveTo(pad.left, yPosition);
    ctx.lineTo(
      width - pad.right,
      yPosition,
    );
    ctx.stroke();

    const leftValue = (
      leftRange.max
      - (leftRange.max - leftRange.min)
      * fraction
    );

    const rightValue = (
      rightRange.max
      - (rightRange.max - rightRange.min)
      * fraction
    );

    ctx.fillStyle = muted;
    ctx.textBaseline = 'middle';

    ctx.textAlign = 'right';
    ctx.fillText(
      chartAxisMoney(leftValue),
      pad.left - 10,
      yPosition,
    );

    ctx.textAlign = 'left';
    ctx.fillText(
      chartAxisMoney(rightValue),
      width - pad.right + 10,
      yPosition,
    );
  }

  const xTicks = 4;

  for (let index = 0; index <= xTicks; index++) {
    const fraction = index / xTicks;
    const timestamp = xMin + xSpan * fraction;
    const xPosition = x(timestamp);

    ctx.fillStyle = muted;
    ctx.textBaseline = 'top';

    if (index === 0) {
      ctx.textAlign = 'left';
    } else if (index === xTicks) {
      ctx.textAlign = 'right';
    } else {
      ctx.textAlign = 'center';
    }

    ctx.fillText(
      chartTimeLabel(timestamp, xSpan),
      xPosition,
      pad.top + plotH + 10,
    );
  }

  const leftColor = normalizedSeries.find(
    item => item.axis !== 'right',
  )?.color || muted;

  const rightColor = normalizedSeries.find(
    item => item.axis === 'right',
  )?.color || muted;

  ctx.save();
  ctx.translate(
    14,
    pad.top + plotH / 2,
  );
  ctx.rotate(-Math.PI / 2);
  ctx.fillStyle = leftColor;
  ctx.font = '600 11px system-ui';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(
    options.leftAxisLabel
      || 'Current value (USDT)',
    0,
    0,
  );
  ctx.restore();

  ctx.save();
  ctx.translate(
    width - 14,
    pad.top + plotH / 2,
  );
  ctx.rotate(Math.PI / 2);
  ctx.fillStyle = rightColor;
  ctx.font = '600 11px system-ui';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(
    options.rightAxisLabel
      || 'PnL (USDT)',
    0,
    0,
  );
  ctx.restore();

  ctx.fillStyle = muted;
  ctx.font = '600 11px system-ui';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  ctx.fillText(
    options.xAxisLabel || 'Snapshot time',
    pad.left + plotW / 2,
    height - 2,
  );

  normalizedSeries.forEach((item, index) => {
    const coordinates = [];

    chartPoints.forEach((point, pointIndex) => {
      const value = Number(point[item.key]);

      if (!Number.isFinite(value)) return;

      coordinates.push({
        x: x(timestamps[pointIndex]),
        y: yFor(value, item.axis),
      });
    });

    if (!coordinates.length) return;

    if (item.fill) {
      ctx.beginPath();
      ctx.moveTo(
        coordinates[0].x,
        pad.top + plotH,
      );

      coordinates.forEach((coordinate, pointIndex) => {
        if (pointIndex === 0) {
          ctx.lineTo(
            coordinate.x,
            coordinate.y,
          );
        } else {
          ctx.lineTo(
            coordinate.x,
            coordinate.y,
          );
        }
      });

      ctx.lineTo(
        coordinates[coordinates.length - 1].x,
        pad.top + plotH,
      );

      ctx.closePath();

      const gradient = ctx.createLinearGradient(
        0,
        pad.top,
        0,
        pad.top + plotH,
      );

      gradient.addColorStop(0, item.fill);
      gradient.addColorStop(
        1,
        'rgba(0,0,0,0)',
      );

      ctx.fillStyle = gradient;
      ctx.fill();
    }

    ctx.beginPath();

    coordinates.forEach((coordinate, pointIndex) => {
      if (pointIndex === 0) {
        ctx.moveTo(
          coordinate.x,
          coordinate.y,
        );
      } else {
        ctx.lineTo(
          coordinate.x,
          coordinate.y,
        );
      }
    });

    ctx.strokeStyle = item.color;
    ctx.lineWidth = index === 0 ? 2.2 : 1.8;
    ctx.stroke();
  });

  canvas._chartMeta = {
    points: chartPoints,
    timestamps,
    xMin,
    xMax,
    xSpan,
    pad,
    plotW,
    plotH,
  };
}

function bindPortfolioChartTooltip() {
  const canvas = $('#portfolioChart');
  const tooltip = $('#portfolioChartTooltip');
  const crosshair = $('#portfolioChartCrosshair');

  if (
    !canvas
    || !tooltip
    || !crosshair
    || canvas.dataset.tooltipBound
  ) {
    return;
  }

  canvas.dataset.tooltipBound = 'true';

  const hide = () => {
    tooltip.classList.add('hidden');
    crosshair.classList.add('hidden');
  };

  canvas.addEventListener(
    'pointerleave',
    hide,
  );

  canvas.addEventListener(
    'pointermove',
    event => {
      const meta = canvas._chartMeta;

      if (!meta || !meta.points.length) {
        hide();
        return;
      }

      const rect = canvas.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      const mouseY = event.clientY - rect.top;

      const plotRight = (
        meta.pad.left + meta.plotW
      );

      const plotBottom = (
        meta.pad.top + meta.plotH
      );

      if (
        mouseX < meta.pad.left
        || mouseX > plotRight
        || mouseY < meta.pad.top
        || mouseY > plotBottom
      ) {
        hide();
        return;
      }

      const targetTimestamp = (
        meta.xMin
        + (
          (mouseX - meta.pad.left)
          / meta.plotW
        ) * meta.xSpan
      );

      let nearestIndex = 0;
      let nearestDistance = Infinity;

      meta.timestamps.forEach(
        (timestamp, index) => {
          const distance = Math.abs(
            timestamp - targetTimestamp,
          );

          if (distance < nearestDistance) {
            nearestDistance = distance;
            nearestIndex = index;
          }
        },
      );

      const point = meta.points[nearestIndex];
      const timestamp = meta.timestamps[nearestIndex];

      const pointX = (
        meta.pad.left
        + (
          (timestamp - meta.xMin)
          / meta.xSpan
        ) * meta.plotW
      );

      tooltip.innerHTML = (
        `<strong class="chart-tooltip-time">`
        + `${escapeHtml(fmtDate(point.captured_at))}`
        + `</strong>`
        + `<span>`
        + `<i class="tooltip-dot value"></i>`
        + `Current value`
        + `<b>${escapeHtml(fmtMoney(point.current_value))}</b>`
        + `</span>`
        + `<span>`
        + `<i class="tooltip-dot pnl"></i>`
        + `Total PnL`
        + `<b>${escapeHtml(fmtMoney(point.pnl))}</b>`
        + `</span>`
      );

      tooltip.classList.remove('hidden');
      crosshair.classList.remove('hidden');

      crosshair.style.left = `${pointX}px`;
      crosshair.style.top = `${meta.pad.top}px`;
      crosshair.style.height = `${meta.plotH}px`;

      const tooltipWidth = tooltip.offsetWidth;
      const tooltipHeight = tooltip.offsetHeight;

      let tooltipLeft = pointX + 14;

      if (
        tooltipLeft + tooltipWidth
        > rect.width - 8
      ) {
        tooltipLeft = pointX - tooltipWidth - 14;
      }

      tooltipLeft = Math.max(
        8,
        tooltipLeft,
      );

      let tooltipTop = mouseY - tooltipHeight - 14;

      if (tooltipTop < 8) {
        tooltipTop = mouseY + 14;
      }

      tooltip.style.left = `${tooltipLeft}px`;
      tooltip.style.top = `${tooltipTop}px`;
    },
  );
}

function drawPortfolioChart() {
  const empty = $('#chartEmpty');

  empty.classList.toggle(
    'hidden',
    state.history.length > 1,
  );

  const css = getComputedStyle(
    document.documentElement,
  );

  drawSeriesChart(
    $('#portfolioChart'),
    state.history,
    [
      {
        key: 'current_value',
        label: 'Current value',
        axis: 'left',
        color: css
          .getPropertyValue('--accent')
          .trim(),
        fill: 'rgba(23,211,154,.16)',
      },
      {
        key: 'pnl',
        label: 'Total PnL',
        axis: 'right',
        color: css
          .getPropertyValue('--blue')
          .trim(),
      },
    ],
    {
      leftAxisLabel: 'Current value (USDT)',
      rightAxisLabel: 'Total PnL (USDT)',
      xAxisLabel: 'Snapshot date and time',
      rightIncludeZero: true,
    },
  );

  bindPortfolioChartTooltip();
}

function populateAccountSelector(accounts = []) {
  const selector = $('#accountSelector');
  const current = state.selectedAccount;
  selector.innerHTML = '<option value="">All accounts</option>' + accounts.map(account => {
    const suffix = account.sync_status && account.sync_status !== 'success' ? ` · ${account.sync_status}` : '';
    return `<option value="${escapeHtml(account.id)}">${escapeHtml(account.name)}${escapeHtml(suffix)}</option>`;
  }).join('');
  if (current && accounts.some(account => account.id === current)) selector.value = current;
  else { state.selectedAccount = ''; selector.value = ''; }
}

function populateFilterOptions(filters = {}) {
  const type = $('#typeFilter'), market = $('#marketFilter');
  const currentType = type.value, currentMarket = market.value;
  type.innerHTML = '<option value="">All types</option>' + (filters.strategy_types || []).map(v => `<option value="${escapeHtml(v)}">${strategyLabel(v)}</option>`).join('');
  market.innerHTML = '<option value="">All markets</option>' + (filters.markets || []).map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
  type.value = currentType;
  market.value = currentMarket;

  const botSelect = $('#ruleForm select[name="bot_id"]');
  if (!botSelect) return;
  const manageableBots = state.bots.filter(
    bot => (
      !botIsArchived(bot)
      && canManageAccount(
        bot.account_id
      )
    )
  );
  const globalOption = state.adminUser?.role === 'super_admin'
    ? '<option value="">All bots (super admin)</option>'
    : '<option value="" disabled>Select one of your bots</option>';
  botSelect.innerHTML = globalOption + manageableBots.map(bot => `<option value="${bot.id}">[${escapeHtml(bot.account_name)}] ${escapeHtml(bot.strategy_name)} (${escapeHtml(bot.market)})</option>`).join('');
  if (state.adminUser?.role !== 'super_admin' && manageableBots.length) botSelect.value = String(manageableBots[0].id);
}

function botIsArchived(bot) {
  return Boolean(
    bot?.archived === true
    && String(
      bot?.status || ''
    )
      .trim()
      .toLowerCase()
      === 'stopped'
  );
}


function applyBotFilters() {
  const term = $('#botSearch').value
    .trim()
    .toLowerCase();

  const status = $('#statusFilter').value;
  const type = $('#typeFilter').value;
  const market = $('#marketFilter').value;
  const sort = $('#sortFilter').value;

  const valueFor = bot => ({
    pnl:
      bot.total_profit
      ?? bot.pnl
      ?? -Infinity,

    roi:
      bot.profit_rate
      ?? bot.pnl_rate
      ?? -Infinity,

    updated:
      new Date(
        bot.updated_at
      ).valueOf(),

    name:
      bot.strategy_name,

    market:
      bot.market,
  }[sort]);

  const matches = state.bots
    .filter(
      bot => {
        const searchable = (
          `${bot.account_name} `
          + `${bot.account_id} `
          + `${bot.strategy_name} `
          + `${bot.market} `
          + `${bot.strategy_id}`
        ).toLowerCase();

        return (
          (
            !term
            || searchable.includes(term)
          )
          && (
            !status
            || bot.status === status
          )
          && (
            !type
            || bot.strategy_type === type
          )
          && (
            !market
            || bot.market === market
          )
        );
      }
    )
    .sort(
      (a, b) => (
        typeof valueFor(a) === 'string'
          ? String(
            valueFor(a)
          ).localeCompare(
            String(
              valueFor(b)
            )
          )
          : (
            Number(
              valueFor(b)
            )
            - Number(
              valueFor(a)
            )
          )
      )
    );

  state.filteredBots = matches.filter(
    bot => !botIsArchived(bot)
  );

  state.filteredArchivedBots =
    matches.filter(
      bot => botIsArchived(bot)
    );

  renderBots();
  renderArchivedBots();
}

function botDisplayStatus(bot) {
  const localStatus = String(
    bot?.status
    ?? ''
  ).trim().toLowerCase();

  /*
   * The Gate running-portfolio feed stops returning a
   * strategy after it finishes/stops. source_status may
   * therefore retain the last value observed from Gate,
   * e.g. "running", while our collector has correctly
   * transitioned the canonical local status to
   * "stopped".
   *
   * Preserve source_status as evidence, but use the
   * terminal local state for effective UI display.
   */
  const terminalLocalStates = new Set([
    'stopped',
    'finished',
    'closed',
    'cancelled',
    'canceled',
    'terminated',
    'failed',
  ]);

  if (
    terminalLocalStates.has(localStatus)
    && String(
      bot?.source_status
      ?? ''
    ).trim().toLowerCase()
      !== localStatus
  ) {
    return botDisplayStatusOriginal({
      ...bot,
      source_status: localStatus,
    });
  }

  return botDisplayStatusOriginal(bot);
}


function botDisplayStatusOriginal(bot) {
  const sourceStatus = String(
    bot?.source_status
    ?? bot?.status
    ?? ''
  ).trim().toLowerCase();

  const positionAmount = numericValue(
    bot?.position_amount
  );

  const entryPrice = numericValue(
    bot?.entry_price
  );

  const totalPnl = numericValue(
    bot?.total_profit
    ?? bot?.pnl
  );

  const realizedPnl = numericValue(
    bot?.realized_pnl
    ?? bot?.grid_profit
  );

  const gridRecords = numericValue(
    bot?.arbitrage_count
  );

  const runtimeSeconds = numericValue(
    bot?.runtime_seconds
  ) ?? 0;

  /*
   * Gate reports trigger-waiting Spot Grid bots as "running".
   * Infer the visible state only after the initial API startup period.
   * The original Gate source_status remains unchanged.
   */
  const waitingForTrigger = (
    bot?.strategy_type === 'spot_grid'
    && sourceStatus === 'running'
    && runtimeSeconds >= 60
    && positionAmount === 0
    && entryPrice !== null
    && entryPrice > 0
    && totalPnl === 0
    && realizedPnl === 0
    && gridRecords === 0
  );

  if (waitingForTrigger) {
    return {
      key: 'waiting-trigger',
      label: 'To be triggered',
      inferred: true,
      title: (
        'Gate reports running, but the bot has no position, '
        + 'profit, or grid records yet. Trigger state inferred.'
      ),
    };
  }

  const labels = {
    running: 'Running',
    paused: 'Paused',
    suspended: 'Suspended',
    stopped: 'Stopped',
    finished: 'Finished',
    failed: 'Failed',
  };

  return {
    key: sourceStatus.replaceAll('_', '-')
      || 'unknown',
    label: labels[sourceStatus]
      || sourceStatus.replaceAll('_', ' ')
      || 'Unknown',
    inferred: false,
    title: `Gate status: ${sourceStatus || 'unknown'}`,
  };
}

function renderBots() {
  const tbody = $('#botsTableBody');

  tbody.innerHTML = state.filteredBots
    .map(
      bot => {
        const totalPnl =
          bot.total_profit
          ?? bot.pnl;

        const rate =
          bot.profit_rate
          ?? bot.pnl_rate;

        const displayStatus =
          botDisplayStatus(bot);

        const stopped = (
          String(
            bot.status || ''
          )
            .trim()
            .toLowerCase()
          === 'stopped'
        );

        const canArchive = Boolean(
          stopped
          && canManageAccount(
            bot.account_id
          )
        );

        const archiveAction =
          canArchive
            ? `
              <button
                type="button"
                class="text-button bot-archive-action"
                data-archive-bot-id="${bot.id}"
              >Archive</button>
            `
            : '';

        return `<tr>
          <td class="strategy-cell">
            <strong>
              ${escapeHtml(
                bot.strategy_name
              )}
            </strong>
            <small>
              ${escapeHtml(bot.market)}
              · ${strategyLabel(
                bot.strategy_type
              )}
            </small>
          </td>

          <td>
            <span class="account-badge">
              ${escapeHtml(
                bot.account_name
              )}
            </span>
          </td>

          <td>
            <span
              class="status-badge ${escapeHtml(displayStatus.key)}"
              title="${escapeHtml(displayStatus.title)}"
            >
              ${escapeHtml(
                displayStatus.label
              )}
            </span>
          </td>

          <td>
            ${fmtMoney(
              bot.invest_amount
            )}
          </td>

          <td>
            ${fmtMoney(
              bot.current_value
            )}
          </td>

          <td class="${valueClass(totalPnl)}">
            ${fmtMoney(totalPnl)}
          </td>

          <td class="${valueClass(rate)}">
            ${fmtRatioPct(rate)}
          </td>

          <td>
            ${fmtDuration(
              bot.runtime_seconds
            )}
          </td>

          <td>
            <div class="bot-row-actions">
              <button
                type="button"
                class="row-button"
                data-bot-id="${bot.id}"
              >Details →</button>

              ${archiveAction}
            </div>
          </td>
        </tr>`;
      }
    )
    .join('');

  $('#botsEmpty').classList.toggle(
    'hidden',
    state.filteredBots.length > 0,
  );
}


function renderArchivedBots() {
  const tbody =
    $('#archivedBotsTableBody');

  if (!tbody) {
    return;
  }

  const totalArchived =
    state.bots.filter(
      bot => botIsArchived(bot)
    ).length;

  const count =
    $('#archivedBotsCount');

  if (count) {
    count.textContent = (
      `${totalArchived} archived`
    );
  }

  tbody.innerHTML =
    state.filteredArchivedBots
      .map(
        bot => {
          const totalPnl =
            bot.total_profit
            ?? bot.pnl;

          const rate =
            bot.profit_rate
            ?? bot.pnl_rate;

          const displayStatus =
            botDisplayStatus(bot);

          const restoreAction =
            canManageAccount(
              bot.account_id
            )
              ? `
                <button
                  type="button"
                  class="text-button bot-restore-action"
                  data-restore-bot-id="${bot.id}"
                >Restore</button>
              `
              : '';

          return `<tr>
            <td class="strategy-cell">
              <strong>
                ${escapeHtml(
                  bot.strategy_name
                )}
              </strong>

              <small>
                ${escapeHtml(bot.market)}
                · ${strategyLabel(
                  bot.strategy_type
                )}
              </small>
            </td>

            <td>
              <span class="account-badge">
                ${escapeHtml(
                  bot.account_name
                )}
              </span>
            </td>

            <td>
              <span
                class="status-badge ${escapeHtml(displayStatus.key)}"
                title="${escapeHtml(displayStatus.title)}"
              >
                ${escapeHtml(
                  displayStatus.label
                )}
              </span>
            </td>

            <td>
              ${fmtMoney(
                bot.invest_amount
              )}
            </td>

            <td>
              ${fmtMoney(
                bot.current_value
              )}
            </td>

            <td class="${valueClass(totalPnl)}">
              ${fmtMoney(totalPnl)}
            </td>

            <td class="${valueClass(rate)}">
              ${fmtRatioPct(rate)}
            </td>

            <td>
              ${fmtDate(
                bot.archived_at
              )}
            </td>

            <td>
              <div class="bot-row-actions">
                <button
                  type="button"
                  class="row-button"
                  data-bot-id="${bot.id}"
                >Details →</button>

                ${restoreAction}
              </div>
            </td>
          </tr>`;
        }
      )
      .join('');

  $('#archivedBotsEmpty')
    ?.classList.toggle(
      'hidden',
      state.filteredArchivedBots.length
        > 0,
    );
}


async function archiveBot(botId) {
  const bot = state.bots.find(
    item => (
      Number(item.id)
      === Number(botId)
    )
  );

  if (
    !bot
    || !canManageAccount(
      bot.account_id
    )
  ) {
    return;
  }

  if (
    String(
      bot.status || ''
    )
      .trim()
      .toLowerCase()
    !== 'stopped'
  ) {
    showToast(
      'Only stopped bots can be archived.',
      true,
    );

    return;
  }

  const confirmed = confirm(
    'Archive this stopped bot? '
    + 'This only hides it from the main '
    + 'dashboard bot list. Nothing will '
    + 'be sent to Gate.'
  );

  if (!confirmed) {
    return;
  }

  try {
    const result = await adminApi(
      `/api/bots/${bot.id}/archive`,
      {
        method: 'POST',
      },
    );

    if (
      result.gate_write_performed
      !== false
    ) {
      throw new Error(
        'Archive safety contract failed.'
      );
    }

    state.bots = state.bots.map(
      item => (
        Number(item.id)
        === Number(bot.id)
          ? {
            ...item,
            ...result.bot,
          }
          : item
      )
    );

    applyBotFilters();

    showToast(
      'Bot archived locally. '
      + 'No Gate request was sent.'
    );

    /*
     * Reconcile from the backend asynchronously.
     * The local committed response already contains the
     * authoritative archive state, so the user should not
     * wait for the full dashboard refresh.
     */
    void loadCore();

  } catch (error) {
    showToast(
      error.message
      || 'Unable to archive bot.',
      true,
    );
  }
}


async function restoreBot(botId) {
  const bot = state.bots.find(
    item => (
      Number(item.id)
      === Number(botId)
    )
  );

  if (
    !bot
    || !canManageAccount(
      bot.account_id
    )
  ) {
    return;
  }

  try {
    const result = await adminApi(
      `/api/bots/${bot.id}/restore`,
      {
        method: 'POST',
      },
    );

    if (
      result.gate_write_performed
      !== false
    ) {
      throw new Error(
        'Restore safety contract failed.'
      );
    }

    state.bots = state.bots.map(
      item => (
        Number(item.id)
        === Number(bot.id)
          ? {
            ...item,
            archived: false,
            archived_at: null,
          }
          : item
      )
    );

    applyBotFilters();

    showToast(
      'Bot restored to the main list. '
      + 'No Gate request was sent.'
    );

    /*
     * Reconcile from the backend asynchronously without
     * delaying the successful local-only UI action.
     */
    void loadCore();

  } catch (error) {
    showToast(
      error.message
      || 'Unable to restore bot.',
      true,
    );
  }
}

function formatAlertMessage(message) {
  const text = String(
    message ?? ''
  );

  const percentageFormatted = text.replace(
    /-?\d+(?:\.\d+)?%/g,
    token => {
      const numeric = Number(
        token.slice(0, -1)
      );

      if (!Number.isFinite(numeric)) {
        return token;
      }

      return (
        numeric.toLocaleString(
          'en-US',
          {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          },
        )
        + '%'
      );
    },
  );

  return percentageFormatted.replace(
    /\brule\s*(>=|<=|==|>|<)\s*(-?\d+(?:\.\d+)?)/gi,
    (
      _match,
      operator,
      rawValue,
    ) => {
      const operators = {
        '>=': '≥',
        '<=': '≤',
        '==': '=',
        '>': '>',
        '<': '<',
      };

      const numeric = Number(rawValue);

      const value = Number.isFinite(numeric)
        ? numeric.toLocaleString(
          'en-US',
          {
            maximumFractionDigits: 2,
          },
        )
        : rawValue;

      return (
        `rule ${operators[operator] || operator} `
        + value
      );
    },
  );
}


function renderOverviewAlerts() {
  const target = $('#overviewAlerts');
  const items = state.alertIncidents.slice(0, 4);

  target.innerHTML = items.length
    ? items.map(
      overviewIncidentHtml
    ).join('')
    : (
      '<div class="empty-state">'
      + 'No active incidents.'
      + '</div>'
    );
}


function overviewIncidentHtml(incident) {
  const acknowledged = Boolean(
    incident.is_acknowledged
    || incident.acknowledged_at
  );

  const manageable = (
    alertIncidentManageable(
      incident
    )
  );

  let action = (
    '<span class="status-badge">'
    + `${acknowledged ? 'Ack' : 'Open'}`
    + '</span>'
  );

  if (
    !acknowledged
    && manageable
  ) {
    action = (
      `<button class="text-button ack-incident" `
      + `data-incident-id="${incident.id}">`
      + 'Acknowledge'
      + '</button>'
    );
  }

  const ruleName = (
    incident.rule_name
    || `Rule ${incident.rule_id}`
  );

  const scope = alertIncidentScope(
    incident
  );

  const condition = alertIncidentCondition(
    incident
  );

  const current = (
    alertIncidentMetricValue(
      incident.metric,
      incident.current_value,
      incident.bot,
    )
  );

  return (
    '<article class="event">'
    + '<i class="event-dot"></i>'
    + '<div>'
    + `<p>${escapeHtml(ruleName)}</p>`
    + (
      `<small>${
        escapeHtml(scope)
      } · ${
        escapeHtml(condition)
      } · Current ${
        escapeHtml(current)
      } · Opened ${
        escapeHtml(
          fmtDate(
            incident.opened_at
          )
        )
      }</small>`
    )
    + '</div>'
    + action
    + '</article>'
  );
}


function formatAlertUtcDate(value) {
  if (!value) {
    return '—';
  }

  const date = new Date(value);

  if (Number.isNaN(date.valueOf())) {
    return String(value);
  }

  const pad = number => String(
    number
  ).padStart(
    2,
    '0',
  );

  return (
    `${date.getUTCFullYear()}-`
    + `${pad(date.getUTCMonth() + 1)}-`
    + `${pad(date.getUTCDate())} `
    + `${pad(date.getUTCHours())}:`
    + `${pad(date.getUTCMinutes())} UTC`
  );
}


function alertMetricLabel(metric) {
  const labels = {
    drawdown_pct: 'Drawdown %',
    pnl: 'PnL USDT',
    pnl_rate: 'ROI %',
    floating_pnl: 'Floating PnL',
    current_value: 'Current value',
    liquidation_distance_pct: (
      'Liquidation distance %'
    ),
    stale_minutes: 'Data age minutes',
  };

  return (
    labels[String(metric || '')]
    || strategyLabel(metric)
  );
}


function alertOperatorLabel(operator) {
  const labels = {
    '>=': '≥',
    '<=': '≤',
    '>': '>',
    '<': '<',
    '==': '=',
  };

  return (
    labels[String(operator || '')]
    || String(operator || '—')
  );
}


function alertIncidentManageable(incident) {
  return Boolean(
    (
      incident.account_id
      && canManageAccount(
        incident.account_id
      )
    )
    || (
      !incident.account_id
      && state.adminUser?.role
        === 'super_admin'
    )
  );
}


function alertIncidentMetricValue(
  metric,
  value,
  bot = null,
) {
  if (
    value === null
    || value === undefined
    || value === ''
  ) {
    return '—';
  }

  const numeric = Number(value);

  if (!Number.isFinite(numeric)) {
    return String(value);
  }

  if (
    String(metric || '').endsWith('_pct')
    || metric === 'pnl_rate'
  ) {
    return `${fmtNumber(numeric, 2)}%`;
  }

  if (metric === 'stale_minutes') {
    return `${fmtNumber(numeric, 1)} min`;
  }

  if (
    metric === 'pnl'
    || metric === 'floating_pnl'
    || metric === 'current_value'
  ) {
    const quote = bot?.market
      ? marketAssets(bot.market).quote
      : '';

    return (
      `${fmtNumber(numeric, 4)}`
      + `${quote ? ` ${quote}` : ''}`
    );
  }

  return fmtNumber(
    numeric,
    4,
  );
}


function alertIncidentCondition(incident) {
  return (
    `${alertMetricLabel(incident.metric)} `
    + `${alertOperatorLabel(incident.operator)} `
    + `${alertIncidentMetricValue(
      incident.metric,
      incident.threshold,
      incident.bot,
    )}`
  );
}


function alertIncidentScope(incident) {
  const account = (
    incident.account_name
    || incident.account_id
    || 'Unknown account'
  );

  const bot = (
    incident.bot?.strategy_name
    || incident.bot?.strategy_id
    || (
      incident.bot_id
        ? `Bot ${incident.bot_id}`
        : 'Removed bot'
    )
  );

  const market = (
    incident.bot?.market
      ? ` · ${incident.bot.market}`
      : ''
  );

  return `${account} · ${bot}${market}`;
}


function alertIncidentAckMeta(incident) {
  if (!incident.acknowledged_at) {
    return '';
  }

  const actor = (
    incident.acknowledged_by
    || 'operator'
  );

  return (
    `Acknowledged by ${actor} · `
    + `${formatAlertUtcDate(
      incident.acknowledged_at
    )}`
  );
}


function alertIncidentAction(incident) {
  if (
    incident.is_acknowledged
    || incident.acknowledged_at
    || !alertIncidentManageable(
      incident
    )
  ) {
    return '';
  }

  return (
    `<button class="text-button ack-incident" `
    + `data-incident-id="${incident.id}">`
    + 'Acknowledge'
    + '</button>'
  );
}


function alertIncidentHtml(incident) {
  const acknowledged = Boolean(
    incident.is_acknowledged
    || incident.acknowledged_at
  );

  const status = acknowledged
    ? (
      '<span class="alerts-incident-status acknowledged">'
      + 'Acknowledged'
      + '</span>'
    )
    : (
      '<span class="alerts-incident-status open">'
      + 'Open'
      + '</span>'
    );

  const values = [
    [
      'Trigger',
      incident.trigger_value,
    ],
    [
      'Current',
      incident.current_value,
    ],
    [
      'Worst',
      incident.worst_value,
    ],
  ];

  const ackMeta = alertIncidentAckMeta(
    incident
  );

  return (
    `<article class="event alerts-incident ${
      acknowledged
        ? 'is-acknowledged'
        : 'is-open'
    }">`
    + '<i class="event-dot" aria-hidden="true"></i>'
    + '<div class="alerts-incident-content">'
    + (
      `<div class="alerts-incident-heading">`
      + `<strong>${
        escapeHtml(
          incident.rule_name
          || `Rule ${incident.rule_id}`
        )
      }</strong>`
      + `<span>${
        escapeHtml(
          alertIncidentScope(
            incident
          )
        )
      }</span>`
      + '</div>'
    )
    + (
      `<div class="alerts-incident-condition">${
        escapeHtml(
          alertIncidentCondition(
            incident
          )
        )
      }</div>`
    )
    + '<div class="alerts-incident-values">'
    + values.map(
      ([label, value]) => (
        '<div>'
        + `<span>${label}</span>`
        + `<strong>${
          escapeHtml(
            alertIncidentMetricValue(
              incident.metric,
              value,
              incident.bot,
            )
          )
        }</strong>`
        + '</div>'
      )
    ).join('')
    + '</div>'
    + '<div class="alerts-incident-time-row">'
    + (
      `<span>Opened ${
        escapeHtml(
          formatAlertUtcDate(
            incident.opened_at
          )
        )
      }</span>`
    )
    + (
      `<span>Last observed ${
        escapeHtml(
          formatAlertUtcDate(
            incident.last_observed_at
          )
        )
      }</span>`
    )
    + (
      ackMeta
        ? `<span>${
          escapeHtml(
            ackMeta
          )
        }</span>`
        : ''
    )
    + '</div>'
    + '</div>'
    + '<div class="alerts-incident-actions">'
    + status
    + alertIncidentAction(
      incident
    )
    + '</div>'
    + '</article>'
  );
}


function alertIncidentHistoryHtml(incident) {
  const acknowledged = Boolean(
    incident.is_acknowledged
    || incident.acknowledged_at
  );

  const ackMeta = alertIncidentAckMeta(
    incident
  );

  const values = (
    `Trigger ${
      alertIncidentMetricValue(
        incident.metric,
        incident.trigger_value,
        incident.bot,
      )
    }`
    + ` · Worst ${
      alertIncidentMetricValue(
        incident.metric,
        incident.worst_value,
        incident.bot,
      )
    }`
  );

  return (
    `<article class="alerts-history-item ${
      acknowledged
        ? 'is-acknowledged'
        : ''
    }">`
    + '<div class="alerts-history-main">'
    + (
      `<div class="alerts-history-title">`
      + `<strong>${
        escapeHtml(
          incident.rule_name
          || `Rule ${incident.rule_id}`
        )
      }</strong>`
      + `<span>${
        escapeHtml(
          alertIncidentScope(
            incident
          )
        )
      }</span>`
      + '</div>'
    )
    + (
      `<div class="alerts-history-condition">${
        escapeHtml(
          alertIncidentCondition(
            incident
          )
        )
      }</div>`
    )
    + (
      `<div class="alerts-history-values">${
        escapeHtml(values)
      }</div>`
    )
    + '<div class="alerts-history-times">'
    + (
      `<span>Opened ${
        escapeHtml(
          formatAlertUtcDate(
            incident.opened_at
          )
        )
      }</span>`
    )
    + (
      `<span>Recovered ${
        escapeHtml(
          formatAlertUtcDate(
            incident.recovered_at
          )
        )
      }</span>`
    )
    + (
      ackMeta
        ? `<span>${
          escapeHtml(
            ackMeta
          )
        }</span>`
        : '<span>Not acknowledged</span>'
    )
    + '</div>'
    + '</div>'
    + '<div class="alerts-history-actions">'
    + (
      '<span class="alerts-incident-status recovered">'
      + 'Recovered'
      + '</span>'
    )
    + alertIncidentAction(
      incident
    )
    + '</div>'
    + '</article>'
  );
}

function renderAlerts() {
  const rulesTarget = $('#rulesList');
  const incidentsTarget = $('#alertIncidents');
  const historyTarget = $('#alertIncidentHistory');

  if (rulesTarget) {
    rulesTarget.innerHTML = state.rules.length
      ? state.rules.map(rule => {
        const scope = (
          rule.account_name
          || 'All accounts'
        );

        const controls = canManageRule(rule)
          ? (
            '<div class="alerts-rule-actions">'
            + (
              '<label '
              + 'class="switch alerts-rule-toggle" '
              + 'title="Enable or disable rule">'
            )
            + (
              `<input class="rule-toggle" `
              + `type="checkbox" `
              + `data-rule-id="${rule.id}" `
              + `${rule.enabled ? 'checked' : ''}>`
            )
            + '<span></span>'
            + '</label>'
            + (
              `<button class="text-button delete-rule" `
              + `data-rule-id="${rule.id}">`
              + 'Delete'
              + '</button>'
            )
            + '</div>'
          )
          : (
            `<span class="alerts-rule-status ${
              rule.enabled
                ? 'active'
                : 'disabled'
            }">`
            + `${rule.enabled ? 'Active' : 'Disabled'}`
            + '</span>'
          );

        const condition = (
          `${alertMetricLabel(rule.metric)} `
          + `${alertOperatorLabel(rule.operator)} `
          + `${fmtNumber(rule.threshold, 4)}`
        );

        return (
          '<article class="rule alerts-rule">'
          + '<div class="alerts-rule-content">'
          + (
            `<p class="alerts-rule-title"><strong>${
              escapeHtml(rule.name)
            }</strong></p>`
          )
          + '<div class="alerts-rule-meta">'
          + (
            `<span class="alerts-rule-scope">${
              escapeHtml(scope)
            }</span>`
          )
          + (
            `<span class="alerts-rule-condition">${
              escapeHtml(condition)
            }</span>`
          )
          + (
            `<span class="alerts-rule-cooldown">Cooldown ${
              escapeHtml(
                fmtDuration(
                  rule.cooldown_seconds
                )
              )
            }</span>`
          )
          + '</div>'
          + '</div>'
          + controls
          + '</article>'
        );
      }).join('')
      : (
        '<div class="empty-state">'
        + 'No rules configured.'
        + '</div>'
      );
  }

  if (incidentsTarget) {
    incidentsTarget.innerHTML = (
      state.alertIncidents.length
        ? state.alertIncidents
          .map(alertIncidentHtml)
          .join('')
        : (
          '<div class="empty-state">'
          + 'No active incidents.'
          + '</div>'
        )
    );
  }

  if (historyTarget) {
    historyTarget.innerHTML = (
      state.alertIncidentHistory.length
        ? state.alertIncidentHistory
          .map(alertIncidentHistoryHtml)
          .join('')
        : (
          '<div class="empty-state">'
          + 'No recovered incidents yet.'
          + '</div>'
        )
    );
  }

  const activeCount = $('#activeIncidentCount');

  if (activeCount) {
    activeCount.textContent = (
      `${state.alertIncidents.length} open`
    );

    activeCount.classList.toggle(
      'has-open',
      state.alertIncidents.length > 0,
    );
  }

  const historyCount = $('#incidentHistoryCount');

  if (historyCount) {
    historyCount.textContent = (
      `${state.alertIncidentHistory.length} recovered`
    );
  }

  const addRuleButton = $('#addRuleButton');

  if (addRuleButton) {
    addRuleButton.disabled = (
      !state.adminUser
    );

    addRuleButton.title = (
      state.adminUser
        ? 'Create a rule for an authorized bot'
        : 'Unlock account actions first'
    );
  }
}

function renderSystem() {
  if (!state.health) return;
  const health = state.health;
  const accounts = state.overview?.accounts || [];
  $('#modeBadge').textContent = health.mode.toUpperCase();
  $('#modeBadge').className = `mode-badge ${health.mode}`;
  $('#connectionDot').className = health.status === 'ok' ? 'online' : 'offline';
  $('#connectionText').textContent = health.mode === 'demo'
    ? 'Demo accounts'
    : health.enabled_account_count
      ? `${health.enabled_account_count} Gate account${health.enabled_account_count === 1 ? '' : 's'}`
      : 'Credentials missing';
  const details = [
    ['Application', health.status], ['Mode', health.mode], ['Configured accounts', health.configured_account_count ?? accounts.length],
    ['Enabled accounts', health.enabled_account_count ?? 0], ['Collector', health.collector_running ? 'Synchronising' : 'Idle'],
    ['Poll interval', `${health.poll_seconds}s`], ['History retention', `${health.snapshot_retention_days} days`],
    ['Stop action', health.allow_bot_stop ? 'Enabled' : 'Disabled'],
    ['Action users', health.action_auth?.enabled_user_count ?? 0],
    ['Account session', state.adminUser ? `${state.adminUser.username} (${state.adminUser.role})` : 'Locked'],
  ];
  if (health.account_config_error) details.push(['Account config error', health.account_config_error]);
  if (health.user_config_error) details.push(['User config error', health.user_config_error]);
  $('#healthDetails').innerHTML = details.map(([k,v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`).join('');

  $('#accountsList').innerHTML = accounts.length ? accounts.map(account => {
    const portfolio = account.portfolio || {};
    const statusClass = account.sync_status === 'success' ? 'success' : account.sync_status === 'running' ? 'running' : account.sync_status === 'disabled' ? 'disabled' : 'error';
    return `<article class="account-row">
      <i class="account-dot ${statusClass}"></i>
      <div><strong>${escapeHtml(account.name)}</strong><small>${escapeHtml(account.id)} · ${portfolio.running ?? account.bot_count ?? 0} running · ${fmtMoney(portfolio.pnl)}</small></div>
      <div class="account-status"><span class="status-badge ${statusClass}">${escapeHtml(account.sync_status || 'never')}</span><small>${fmtDate(account.last_success_at)}</small></div>
    </article>`;
  }).join('') : '<div class="empty-state">No accounts recorded yet.</div>';

  $('#syncRuns').innerHTML = state.syncRuns.length ? state.syncRuns.map(run => `<article class="sync-run"><i class="sync-dot ${run.status === 'error' ? 'error' : run.status === 'partial' ? 'warning' : ''}"></i><div><strong>${escapeHtml(run.account_name || 'All accounts')} · ${escapeHtml(run.status)}</strong><small>${fmtDate(run.started_at)} · ${run.bot_count} bots / ${run.detail_count} details${run.error ? ` · ${escapeHtml(run.error)}` : ''}</small></div><span class="type-badge">${escapeHtml(run.trigger || run.summary?.trigger || '—')}</span></article>`).join('') : '<div class="empty-state">No collection runs yet.</div>';
}

async function loadCore() {
  try {
    const hours = Number($('#historyRange').value);
    const [
      health,
      overviewData,
      botData,
      historyData,
      ruleData,
      openIncidentData,
      historyIncidentData,
      syncData,
    ] = await Promise.all([
      api('/api/health'),
      api(scopedPath('/api/overview')),
      api(scopedPath('/api/bots')),
      api(scopedPath('/api/portfolio/history', { hours })),
      api('/api/alerts/rules'),
      api(scopedPath('/api/alerts/incidents', {
        state: 'open',
        limit: 100,
      })),
      api(scopedPath('/api/alerts/incidents', {
        state: 'history',
        limit: 100,
      })),
      api(scopedPath('/api/sync-runs', { limit: 20 })),
    ]);

    state.health = health;
    state.overview = overviewData;
    state.bots = botData.items;
    state.botFilters = botData.filters || {};
    state.history = historyData.items;
    state.rules = ruleData.items;

    // Alerts tab uses durable incident lifecycle data.
    state.alertIncidents = openIncidentData.items;
    state.alertIncidentHistory = historyIncidentData.items;

    state.syncRuns = syncData.items;
    populateAccountSelector(overviewData.accounts || []);
    populateFilterOptions(botData.filters);
    applyBotFilters(); renderOverview(); renderAlerts(); renderSystem();
    renderBotControlAccess();
if (state.adminUser && state.activeTab === 'wallet') {
  await Promise.all([
    loadPrivateBalance({ quiet: true }),
    loadDepositHistory({ quiet: true }),
  ]);
}
  } catch (error) {
    $('#connectionDot').className = 'offline'; $('#connectionText').textContent = 'API unavailable';
    showToast(error.message, true);
  }
}

async function syncNow() {
  if (!state.adminUser) { openAdminDialog(); return; }
  const button = $('#syncButton');
  button.disabled = true;
  button.textContent = 'Syncing…';
  try {
    const result = await adminApi(scopedPath('/api/sync'), { method: 'POST' });
    if (result.status === 'error') throw new Error(result.error || 'Sync failed');
    const scope = result.requested_account_id || state.selectedAccount || 'authorized account(s)';
    showToast(result.status === 'skipped' ? 'A sync is already running.' : `Sync complete for ${scope}: ${result.bot_count ?? 0} bots`);
    await loadCore();
    await loadPrivateBalance({ force: true, quiet: true });
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; button.textContent = 'Sync Gate'; }
}

async function openBot(botId) {
  try {
    const hours = Number($('#botHistoryRange').value);
    const [detail, history] = await Promise.all([
      api(`/api/bots/${botId}`),
      api(`/api/bots/${botId}/history?hours=${hours}`),
    ]);
    state.currentBot = botId;
    state.currentBotData = detail;
    state.currentBotHistory = history.items;
    state.currentRawData = null;
    renderBotDialog(detail, history);
    if (!$('#botDialog').open) $('#botDialog').showModal();
    if (canManageAccount(detail.bot.account_id)) await loadCurrentBotRaw();
  } catch (error) { showToast(error.message, true); }
}

function renderBotDialog(detail, history) {
  const bot = detail.bot;
  $('#dialogTitle').textContent = bot.strategy_name;
  $('#dialogSubtitle').textContent = `${bot.account_name} · ${bot.market} · ${strategyLabel(bot.strategy_type)} · ${bot.strategy_id}`;
  const totalPnl = bot.total_profit ?? bot.pnl;
  const rate = bot.profit_rate ?? bot.pnl_rate;

  const realizedPnl = (
    bot.realized_pnl
    ?? bot.grid_profit
  );

  const totalPnlNumber = numericValue(totalPnl);
  const realizedPnlNumber = numericValue(realizedPnl);

  const unrealizedPnl = hasValue(bot.floating_pnl)
    ? bot.floating_pnl
    : (
      totalPnlNumber !== null
      && realizedPnlNumber !== null
        ? totalPnlNumber - realizedPnlNumber
        : null
    );

  const annualizedApr = annualizedAprPct(
    rate,
    bot.runtime_seconds,
  );

  const stats = [
    [
      'Invested',
      fmtMoney(bot.invest_amount),
      null,
    ],
    [
      'Current value',
      fmtMoney(bot.current_value),
      totalPnl,
    ],
    [
      'Total PnL',
      fmtMoney(totalPnl),
      totalPnl,
    ],
    [
      'Realized PnL',
      fmtMoney(realizedPnl),
      realizedPnl,
    ],
    [
      'Unrealized PnL',
      fmtMoney(unrealizedPnl),
      unrealizedPnl,
    ],
    [
      'ROI',
      fmtRatioPct(rate),
      rate,
    ],
    [
      'Annualized APR',
      fmtPct(annualizedApr),
      annualizedApr,
    ],
    [
      'Grid records / cycles',
      fmtNumber(bot.arbitrage_count, 0),
      null,
    ],
    [
      'Runtime',
      fmtDuration(bot.runtime_seconds),
      null,
    ],
    [
      'Max drawdown',
      fmtPct(history.analytics?.max_drawdown_pct),
      -(history.analytics?.max_drawdown_pct || 0),
    ],
    [
      'Status',
      botDisplayStatus(bot).label,
      null,
    ],
  ];

  $('#botDetailMetrics').innerHTML = stats
    .map(([label, value, cls]) => (
      `<div class="detail-stat">`
      + `<span>${label}</span>`
      + `<strong class="${
        cls === null ? '' : valueClass(cls)
      }">${escapeHtml(value)}</strong>`
      + `</div>`
    ))
    .join('');

  $('#drawdownSummary').textContent = `Max ${fmtPct(history.analytics?.max_drawdown_pct)} · Current ${fmtPct(history.analytics?.current_drawdown_pct)} · Peak ${fmtMoney(history.analytics?.peak_value)}`;
  const {
    base: baseAsset,
    quote: quoteAsset,
  } = marketAssets(bot.market);

  const leveragedStrategies = new Set([
    'futures_grid',
    'margin_grid',
    'contract_martingale',
  ]);

  const isLeveraged = leveragedStrategies.has(
    bot.strategy_type
  );

  const amountNumber = numericValue(
    bot.position_amount
  );

  const entryNumber = numericValue(
    bot.entry_price
  );

  const calculatedPositionValue = (
    amountNumber !== null
    && entryNumber !== null
  )
    ? amountNumber * entryNumber
    : null;

  const positionValue = hasValue(
    bot.position_value
  )
    ? bot.position_value
    : calculatedPositionValue;

  const definitions = [
    ['Account', bot.account_name],
    ['Account ID', bot.account_id],
    ['Strategy ID', bot.strategy_id],
    ['Type', strategyLabel(bot.strategy_type)],
    ['Market', bot.market || '—'],
    ['Gate status', bot.source_status],
    ['Created', fmtDate(bot.created_at_gate)],
    ['Last seen', fmtDate(bot.last_seen_at)],
  ];

  const addDefinition = (
    label,
    value,
    present = true,
  ) => {
    if (present) {
      definitions.push([label, value]);
    }
  };

  addDefinition(
    'Base asset',
    baseAsset,
    Boolean(baseAsset),
  );

  addDefinition(
    'Quote asset',
    quoteAsset,
    Boolean(quoteAsset),
  );

  addDefinition(
    'Price range',
    fmtPriceRange(bot.price_range, quoteAsset),
    Boolean(bot.price_range),
  );

  addDefinition(
    'Grid count',
    fmtNumber(bot.grid_count, 0),
    hasValue(bot.grid_count),
  );

  addDefinition(
    'Finished rounds',
    fmtNumber(bot.finished_rounds, 0),
    hasValue(bot.finished_rounds),
  );

  addDefinition(
    'Position amount',
    (
      `${fmtNumber(bot.position_amount, 8)}`
      + `${baseAsset ? ` ${baseAsset}` : ''}`
    ),
    hasValue(bot.position_amount),
  );

  addDefinition(
    'Entry price',
    fmtPrice(bot.entry_price, quoteAsset),
    hasValue(bot.entry_price),
  );

  addDefinition(
    'Position value',
    fmtQuoteValue(positionValue, quoteAsset),
    hasValue(positionValue),
  );

  addDefinition(
    'Quote amount',
    fmtQuoteValue(bot.quote_amount, quoteAsset),
    (
      hasValue(bot.quote_amount)
      && !sameNumericValue(
        bot.quote_amount,
        positionValue,
      )
    ),
  );

  addDefinition(
    'Average cost',
    fmtPrice(bot.avg_cost, quoteAsset),
    (
      hasValue(bot.avg_cost)
      && !sameNumericValue(
        bot.avg_cost,
        bot.entry_price,
      )
    ),
  );

  addDefinition(
    'Price floor',
    fmtPrice(bot.price_floor, quoteAsset),
    hasValue(bot.price_floor),
  );

  addDefinition(
    'Take-profit price',
    fmtPrice(
      bot.take_profit_price,
      quoteAsset,
    ),
    hasValue(bot.take_profit_price),
  );

  if (isLeveraged) {
    addDefinition(
      'Position side',
      bot.position_side,
      Boolean(bot.position_side),
    );

    addDefinition(
      'Margin',
      fmtQuoteValue(bot.margin, quoteAsset),
      hasValue(bot.margin),
    );

    addDefinition(
      'Liquidation price',
      fmtPrice(
        bot.estimated_liquidation_price,
        quoteAsset,
      ),
      hasValue(
        bot.estimated_liquidation_price
      ),
    );

    addDefinition(
      'Maintenance margin',
      fmtPct(bot.maintenance_margin_ratio),
      hasValue(
        bot.maintenance_margin_ratio
      ),
    );
  }

  definitions.push([
    'Stop supported',
    bot.stop_supported ? 'Yes' : 'No',
  ]);

  $('#botDefinitionList').innerHTML = definitions
    .map(([key, value]) => (
      `<dt>${escapeHtml(key)}</dt>`
      + `<dd>${escapeHtml(value)}</dd>`
    ))
    .join('');
  state.currentRawKey = 'metrics';
  $$('.raw-tab').forEach(t => t.classList.toggle('active', t.dataset.raw === 'metrics'));
  renderBotRaw();
  updateBotAdminControls(bot);
  drawBotChart();
}

function updateBotAdminControls(bot) {
  const ownsBot = canManageAccount(
    bot.account_id
  );

  const available =
    botStopSubmissionAvailableForAccount(
      bot.account_id
    );

  const stopEnabled = Boolean(
    available
    && bot.stop_supported
    && ownsBot
  );

  $('#stopBotButton').disabled =
    !stopEnabled;

  const message = $('#dangerZone p');

  if (!state.adminUser) {
    message.textContent = (
      'Unlock the matching account before using '
      + 'Bot Control actions.'
    );

  } else if (!ownsBot) {
    message.textContent = (
      `Signed in as ${state.adminUser.username}; `
      + `this bot belongs to ${bot.account_name}.`
    );

  } else if (!bot.stop_supported) {
    message.textContent = (
      'Gate reports Stop is unavailable for '
      + 'this strategy.'
    );

  } else if (botStopSimulation()) {
    message.textContent = (
      'Stop simulation mode. The complete Bot '
      + 'Control workflow will run, but no Gate '
      + 'Stop request will be sent.'
    );

  } else if (
    botStopLive()
    && botControlAccountLiveEnabled(
      bot.account_id
    )
  ) {
    message.textContent = (
      'LIVE Bot Stop is enabled. A final typed '
      + 'confirmation is required.'
    );

  } else if (botStopLive()) {
    message.textContent = (
      'LIVE Bot Stop is not enabled for this '
      + 'account.'
    );

  } else {
    message.textContent = (
      'Bot stopping is disabled on the server.'
    );
  }

  const button = $('#stopBotButton');

  if (button) {
    button.textContent = (
      botStopSimulation()
      && !botStopEnabled()
        ? 'Simulate stop'
        : 'Stop bot'
    );
  }
}

async function loadCurrentBotRaw() {
  const bot = state.currentBotData?.bot;
  if (!bot || !canManageAccount(bot.account_id)) { renderBotRaw(); return; }
  try {
    const result = await adminApi(`/api/bots/${bot.id}/raw`);
    state.currentRawData = result.bot;
    renderBotRaw();
  } catch (error) {
    $('#botRaw').textContent = error.message;
  }
}

function renderBotRaw() {
  const bot = state.currentBotData?.bot;
  if (!bot) return;
  if (!state.adminUser) {
    $('#botRaw').textContent = 'Unlock the matching account to inspect Gate raw data.';
    return;
  }
  if (!canManageAccount(bot.account_id)) {
    $('#botRaw').textContent = `This login cannot inspect data for ${bot.account_name}.`;
    return;
  }
  if (!state.currentRawData) {
    $('#botRaw').textContent = 'Loading authorized Gate data…';
    return;
  }
  $('#botRaw').textContent = JSON.stringify(state.currentRawData[state.currentRawKey] ?? {}, null, 2);
}


function drawBotChart() {
  const css = getComputedStyle(document.documentElement);
  drawSeriesChart($('#botChart'), state.currentBotHistory, [
    { key: 'current_value', color: css.getPropertyValue('--accent').trim(), fill: 'rgba(23,211,154,.14)' },
    { key: 'total_profit', color: css.getPropertyValue('--blue').trim() },
  ]);
}

async function stopCurrentBot() {
  const bot = state.currentBotData?.bot;

  if (!bot) return;

  if (!canManageAccount(bot.account_id)) {
    openAdminDialog();
    return;
  }

  if (
    !botStopSubmissionAvailableForAccount(
      bot.account_id
    )
  ) {
    showToast(
      botStopLive()
        ? (
          'LIVE Bot Stop is not enabled '
          + 'for this account.'
        )
        : (
          'Bot stopping is disabled '
          + 'on the server.'
        ),
      true,
    );
    return;
  }

  if (!bot.stop_supported) {
    showToast(
      'Gate reports Stop is unavailable for '
      + 'this strategy.',
      true,
    );
    return;
  }

  const button = $('#stopBotButton');

  button.disabled = true;
  button.textContent = 'Checking Gate…';

  try {
    const prepared = await adminApi(
      `/api/bot-control/bots/${bot.id}/stop/prepare`
    );

    state.botStopPrepared = prepared;
    state.botStopRequestId = '';

    renderBotStopConfirmation(
      prepared
    );

    const dialog = $('#stopBotConfirmDialog');

    if (!dialog.open) {
      dialog.showModal();
    }

    setTimeout(
      () => $('#stopBotConfirmText')?.focus(),
      0,
    );

  } catch (error) {
    showToast(
      botControlErrorMessage(error),
      true,
    );

  } finally {
    updateBotAdminControls(bot);
  }
}

function renderBotStopConfirmation(prepared) {
  const bot = prepared.bot || {};
  const gate = prepared.gate_snapshot || {};
  const estimate =
    prepared.stop_return_estimate || {};

  const formatEstimateAmount = (
    amount,
    currency,
  ) => {
    if (
      amount === null
      || amount === undefined
      || amount === ''
    ) {
      return '—';
    }

    const numeric = Number(amount);

    const formatted = Number.isFinite(numeric)
      ? numeric.toLocaleString(
        undefined,
        {
          maximumFractionDigits: 8,
        },
      )
      : String(amount);

    return currency
      ? `${formatted} ${currency}`
      : formatted;
  };

  const estimateConfidence = (
    estimate.confidence
    && estimate.confidence !== 'unavailable'
  )
    ? (
      estimate.confidence.charAt(0).toUpperCase()
      + estimate.confidence.slice(1)
    )
    : '—';

  const pnlNumeric = Number(bot.total_profit);

  const pnlClass = Number.isFinite(pnlNumeric)
    ? (
      pnlNumeric > 0
        ? 'positive'
        : pnlNumeric < 0
          ? 'negative'
          : ''
    )
    : '';

  $('#stopBotConfirmSummary').innerHTML = `
    <section class="bot-stop-strategy-card">
      <div class="bot-stop-strategy-heading">
        <div>
          <span class="bot-stop-card-label">Strategy</span>
          <strong>
            ${escapeHtml(
              bot.strategy_name
              || bot.strategy_id
              || '—'
            )}
          </strong>
        </div>

        <span class="bot-stop-account-badge">
          ${escapeHtml(bot.account_id || '—')}
        </span>
      </div>

      <div class="bot-stop-strategy-meta">
        <div>
          <span>Strategy ID</span>
          <strong>${escapeHtml(bot.strategy_id || '—')}</strong>
        </div>

        <div>
          <span>Market</span>
          <strong>${escapeHtml(bot.market || '—')}</strong>
        </div>

        <div>
          <span>Type</span>
          <strong>${escapeHtml(bot.strategy_type || '—')}</strong>
        </div>
      </div>

      <div class="bot-stop-status-row">
        <div class="bot-stop-status-item">
          <span>Dashboard</span>
          <strong class="bot-stop-status-badge">
            ${escapeHtml(bot.status || '—')}
          </strong>
        </div>

        <div class="bot-stop-status-item">
          <span>Gate</span>
          <strong class="bot-stop-status-badge">
            ${escapeHtml(gate.status || '—')}
          </strong>
        </div>
      </div>
    </section>

    <section class="bot-stop-financial-cards">
      <div class="bot-stop-financial-card">
        <span>Investment</span>
        <strong>
          ${
            bot.invest_amount
              ? escapeHtml(fmtMoney(bot.invest_amount))
              : '—'
          }
        </strong>
      </div>

      <div class="bot-stop-financial-card">
        <span>Current value</span>
        <strong>
          ${
            bot.current_value
              ? escapeHtml(fmtMoney(bot.current_value))
              : '—'
          }
        </strong>
      </div>

      <div class="bot-stop-financial-card ${pnlClass}">
        <span>Total PnL</span>
        <strong>
          ${
            bot.total_profit !== null
            && bot.total_profit !== undefined
              ? escapeHtml(fmtMoney(bot.total_profit))
              : '—'
          }
        </strong>
      </div>
    </section>
  `;

  const estimatePanel = $('#stopBotReturnEstimate');

  if (estimatePanel) {
    if (estimate.available) {
      const baseReturn = formatEstimateAmount(
        estimate.base?.amount,
        estimate.base?.currency,
      );

      const quoteReturn = formatEstimateAmount(
        estimate.quote?.amount,
        estimate.quote?.currency,
      );

      const totalReturn = formatEstimateAmount(
        estimate.estimated_total_quote_value,
        estimate.quote?.currency,
      );

      const confidenceText = (
        estimateConfidence !== '—'
          ? `${estimateConfidence} confidence`
          : ''
      );

      estimatePanel.innerHTML = `
        <div class="bot-stop-return-heading">
          <div>
            <strong>Estimated return if stopped now</strong>
            <span>Current market estimate</span>
          </div>
          ${
            confidenceText
              ? (
                '<span class="bot-stop-return-confidence">'
                + escapeHtml(confidenceText)
                + '</span>'
              )
              : ''
          }
        </div>

        <div class="bot-stop-return-assets">
          <div class="bot-stop-return-asset">
            <span>Base asset</span>
            <strong>${escapeHtml(baseReturn)}</strong>
          </div>

          <div class="bot-stop-return-asset">
            <span>Quote asset</span>
            <strong>${escapeHtml(quoteReturn)}</strong>
          </div>
        </div>

        <div class="bot-stop-return-total">
          <span>Estimated total value</span>
          <strong>${escapeHtml(totalReturn)}</strong>
        </div>

        <p class="bot-stop-return-note">
          Actual Gate settlement may differ because orders
          can fill or be cancelled while Stop is processed.
        </p>
      `;

      estimatePanel.classList.remove('hidden');

    } else {
      estimatePanel.innerHTML = '';
      estimatePanel.classList.add('hidden');
    }
  }

  const messages = [];

  (prepared.errors || []).forEach(
    message => {
      messages.push(
        '<div class="bot-control-message error">'
        + `${escapeHtml(message)}`
        + '</div>'
      );
    },
  );

  (prepared.warnings || []).forEach(
    message => {
      messages.push(
        '<div class="bot-control-message warning">'
        + `${escapeHtml(message)}`
        + '</div>'
      );
    },
  );

  if (
    !(prepared.errors || []).length
    && !(prepared.warnings || []).length
  ) {
    messages.push(
      '<div class="bot-control-message success">'
      + 'Stop preflight passed.'
      + '</div>'
    );
  }

  $('#botStopValidationMessages').innerHTML =
    messages.join('');

  const accountId = String(
    bot.account_id || ''
  )
    .trim()
    .toLowerCase();

  const liveGloballyEnabled =
    botStopLive();

  const live = Boolean(
    liveGloballyEnabled
    && botControlAccountLiveEnabled(
      accountId
    )
  );

  const notice = $('#botStopSafetyNotice');

  notice.classList.toggle(
    'enabled',
    live,
  );

  notice.textContent = live
    ? (
      'LIVE BOT STOP IS ENABLED. Submitting this '
      + 'confirmation can stop the live Gate strategy.'
    )
    : botStopSimulation()
      ? (
        'SIMULATION MODE. The Stop operation will be '
        + 'validated, reserved and audited, but NO '
        + 'Gate Stop request will be sent.'
      )
      : liveGloballyEnabled
        ? (
          'LIVE Bot Stop is not enabled for this '
          + 'account. No Gate Stop request can be '
          + 'submitted for this account.'
        )
        : (
          'Bot stopping is disabled on the server.'
        );

  const requiredConfirmation =
    botStopRequiredConfirmation();

  $('#stopBotRequiredConfirmation').textContent =
    requiredConfirmation;

  $('#stopBotConfirmText').placeholder =
    requiredConfirmation;

  $('#stopBotConfirmText').value = '';

  const errorBox = $('#stopBotConfirmError');

  errorBox.textContent = '';
  errorBox.classList.add('hidden');

  updateBotStopConfirmButton();
}

function updateBotStopConfirmButton() {
  const button = $('#confirmStopBot');

  if (!button) return;

  button.disabled = !(
    botStopSubmissionAvailableForAccount(
      state.botStopPrepared?.bot?.account_id
    )
    && state.botStopPrepared?.can_stop
    && $('#stopBotConfirmText')?.value
      === botStopRequiredConfirmation()
  );

  button.textContent = (
    botStopSimulation()
    && !botStopEnabled()
      ? 'Simulate Stop'
      : 'Stop Bot'
  );
}

async function submitBotStop() {
  const prepared = state.botStopPrepared;

  if (!prepared?.can_stop) {
    return;
  }

  const accountId = String(
    prepared.bot?.account_id || ''
  )
    .trim()
    .toLowerCase();

  if (
    !botStopSubmissionAvailableForAccount(
      accountId
    )
  ) {
    return;
  }

  const modeBefore = botStopMode();

  const accountLiveBefore =
    botStopSubmissionAvailableForAccount(
      accountId
    );

  try {
    await refreshBotControlRuntimeHealth();

    /*
     * Runtime health contains the global Stop arm.
     * Auth capabilities contain account eligibility.
     * Re-read BOTH before any live Stop POST.
     */
    state.botControlCapabilities = await adminApi(
      '/api/auth/capabilities'
    );

    renderBotControlAccess();

    if (state.currentBotData?.bot) {
      updateBotAdminControls(
        state.currentBotData.bot
      );
    }

  } catch (error) {
    const errorBox =
      $('#stopBotConfirmError');

    errorBox.textContent = (
      'Unable to refresh Bot Control safety state. '
      + 'No Stop request was submitted.'
    );

    errorBox.classList.remove('hidden');
    return;
  }

  const modeAfter = botStopMode();

  const accountLiveAfter =
    botStopSubmissionAvailableForAccount(
      accountId
    );

  if (
    modeAfter !== modeBefore
    || accountLiveAfter !== accountLiveBefore
    || !accountLiveAfter
  ) {
    renderBotStopConfirmation(
      prepared
    );

    const errorBox =
      $('#stopBotConfirmError');

    errorBox.textContent = (
      'Bot Control mode or account policy changed '
      + 'on the server. Review the updated state and '
      + 'confirm again.'
    );

    errorBox.classList.remove('hidden');
    return;
  }

  if (
    !botStopSubmissionAvailableForAccount(
      accountId
    )
  ) {
    return;
  }

  const requiredConfirmation =
    botStopRequiredConfirmation();

  if (
    $('#stopBotConfirmText').value
    !== requiredConfirmation
  ) {
    return;
  }

  if (!state.botStopRequestId) {
    state.botStopRequestId =
      generateBotControlRequestId(
        'bot-stop'
      );
  }

  const requestId =
    state.botStopRequestId;

  const botId = prepared.bot.id;

  const button = $('#confirmStopBot');
  const errorBox = $('#stopBotConfirmError');

  button.disabled = true;
  button.textContent = (
    botStopSimulation()
    && !botStopEnabled()
      ? 'Simulating…'
      : 'Submitting to Gate…'
  );

  errorBox.textContent = '';
  errorBox.classList.add('hidden');

  let result;

  /*
   * Only the actual mutation request belongs in this
   * try/catch. Once this returns successfully, Gate
   * submission succeeded from the UI's perspective.
   *
   * Later dashboard refresh failures must NEVER make
   * the operator think the Stop itself failed.
   */
  try {
    result = await adminApi(
      `/api/bot-control/bots/${botId}/stop`,
      {
        method: 'POST',
        body: JSON.stringify({
          request_id: requestId,
          confirmation: requiredConfirmation,
        }),
      },
    );

  } catch (error) {
    /*
     * Keep the SAME request ID after mutation failure.
     * The backend audit/idempotency layer decides
     * whether replay is safe.
     */
    errorBox.textContent =
      botControlErrorMessage(error);

    errorBox.classList.remove(
      'hidden'
    );

    updateBotStopConfirmButton();
    return;
  }

  const simulated = Boolean(
    result.simulation
    || result.status === 'simulated'
  );

  $('#stopBotConfirmDialog').close();

  /*
   * Persist the raw response immediately. Do this
   * before any secondary refresh work.
   */
  $('#apiInspector').textContent =
    JSON.stringify(
      result,
      null,
      2,
    );

  showToast(
    simulated
      ? (
        'Stop simulation completed. '
        + `Request ${requestId}. `
        + 'No Gate write performed.'
      )
      : (
        'Bot Stop submitted to Gate. '
        + `Request ${requestId}.`
      )
  );

  /*
   * For a live Stop, close the old strategy detail
   * before presenting the durable request record.
   */
  if (
    !simulated
    && $('#botDialog').open
  ) {
    $('#botDialog').close();
  }

  /*
   * Always show the persistent Bot Control request
   * after a successful submission. This contains the
   * request ID, status, Gate HTTP response and audit
   * evidence, so the operator is never dependent on a
   * transient toast.
   */
  await openBotControlRequestDetail(
    requestId
  );

  /*
   * Everything below is secondary refresh work.
   * Failures here must not be confused with mutation
   * failure because the Stop has already succeeded.
   */
  try {
    await loadBotControlActivity({
      quiet: true,
    });

  } catch (error) {
    showToast(
      'Stop was submitted successfully, but Bot '
      + 'Control Activity could not be refreshed. '
      + `Request ${requestId}.`,
      true,
    );
  }

  try {
    await loadCore();

  } catch (error) {
    showToast(
      'Stop was submitted successfully, but the '
      + 'dashboard could not be refreshed. '
      + `Request ${requestId}.`,
      true,
    );
  }

  updateBotStopConfirmButton();
}

function exportCsv() {
  const headers = ['account_id','account_name','strategy_id','strategy_name','strategy_type','market','status','invest_amount','current_value','total_profit','profit_rate','realized_pnl','grid_profit','floating_pnl','arbitrage_count','runtime_seconds','last_seen_at'];
  const quote = value => `"${String(value ?? '').replaceAll('"','""')}"`;
  const rows = [headers.join(','), ...state.filteredBots.map(bot => headers.map(key => quote(bot[key])).join(','))];
  const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `gate-bots-${new Date().toISOString().slice(0,10)}.csv`; a.click(); URL.revokeObjectURL(url);
}

async function acknowledgeIncident(id) {
  if (!state.adminUser) {
    openAdminDialog();
    return;
  }

  try {
    await adminApi(
      `/api/alerts/incidents/${id}/acknowledge`,
      {
        method: 'POST',
      },
    );

    await loadCore();

    showToast(
      'Incident acknowledged.'
    );
  } catch (error) {
    showToast(
      error.message,
      true,
    );
  }
}

async function toggleRule(id, enabled) {
  if (!state.adminUser) { openAdminDialog(); return; }
  try { await adminApi(`/api/alerts/rules/${id}`, { method:'PATCH', body:JSON.stringify({ enabled }) }); showToast(`Rule ${enabled ? 'enabled' : 'disabled'}.`); }
  catch (error) { showToast(error.message, true); await loadCore(); }
}

async function deleteRule(id) {
  if (!confirm('Delete this alert rule?')) return;
  if (!state.adminUser) { openAdminDialog(); return; }
  try { await adminApi(`/api/alerts/rules/${id}`, { method:'DELETE' }); await loadCore(); showToast('Rule deleted.'); }
  catch (error) { showToast(error.message, true); }
}

async function createRule(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = Object.fromEntries(form.entries());
  payload.threshold = Number(payload.threshold); payload.cooldown_seconds = Number(payload.cooldown_seconds); payload.bot_id = payload.bot_id ? Number(payload.bot_id) : null;
  if (!state.adminUser) { openAdminDialog(); return; }
  try { await adminApi('/api/alerts/rules', { method:'POST', body:JSON.stringify(payload) }); $('#ruleDialog').close(); event.currentTarget.reset(); await loadCore(); showToast('Alert rule created.'); }
  catch (error) { showToast(error.message, true); }
}

async function inspectEndpoint(endpoint) {
  const inspector = $('#apiInspector'); inspector.textContent = 'Loading…';
  if (!state.adminUser) { openAdminDialog(); inspector.textContent = 'Sign in to your account first.'; return; }
  try { inspector.textContent = JSON.stringify(await adminApi(endpoint), null, 2); }
  catch (error) { inspector.textContent = error.message; showToast(error.message, true); }
}

function bindEvents() {
  $$('.nav-item').forEach(button => button.addEventListener('click', () => switchTab(button.dataset.tab)));
  $$('[data-jump]').forEach(button => button.addEventListener('click', () => switchTab(button.dataset.jump)));
  $('#syncButton').addEventListener('click', syncNow);


  $('#botControlActivityBody')?.addEventListener(
    'click',
    event => {
      const button = event.target.closest(
        '[data-bot-control-request]'
      );

      if (!button) {
        return;
      }

      openBotControlRequestDetail(
        button.dataset.botControlRequest
      );
    },
  );

  $('#manualLockReleaseReason')?.addEventListener(
    'input',
    updateManualLockReleaseButton,
  );

  $('#manualLockReleaseConfirm')?.addEventListener(
    'input',
    updateManualLockReleaseButton,
  );

  $('#releaseBotControlLock')?.addEventListener(
    'click',
    releaseCurrentBotControlLock,
  );

  $('#reconcileBotControlRequest')?.addEventListener(
    'click',
    reconcileCurrentBotControlRequest,
  );

  $('#closeBotControlRequestDialog')?.addEventListener(
    'click',
    () => $('#botControlRequestDialog').close(),
  );

  $('#botControlRequestDialog')?.addEventListener(
    'click',
    event => {
      if (
        event.target
        === $('#botControlRequestDialog')
      ) {
        $('#botControlRequestDialog').close();
      }
    },
  );


  $('#refreshBotControlAttention')?.addEventListener(
    'click',
    () => loadBotControlAttention(),
  );

  $('#botControlAttentionList')?.addEventListener(
    'click',
    async event => {
      const reviewButton = event.target.closest(
        '[data-bot-control-attention-review]'
      );

      if (reviewButton) {
        const requestId = (
          reviewButton.dataset
            .botControlAttentionReview
          || ''
        );

        reviewButton.disabled = true;

        try {
          await adminApi(
            `/api/bot-control/attention/${
              encodeURIComponent(requestId)
            }/review`,
            {
              method: 'POST',
            },
          );

          await loadBotControlAttention();

          showToast(
            'Bot Control item marked reviewed.'
          );
        } catch (error) {
          reviewButton.disabled = false;
          showError(
            error?.message
            || 'Unable to mark item reviewed.'
          );
        }

        return;
      }

      const button = event.target.closest(
        '[data-bot-control-attention-request]'
      );

      if (!button) {
        return;
      }

      openBotControlRequestDetail(
        button.dataset
          .botControlAttentionRequest
      );
    },
  );


  $('#exportBotControlJson')?.addEventListener(
    'click',
    () => downloadBotControlAuditExport(
      'json'
    ),
  );

  $('#exportBotControlCsv')?.addEventListener(
    'click',
    () => downloadBotControlAuditExport(
      'csv'
    ),
  );

  $('#refreshBotControlActivity')?.addEventListener(
    'click',
    () => loadBotControlActivity(),
  );

  $('#botControlActivityPageSize')?.addEventListener(
    'change',
    event => {
      const limit = Number(
        event.currentTarget.value
      );

      if (![10, 25, 50].includes(limit)) {
        return;
      }

      loadBotControlActivity({
        limit,
        offset: 0,
      });
    },
  );

  $('#botControlActivityPrevious')?.addEventListener(
    'click',
    () => {
      const pagination = (
        state.botControlActivityPagination
        || {}
      );

      if (!pagination.hasPrevious) {
        return;
      }

      const limit = (
        Number(pagination.limit)
        || 10
      );

      loadBotControlActivity({
        offset: Math.max(
          0,
          (
            Number(pagination.offset)
            || 0
          ) - limit,
        ),
      });
    },
  );

  $('#botControlActivityNext')?.addEventListener(
    'click',
    () => {
      const pagination = (
        state.botControlActivityPagination
        || {}
      );

      if (!pagination.hasNext) {
        return;
      }

      const limit = (
        Number(pagination.limit)
        || 10
      );

      loadBotControlActivity({
        offset: (
          Number(pagination.offset)
          || 0
        ) + limit,
      });
    },
  );

  $('#spotGridForm')?.addEventListener(
    'submit',
    prepareSpotGrid,
  );

  $('#resetSpotGridButton')?.addEventListener(
    'click',
    resetSpotGridForm,
  );

  $('#spotGridForm')?.addEventListener(
    'input',
    invalidateSpotGridReview,
  );

  $('#spotGridForm')?.addEventListener(
    'change',
    invalidateSpotGridReview,
  );

  $('#spotGridAccount')?.addEventListener(
    'change',
    () => {
      renderBotControlCreateState();
      updateSpotGridConfirmButton();
    },
  );

  $('#openSpotGridConfirmation')?.addEventListener(
    'click',
    openSpotGridConfirmation,
  );

  $('#spotGridConfirmText')?.addEventListener(
    'input',
    updateSpotGridConfirmButton,
  );

  $('#confirmSpotGridCreate')?.addEventListener(
    'click',
    submitSpotGridCreate,
  );

  $('#closeSpotGridConfirmDialog')?.addEventListener(
    'click',
    () => $('#spotGridConfirmDialog').close(),
  );

  $('#cancelSpotGridCreate')?.addEventListener(
    'click',
    () => $('#spotGridConfirmDialog').close(),
  );

  $('#spotGridConfirmDialog')?.addEventListener(
    'click',
    event => {
      if (
        event.target
        === $('#spotGridConfirmDialog')
      ) {
        $('#spotGridConfirmDialog').close();
      }
    },
  );
  $('#refreshTreasury')?.addEventListener(
    'click',
    () => loadTreasuryOverview(),
  );

  $('#treasuryWithdrawalForm')?.addEventListener(
    'submit',
    runTreasuryWithdrawalPreflight,
  );

  $('#treasuryWithdrawalDestination')?.addEventListener(
    'change',
    invalidateTreasuryWithdrawalPreflight,
  );

  $('#treasuryWithdrawalAmount')?.addEventListener(
    'input',
    invalidateTreasuryWithdrawalPreflight,
  );

  $('#createTreasuryWithdrawalRequest')?.addEventListener(
    'click',
    createTreasuryWithdrawalRequest,
  );

  $('#treasuryWithdrawalRequestBody')?.addEventListener(
    'click',
    event => {
      const button = event.target.closest(
        '[data-treasury-withdrawal-request]'
      );

      if (!button) return;

      openTreasuryWithdrawalRequestDetail(
        button.dataset.treasuryWithdrawalRequest
      );
    },
  );

  $('#treasuryWithdrawalConfirmation')?.addEventListener(
    'input',
    updateTreasuryWithdrawalLifecycleButtons,
  );

  $('#reserveTreasuryWithdrawalRequest')?.addEventListener(
    'click',
    reserveCurrentTreasuryWithdrawal,
  );

  $('#confirmTreasuryWithdrawalRequest')?.addEventListener(
    'click',
    confirmCurrentTreasuryWithdrawal,
  );

  $('#prepareTreasuryWithdrawalJit')?.addEventListener(
    'click',
    prepareCurrentTreasuryWithdrawalJit,
  );

  $('#closeTreasuryWithdrawalRequestDialog')?.addEventListener(
    'click',
    () => $('#treasuryWithdrawalRequestDialog').close(),
  );

  $('#treasuryWithdrawalRequestDialog')?.addEventListener(
    'click',
    event => {
      if (
        event.target.closest(
          '#settleTreasuryWithdrawal'
        )
      ) {
        settleCurrentTreasuryWithdrawal();
        return;
      }

      if (
        event.target.closest(
          '#executeTreasuryExternalWithdrawal'
        )
      ) {
        executeCurrentTreasuryExternalWithdrawal();
        return;
      }

      if (
        event.target.closest(
          '#reconcileTreasuryExternalWithdrawal'
        )
      ) {
        reconcileCurrentTreasuryExternalWithdrawal();
        return;
      }

      if (
        event.target.closest(
          '#executeTreasuryWithdrawalJit'
        )
      ) {
        executeCurrentTreasuryWithdrawalJit();
        return;
      }

      if (
        event.target.closest(
          '#reconcileTreasuryWithdrawalJit'
        )
      ) {
        reconcileCurrentTreasuryWithdrawalJit();
        return;
      }

      if (
        event.target
        === $('#treasuryWithdrawalRequestDialog')
      ) {
        $('#treasuryWithdrawalRequestDialog').close();
      }
    },
  );

  $('#treasuryActivityBody')?.addEventListener(
    'click',
    event => {
      const button = event.target.closest(
        '[data-treasury-request]'
      );

      if (!button) return;

      openTreasuryRequestDetail(
        button.dataset.treasuryRequest
      );
    },
  );

  $('#treasuryLockList')?.addEventListener(
    'click',
    event => {
      const button = event.target.closest(
        '[data-treasury-request]'
      );

      if (!button) return;

      openTreasuryRequestDetail(
        button.dataset.treasuryRequest
      );
    },
  );

  $('#reconcileTreasuryRequest')?.addEventListener(
    'click',
    reconcileCurrentTreasuryRequest,
  );

  $('#treasuryReleaseReason')?.addEventListener(
    'input',
    updateTreasuryReleaseButton,
  );

  $('#treasuryReleaseConfirmation')?.addEventListener(
    'input',
    updateTreasuryReleaseButton,
  );

  $('#releaseTreasuryLock')?.addEventListener(
    'click',
    releaseCurrentTreasuryLock,
  );

  $('#closeTreasuryRequestDialog')?.addEventListener(
    'click',
    () => $('#treasuryRequestDialog').close(),
  );

  $('#treasuryRequestDialog')?.addEventListener(
    'click',
    event => {
      if (
        event.target
        === $('#treasuryRequestDialog')
      ) {
        $('#treasuryRequestDialog').close();
      }
    },
  );

  $('#refreshPrivateBalance').addEventListener('click', () => loadPrivateBalance({ force: true }));
  $('#depositButton').addEventListener('click', openDepositDialog);
  $('#refreshDepositHistory').addEventListener('click', () => loadDepositHistory());
  $('#syncDepositHistory').addEventListener('click', syncDepositHistory);
  $('#closeDepositDialog').addEventListener('click', closeDepositDialog);
  $('#depositDialog').addEventListener('click', event => { if (event.target === $('#depositDialog')) closeDepositDialog(); });
  $('#depositCurrencySearch').addEventListener('input', renderDepositCurrencies);
  $('#accountSelector').addEventListener('change', event => { state.selectedAccount = event.target.value; closeDepositDialog(); loadCore(); });
  $('#historyRange').addEventListener('change', loadCore);
  ['#botSearch','#statusFilter','#typeFilter','#marketFilter','#sortFilter'].forEach(selector => $(selector).addEventListener(selector === '#botSearch' ? 'input' : 'change', applyBotFilters));
  $('#exportCsv').addEventListener('click', exportCsv);
  document.addEventListener('click', event => {
    const archiveButton =
      event.target.closest(
        '[data-archive-bot-id]'
      );

    if (archiveButton) {
      archiveBot(
        Number(
          archiveButton.dataset
            .archiveBotId
        )
      );

      return;
    }

    const restoreButton =
      event.target.closest(
        '[data-restore-bot-id]'
      );

    if (restoreButton) {
      restoreBot(
        Number(
          restoreButton.dataset
            .restoreBotId
        )
      );

      return;
    }

    const botButton = event.target.closest('[data-bot-id]'); if (botButton) openBot(Number(botButton.dataset.botId));

    const incidentAck = event.target.closest('.ack-incident');

    if (incidentAck) {
      acknowledgeIncident(
        Number(
          incidentAck.dataset.incidentId
        )
      );

      return;
    }

    const del = event.target.closest('.delete-rule'); if (del) deleteRule(Number(del.dataset.ruleId));
    const depositCurrency = event.target.closest('[data-deposit-currency]'); if (depositCurrency) selectDepositCurrency(depositCurrency.dataset.depositCurrency);
    const depositChain = event.target.closest('[data-deposit-chain]'); if (depositChain) selectDepositNetwork(depositChain.dataset.depositChain);
    const depositCopy = event.target.closest('[data-copy-deposit]'); if (depositCopy) copyDepositValue(depositCopy.dataset.copyDeposit);
  });
  document.addEventListener('change', event => { if (event.target.matches('.rule-toggle')) toggleRule(Number(event.target.dataset.ruleId), event.target.checked); });
  $('#closeDialog').addEventListener('click', () => $('#botDialog').close());
  $('#botDialog').addEventListener('click', event => { if (event.target === $('#botDialog')) $('#botDialog').close(); });
  $('#botHistoryRange').addEventListener('change', () => state.currentBot && openBot(state.currentBot));
  $$('.raw-tab').forEach(button => button.addEventListener('click', async () => { state.currentRawKey = button.dataset.raw; $$('.raw-tab').forEach(t => t.classList.toggle('active', t === button)); if (!state.currentRawData && state.currentBotData?.bot && canManageAccount(state.currentBotData.bot.account_id)) await loadCurrentBotRaw(); else renderBotRaw(); }));
  $('#stopBotButton').addEventListener(
    'click',
    stopCurrentBot,
  );

  $('#stopBotConfirmText')?.addEventListener(
    'input',
    updateBotStopConfirmButton,
  );

  $('#confirmStopBot')?.addEventListener(
    'click',
    submitBotStop,
  );

  $('#closeStopBotConfirmDialog')?.addEventListener(
    'click',
    () => $('#stopBotConfirmDialog').close(),
  );

  $('#cancelStopBot')?.addEventListener(
    'click',
    () => $('#stopBotConfirmDialog').close(),
  );

  $('#stopBotConfirmDialog')?.addEventListener(
    'click',
    event => {
      if (
        event.target
        === $('#stopBotConfirmDialog')
      ) {
        $('#stopBotConfirmDialog').close();
      }
    },
  );
  $('#addRuleButton').addEventListener('click', () => { if (!state.adminUser) { openAdminDialog(); return; } populateFilterOptions(); $('#ruleDialog').showModal(); });
  $('#closeRuleDialog').addEventListener('click', () => $('#ruleDialog').close()); $('#cancelRule').addEventListener('click', () => $('#ruleDialog').close());
  $('#ruleForm').addEventListener('submit', createRule);
  $('#testAccountButton').addEventListener('click', () => inspectEndpoint(scopedPath('/api/account')));
  $('#loadRecommendations').addEventListener('click', () => inspectEndpoint(scopedPath('/api/recommendations', { limit: 10 })));
  $('#clearInspector').addEventListener('click', () => { $('#apiInspector').textContent = 'Select an action above to inspect a response.'; });
  $('#adminButton').addEventListener('click', () => state.adminUser ? lockAdmin() : openAdminDialog());
  $('#changePasswordButton').addEventListener('click', openChangePasswordDialog);
  $('#adminForm').addEventListener('submit', unlockAdmin);
  $('#closeAdminDialog').addEventListener('click', () => $('#adminDialog').close());
  $('#cancelAdmin').addEventListener('click', () => $('#adminDialog').close());
  $('#adminDialog').addEventListener('click', event => { if (event.target === $('#adminDialog')) $('#adminDialog').close(); });
  $('#changePasswordForm').addEventListener('submit', changeOwnPassword);
  $('#closeChangePasswordDialog').addEventListener('click', () => $('#changePasswordDialog').close());
  $('#cancelChangePassword').addEventListener('click', () => $('#changePasswordDialog').close());
  $('#changePasswordDialog').addEventListener('click', event => { if (event.target === $('#changePasswordDialog')) $('#changePasswordDialog').close(); });
  window.addEventListener('hashchange', () => {
    switchTab(window.location.hash.slice(1), { updateHash: false });
  });
  window.addEventListener('resize', () => { drawPortfolioChart(); if ($('#botDialog').open) drawBotChart(); });
}

const footerYear = document.getElementById("footer-year");

if (footerYear) {
  footerYear.textContent = new Date().getFullYear();
}

/*
 * Ownership-ledger entries reference the Treasury transfer
 * request that caused the accounting entry. Open the same
 * request-detail dialog used by Treasury activity.
 */
document.addEventListener('click', event => {
  const target = (
    event.target instanceof Element
      ? event.target
      : null
  );

  const button = target?.closest(
    '#treasuryOwnershipLedgerBody '
    + '[data-treasury-request]'
  );

  if (!button) {
    return;
  }

  const requestId = String(
    button.dataset.treasuryRequest || ''
  );

  if (requestId) {
    openTreasuryRequestDetail(requestId);
  }
});


bindEvents();
renderAdminState();
switchTab(window.location.hash.slice(1) || 'overview', { updateHash: false });
loadCore();
setInterval(loadCore, 60000);


function bindTreasuryUserTransferEvents() {
  const form = $('#treasuryUserTransferForm');

  if (
    form
    && form.dataset.userTransferEventsBound !== 'true'
  ) {
    form.dataset.userTransferEventsBound = 'true';

    form.addEventListener(
      'submit',
      runTreasuryUserTransferPreview,
    );
  }

  const source = $('#treasuryUserTransferSource');

  if (
    source
    && source.dataset.userTransferEventsBound !== 'true'
  ) {
    source.dataset.userTransferEventsBound = 'true';

    source.addEventListener('change', () => {
      invalidateTreasuryUserTransferPreview();
      renderTreasuryUserTransferParticipants();
    });
  }

  const destination = $(
    '#treasuryUserTransferDestination'
  );

  if (
    destination
    && destination.dataset.userTransferEventsBound !== 'true'
  ) {
    destination.dataset.userTransferEventsBound = 'true';

    destination.addEventListener(
      'change',
      invalidateTreasuryUserTransferPreview,
    );
  }

  const currency = $('#treasuryUserTransferCurrency');

  if (
    currency
    && currency.dataset.userTransferEventsBound !== 'true'
  ) {
    currency.dataset.userTransferEventsBound = 'true';

    currency.addEventListener(
      'change',
      invalidateTreasuryUserTransferPreview,
    );
  }

  const amount = $('#treasuryUserTransferAmount');

  if (
    amount
    && amount.dataset.userTransferEventsBound !== 'true'
  ) {
    amount.dataset.userTransferEventsBound = 'true';

    amount.addEventListener(
      'input',
      invalidateTreasuryUserTransferPreview,
    );
  }

  const confirmation = $(
    '#treasuryUserTransferConfirmation'
  );

  if (
    confirmation
    && confirmation.dataset.userTransferEventsBound !== 'true'
  ) {
    confirmation.dataset.userTransferEventsBound = 'true';

    confirmation.addEventListener(
      'input',
      updateTreasuryUserTransferExecuteButton,
    );
  }

  const execute = $('#executeTreasuryUserTransfer');

  if (
    execute
    && execute.dataset.userTransferEventsBound !== 'true'
  ) {
    execute.dataset.userTransferEventsBound = 'true';

    execute.addEventListener(
      'click',
      executeTreasuryUserTransfer,
    );
  }

  const preview = $('#treasuryUserTransferPreview');

  if (
    preview
    && preview.dataset.userTransferOutcomeEventsBound
      !== 'true'
  ) {
    preview.dataset.userTransferOutcomeEventsBound = 'true';

    preview.addEventListener('click', event => {
      const target = (
        event.target instanceof Element
          ? event.target
          : null
      );

      const requestButton = target?.closest(
        '[data-user-transfer-view-request]'
      );

      if (requestButton) {
        const requestId = String(
          requestButton.dataset.userTransferViewRequest
          || ''
        );

        if (requestId) {
          openTreasuryRequestDetail(requestId);
        }

        return;
      }

      if (
        target?.closest('[data-user-transfer-new]')
      ) {
        void startNewTreasuryUserTransfer();
      }
    });
  }

}


if (document.readyState === 'loading') {
  document.addEventListener(
    'DOMContentLoaded',
    bindTreasuryUserTransferEvents,
    { once: true },
  );
} else {
  bindTreasuryUserTransferEvents();
}
