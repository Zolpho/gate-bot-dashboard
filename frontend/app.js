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
  botFilters: {},
  history: [],
  alertEvents: [],
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
  const signedIn = Boolean(state.adminUser && state.adminAuthorization);

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

  walletNavItem?.classList.toggle('hidden', !signedIn);
  walletNavItem?.setAttribute('aria-hidden', String(!signedIn));
  if (walletNavItem) walletNavItem.tabIndex = signedIn ? 0 : -1;

  if (signedIn) {
    $('#privateBalancePanel')?.classList.remove('hidden');
  } else {
    clearPrivateBalance();
    clearDepositHistory();
    if (state.activeTab === 'wallet') switchTab('overview');
  }

  populateFilterOptions(state.botFilters);
  renderAlerts();
  if (state.currentBotData?.bot) updateBotAdminControls(state.currentBotData.bot);
}
function lockAdmin(showMessage = true) {
  state.adminAuthorization = '';
  state.adminUser = null;
  state.currentRawData = null;
  clearPrivateBalance();
  clearDepositHistory();
  clearDepositState({ keepCatalog: false });
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

function switchTab(tab, { updateHash = true } = {}) {
  const titles = {
    overview: ['Overview', 'Native Gate.io bot performance and portfolio history'],
    bots: ['Trading bots', 'Inspect every mapped field and Gate’s dynamic response data'],
    alerts: ['Alerts', 'Local rules evaluated after each bot snapshot'],
    wallet: ['Wallet', 'Private balances, deposits and account-scoped wallet activity'],
    system: ['System', 'Connection status, collector runs and safe API inspection'],
  };

  let target = String(tab || 'overview')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, '');

  if (!titles[target] || !document.querySelector(`#tab-${target}`)) {
    target = 'overview';
  }
  if (target === 'wallet' && (!state.adminUser || !state.adminAuthorization)) {
    target = 'overview';
  }

  state.activeTab = target;
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

  if (target === 'wallet' && state.adminUser && state.adminAuthorization) {
    void Promise.all([
      loadPrivateBalance({ quiet: true }),
      loadDepositHistory({ quiet: true }),
    ]);
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
  setMetric('#currentValue', totals.current_value, fmtMoney, totals.pnl);
  setMetric('#totalPnl', totals.pnl, fmtMoney, totals.pnl);
  setMetric('#gridProfit', totals.grid_profit, fmtMoney, totals.grid_profit);
  $('#activeBotCount').textContent = `${counts.running} running · ${counts.all} tracked`;
  const day = periods['24h'] || {};
  $('#portfolioDelta').textContent = day.value_change === null || day.value_change === undefined ? `Invested ${fmtMoney(totals.invest_amount)}` : `24h ${fmtMoney(day.value_change)} (${fmtPct(day.value_change_pct)})`;
  $('#portfolioDelta').className = valueClass(day.value_change);
  $('#totalRoi').textContent = `ROI ${fmtPct(totals.roi_pct)}`;
  $('#totalRoi').className = valueClass(totals.roi_pct);
  $('#floatingPnl').textContent = `Unrealized ${fmtMoney(totals.floating_pnl)}`;
  $('#floatingPnl').className = valueClass(totals.floating_pnl);
  $('#ringTotal').textContent = counts.all;

  const total = Math.max(1, counts.all);
  const runDegrees = counts.running / total * 360;
  const pauseDegrees = runDegrees + counts.paused / total * 360;
  $('#statusRing').style.setProperty('--run', `${runDegrees}deg`);
  $('#statusRing').style.setProperty('--pause', `${pauseDegrees}deg`);
  const statuses = [
    ['Running', counts.running, 'var(--positive)'],
    ['Paused', counts.paused, 'var(--warning)'],
    ['Stopped', counts.stopped, '#53655e'],
    ['Other', counts.other, 'var(--negative)'],
  ];
  $('#statusList').innerHTML = statuses.map(([label, count, color]) => `<div class="status-row"><span><i class="dot" style="background:${color}"></i>${label}</span><b>${count}</b></div>`).join('');

  const leaders = [...state.bots].filter(b => b.status === 'running').sort((a,b) => (b.profit_rate ?? b.pnl_rate ?? -Infinity) - (a.profit_rate ?? a.pnl_rate ?? -Infinity)).slice(0,4);
  $('#leaderCards').innerHTML = leaders.length ? leaders.map(bot => `<button class="leader row-button" data-bot-id="${bot.id}"><span><b>${escapeHtml(bot.strategy_name)}</b><small>${escapeHtml(bot.account_name)} · ${escapeHtml(bot.market)} · ${strategyLabel(bot.strategy_type)}</small></span><strong class="${valueClass(bot.profit_rate ?? bot.pnl_rate)}">${fmtRatioPct(bot.profit_rate ?? bot.pnl_rate)}<small>${fmtMoney(bot.total_profit ?? bot.pnl)}</small></strong></button>`).join('') : '<div class="empty-state">No running bots yet.</div>';

  const accountLabel = state.selectedAccount ? (state.overview.selected_account?.name || state.selectedAccount) : 'All accounts';
  $('#lastSyncSidebar').textContent = latest ? `${accountLabel} · ${fmtDate(latest.finished_at || latest.started_at)}` : `${accountLabel} · no sync yet`;
  renderOverviewAlerts();
  drawPortfolioChart();
}

function drawSeriesChart(canvas, points, series) {
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);
  const ctx = canvas.getContext('2d');
  ctx.scale(ratio, ratio);
  const width = rect.width;
  const height = rect.height;
  const pad = { left: 52, right: 18, top: 14, bottom: 27 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const css = getComputedStyle(document.documentElement);
  const muted = css.getPropertyValue('--muted').trim();
  const border = css.getPropertyValue('--border').trim();
  const surface = css.getPropertyValue('--surface').trim();
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = surface;
  ctx.fillRect(0, 0, width, height);
  if (!points.length) return;

  ctx.strokeStyle = border;
  ctx.lineWidth = 1;
  ctx.fillStyle = muted;
  ctx.font = '11px system-ui';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + plotH * i / 4;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
  }

  const timestamps = points.map(p => new Date(p.captured_at).valueOf());
  const xMin = Math.min(...timestamps), xMax = Math.max(...timestamps);
  const x = ts => pad.left + ((ts - xMin) / Math.max(1, xMax - xMin)) * plotW;

  series.forEach((s, index) => {
    const values = points.map(p => Number(p[s.key])).filter(Number.isFinite);
    if (!values.length) return;
    let min = Math.min(...values), max = Math.max(...values);
    if (min === max) { min -= 1; max += 1; }
    const margin = (max - min) * .12;
    min -= margin; max += margin;
    const y = value => pad.top + (1 - (value - min) / (max - min)) * plotH;
    ctx.beginPath();
    let started = false;
    points.forEach((point, i) => {
      const value = Number(point[s.key]);
      if (!Number.isFinite(value)) return;
      const px = x(timestamps[i]), py = y(value);
      if (!started) { ctx.moveTo(px, py); started = true; } else ctx.lineTo(px, py);
    });
    ctx.strokeStyle = s.color;
    ctx.lineWidth = index === 0 ? 2.2 : 1.6;
    ctx.stroke();
    if (s.fill && started) {
      const lastX = x(timestamps[timestamps.length - 1]);
      ctx.lineTo(lastX, pad.top + plotH); ctx.lineTo(x(timestamps[0]), pad.top + plotH); ctx.closePath();
      const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
      gradient.addColorStop(0, s.fill); gradient.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = gradient; ctx.fill();
    }
  });

  ctx.fillStyle = muted;
  ctx.textAlign = 'left';
  const first = new Date(xMin), last = new Date(xMax);
  ctx.fillText(first.toLocaleDateString(), pad.left, height - 7);
  ctx.textAlign = 'right';
  ctx.fillText(last.toLocaleDateString(), width - pad.right, height - 7);
}

function drawPortfolioChart() {
  const empty = $('#chartEmpty');
  empty.classList.toggle('hidden', state.history.length > 1);
  const css = getComputedStyle(document.documentElement);
  drawSeriesChart($('#portfolioChart'), state.history, [
    { key: 'current_value', color: css.getPropertyValue('--accent').trim(), fill: 'rgba(23,211,154,.16)' },
    { key: 'pnl', color: css.getPropertyValue('--blue').trim() },
  ]);
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
  const manageableBots = state.bots.filter(bot => canManageAccount(bot.account_id));
  const globalOption = state.adminUser?.role === 'super_admin'
    ? '<option value="">All bots (super admin)</option>'
    : '<option value="" disabled>Select one of your bots</option>';
  botSelect.innerHTML = globalOption + manageableBots.map(bot => `<option value="${bot.id}">[${escapeHtml(bot.account_name)}] ${escapeHtml(bot.strategy_name)} (${escapeHtml(bot.market)})</option>`).join('');
  if (state.adminUser?.role !== 'super_admin' && manageableBots.length) botSelect.value = String(manageableBots[0].id);
}

function applyBotFilters() {
  const term = $('#botSearch').value.trim().toLowerCase();
  const status = $('#statusFilter').value;
  const type = $('#typeFilter').value;
  const market = $('#marketFilter').value;
  const sort = $('#sortFilter').value;
  const valueFor = (bot) => ({ pnl: bot.total_profit ?? bot.pnl ?? -Infinity, roi: bot.profit_rate ?? bot.pnl_rate ?? -Infinity, updated: new Date(bot.updated_at).valueOf(), name: bot.strategy_name, market: bot.market }[sort]);
  state.filteredBots = state.bots.filter(bot => (!term || `${bot.account_name} ${bot.account_id} ${bot.strategy_name} ${bot.market} ${bot.strategy_id}`.toLowerCase().includes(term)) && (!status || bot.status === status) && (!type || bot.strategy_type === type) && (!market || bot.market === market)).sort((a,b) => typeof valueFor(a) === 'string' ? String(valueFor(a)).localeCompare(String(valueFor(b))) : Number(valueFor(b)) - Number(valueFor(a)));
  renderBots();
}

function renderBots() {
  const tbody = $('#botsTableBody');

  tbody.innerHTML = state.filteredBots.map(bot => {
    const totalPnl = bot.total_profit ?? bot.pnl;
    const rate = bot.profit_rate ?? bot.pnl_rate;

    const realizedPnl = (
      bot.realized_pnl
      ?? bot.grid_profit
    );

    const totalNumber = numericValue(totalPnl);
    const realizedNumber = numericValue(realizedPnl);

    const unrealizedPnl = hasValue(bot.floating_pnl)
      ? bot.floating_pnl
      : (
        totalNumber !== null
        && realizedNumber !== null
          ? totalNumber - realizedNumber
          : null
      );

    const apr = annualizedAprPct(
      rate,
      bot.runtime_seconds,
    );

    return `<tr>
      <td class="strategy-cell">
        <strong>${escapeHtml(bot.strategy_name)}</strong>
        <small>
          ${escapeHtml(bot.market)}
          · ${strategyLabel(bot.strategy_type)}
        </small>
      </td>
      <td>
        <span class="account-badge">
          ${escapeHtml(bot.account_name)}
        </span>
      </td>
      <td>
        <span class="status-badge ${escapeHtml(bot.status)}">
          ${escapeHtml(bot.status)}
        </span>
      </td>
      <td>${fmtMoney(bot.invest_amount)}</td>
      <td>${fmtMoney(bot.current_value)}</td>
      <td class="${valueClass(totalPnl)}">
        ${fmtMoney(totalPnl)}
      </td>
      <td class="${valueClass(realizedPnl)}">
        ${fmtMoney(realizedPnl)}
      </td>
      <td class="${valueClass(unrealizedPnl)}">
        ${fmtMoney(unrealizedPnl)}
      </td>
      <td class="${valueClass(rate)}">
        ${fmtRatioPct(rate)}
      </td>
      <td class="${valueClass(apr)}">
        ${fmtPct(apr)}
      </td>
      <td>${fmtNumber(bot.arbitrage_count, 0)}</td>
      <td>${fmtDuration(bot.runtime_seconds)}</td>
      <td>
        <button
          class="row-button"
          data-bot-id="${bot.id}"
        >Details →</button>
      </td>
    </tr>`;
  }).join('');

  $('#botsEmpty').classList.toggle(
    'hidden',
    state.filteredBots.length > 0,
  );
}

function renderOverviewAlerts() {
  const target = $('#overviewAlerts');
  const items = state.alertEvents.slice(0,4);
  target.innerHTML = items.length ? items.map(eventHtml).join('') : '<div class="empty-state">No alert events.</div>';
}

function eventHtml(event) {
  let action = '<span class="status-badge">Open</span>';
  if (event.acknowledged_at) action = '<span class="status-badge">Ack</span>';
  else if ((event.account_id && canManageAccount(event.account_id)) || (!event.account_id && state.adminUser?.role === 'super_admin')) {
    action = `<button class="text-button ack-event" data-event-id="${event.id}">Acknowledge</button>`;
  }
  return `<article class="event"><i class="event-dot"></i><div><p>${escapeHtml(event.message)}</p><small>${fmtDate(event.triggered_at)}</small></div>${action}</article>`;
}

function renderAlerts() {
  $('#rulesList').innerHTML = state.rules.length ? state.rules.map(rule => {
    const scope = rule.account_name || 'All accounts';
    const controls = canManageRule(rule)
      ? `<div class="button-row"><label class="switch" title="Enable rule"><input class="rule-toggle" type="checkbox" data-rule-id="${rule.id}" ${rule.enabled ? 'checked' : ''}><span></span></label><button class="text-button delete-rule" data-rule-id="${rule.id}">Delete</button></div>`
      : `<span class="status-badge">${rule.enabled ? 'Active' : 'Disabled'}</span>`;
    return `<article class="rule"><div><p><strong>${escapeHtml(rule.name)}</strong></p><small>${escapeHtml(scope)} · ${escapeHtml(rule.metric)} ${escapeHtml(rule.operator)} ${fmtNumber(rule.threshold,4)} · cooldown ${fmtDuration(rule.cooldown_seconds)}</small></div>${controls}</article>`;
  }).join('') : '<div class="empty-state">No rules configured.</div>';
  $('#alertEvents').innerHTML = state.alertEvents.length ? state.alertEvents.map(eventHtml).join('') : '<div class="empty-state">No alert events.</div>';
  $('#addRuleButton').disabled = !state.adminUser;
  $('#addRuleButton').title = state.adminUser ? 'Create a rule for an authorized bot' : 'Unlock account actions first';
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
    const [health, overviewData, botData, historyData, ruleData, eventData, syncData] = await Promise.all([
      api('/api/health'),
      api(scopedPath('/api/overview')),
      api(scopedPath('/api/bots')),
      api(scopedPath('/api/portfolio/history', { hours })),
      api('/api/alerts/rules'),
      api(scopedPath('/api/alerts/events', { unacknowledged_only: $('#unackedOnly').checked })),
      api(scopedPath('/api/sync-runs', { limit: 20 })),
    ]);
    state.health = health; state.overview = overviewData; state.bots = botData.items; state.botFilters = botData.filters || {}; state.history = historyData.items; state.rules = ruleData.items; state.alertEvents = eventData.items; state.syncRuns = syncData.items;
    populateAccountSelector(overviewData.accounts || []);
    populateFilterOptions(botData.filters);
    applyBotFilters(); renderOverview(); renderAlerts(); renderSystem();
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
      'Trades / cycles',
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
      bot.status,
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
  const ownsBot = canManageAccount(bot.account_id);
  const stopEnabled = Boolean(state.health?.allow_bot_stop && bot.stop_supported && ownsBot);
  $('#stopBotButton').disabled = !stopEnabled;
  if (!state.adminUser) $('#dangerZone p').textContent = 'Unlock the matching account before using disruptive actions.';
  else if (!ownsBot) $('#dangerZone p').textContent = `Signed in as ${state.adminUser.username}; this bot belongs to ${bot.account_name}.`;
  else if (!state.health?.allow_bot_stop) $('#dangerZone p').textContent = 'Stopping is disabled by ALLOW_BOT_STOP on the server.';
  else if (!bot.stop_supported) $('#dangerZone p').textContent = 'Gate reports stop is unavailable for this strategy.';
  else $('#dangerZone p').textContent = 'This sends Gate’s native stop request after typed confirmation.';
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
  const confirmation = prompt(`Type STOP to stop ${bot.strategy_name}. Gate may close/cancel strategy orders according to its bot rules.`);
  if (confirmation !== 'STOP') { showToast('Stop cancelled: confirmation did not match.'); return; }
  try {
    if (!canManageAccount(bot.account_id)) { openAdminDialog(); return; }
    const result = await adminApi(`/api/bots/${bot.id}/stop`, { method: 'POST', body: JSON.stringify({ confirmation }) });
    showToast('Stop request submitted to Gate.');
    $('#apiInspector').textContent = JSON.stringify(result, null, 2);
    switchTab('system'); $('#botDialog').close();
  } catch (error) { showToast(error.message, true); }
}

function exportCsv() {
  const headers = ['account_id','account_name','strategy_id','strategy_name','strategy_type','market','status','invest_amount','current_value','total_profit','profit_rate','realized_pnl','grid_profit','floating_pnl','arbitrage_count','runtime_seconds','last_seen_at'];
  const quote = value => `"${String(value ?? '').replaceAll('"','""')}"`;
  const rows = [headers.join(','), ...state.filteredBots.map(bot => headers.map(key => quote(bot[key])).join(','))];
  const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `gate-bots-${new Date().toISOString().slice(0,10)}.csv`; a.click(); URL.revokeObjectURL(url);
}

async function acknowledgeEvent(id) {
  if (!state.adminUser) { openAdminDialog(); return; }
  try { await adminApi(`/api/alerts/events/${id}/acknowledge`, { method:'POST' }); await loadCore(); showToast('Alert acknowledged.'); }
  catch (error) { showToast(error.message, true); }
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
  $('#refreshButton').addEventListener('click', loadCore); $('#syncButton').addEventListener('click', syncNow);
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
    const botButton = event.target.closest('[data-bot-id]'); if (botButton) openBot(Number(botButton.dataset.botId));
    const ack = event.target.closest('.ack-event'); if (ack) acknowledgeEvent(Number(ack.dataset.eventId));
    const del = event.target.closest('.delete-rule'); if (del) deleteRule(Number(del.dataset.ruleId));
    const depositCurrency = event.target.closest('[data-deposit-currency]'); if (depositCurrency) selectDepositCurrency(depositCurrency.dataset.depositCurrency);
    const depositChain = event.target.closest('[data-deposit-chain]'); if (depositChain) selectDepositNetwork(depositChain.dataset.depositChain);
    const depositCopy = event.target.closest('[data-copy-deposit]'); if (depositCopy) copyDepositValue(depositCopy.dataset.copyDeposit);
  });
  document.addEventListener('change', event => { if (event.target.matches('.rule-toggle')) toggleRule(Number(event.target.dataset.ruleId), event.target.checked); });
  $('#unackedOnly').addEventListener('change', loadCore);
  $('#closeDialog').addEventListener('click', () => $('#botDialog').close());
  $('#botDialog').addEventListener('click', event => { if (event.target === $('#botDialog')) $('#botDialog').close(); });
  $('#botHistoryRange').addEventListener('change', () => state.currentBot && openBot(state.currentBot));
  $$('.raw-tab').forEach(button => button.addEventListener('click', async () => { state.currentRawKey = button.dataset.raw; $$('.raw-tab').forEach(t => t.classList.toggle('active', t === button)); if (!state.currentRawData && state.currentBotData?.bot && canManageAccount(state.currentBotData.bot.account_id)) await loadCurrentBotRaw(); else renderBotRaw(); }));
  $('#stopBotButton').addEventListener('click', stopCurrentBot);
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

bindEvents();
renderAdminState();
switchTab(window.location.hash.slice(1) || 'overview', { updateHash: false });
loadCore();
setInterval(loadCore, 60000);
