'use strict';

const state = {
  overview: null,
  bots: [],
  filteredBots: [],
  history: [],
  alertEvents: [],
  rules: [],
  health: null,
  syncRuns: [],
  currentBot: null,
  currentBotData: null,
  currentBotHistory: [],
  currentRawKey: 'metrics',
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let payload;
  try { payload = text ? JSON.parse(text) : {}; } catch { payload = { detail: text }; }
  if (!response.ok) throw new Error(payload.detail || payload.error || `Request failed (${response.status})`);
  return payload;
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

function fmtNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(Number(value));
}

function fmtPct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  const n = Number(value);
  return `${n > 0 ? '+' : ''}${fmtNumber(n, digits)}%`;
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

function switchTab(tab) {
  $$('.nav-item').forEach(button => button.classList.toggle('active', button.dataset.tab === tab));
  $$('.tab-panel').forEach(panel => panel.classList.toggle('active', panel.id === `tab-${tab}`));
  const titles = {
    overview: ['Overview', 'Native Gate.io bot performance and portfolio history'],
    bots: ['Trading bots', 'Inspect every mapped field and Gate’s dynamic response data'],
    alerts: ['Alerts', 'Local rules evaluated after each bot snapshot'],
    system: ['System', 'Connection status, collector runs and safe API inspection'],
  };
  $('#pageTitle').textContent = titles[tab][0];
  $('#pageSubtitle').textContent = titles[tab][1];
}

function setMetric(selector, value, formatter = fmtMoney, classValue = value) {
  const el = $(selector);
  el.textContent = formatter(value);
  el.classList.remove('positive', 'negative');
  if (classValue !== null && classValue !== undefined) el.classList.add(valueClass(classValue));
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
  $('#floatingPnl').textContent = `Floating ${fmtMoney(totals.floating_pnl)}`;
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
  $('#leaderCards').innerHTML = leaders.length ? leaders.map(bot => `<button class="leader row-button" data-bot-id="${bot.id}"><span><b>${escapeHtml(bot.strategy_name)}</b><small>${escapeHtml(bot.market)} · ${strategyLabel(bot.strategy_type)}</small></span><strong class="${valueClass(bot.profit_rate ?? bot.pnl_rate)}">${fmtPct(bot.profit_rate ?? bot.pnl_rate)}<small>${fmtMoney(bot.total_profit ?? bot.pnl)}</small></strong></button>`).join('') : '<div class="empty-state">No running bots yet.</div>';

  $('#lastSyncSidebar').textContent = latest ? `Last sync ${fmtDate(latest.finished_at || latest.started_at)}` : 'No sync yet';
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

function populateFilterOptions(filters = {}) {
  const type = $('#typeFilter'), market = $('#marketFilter');
  const currentType = type.value, currentMarket = market.value;
  type.innerHTML = '<option value="">All types</option>' + (filters.strategy_types || []).map(v => `<option value="${escapeHtml(v)}">${strategyLabel(v)}</option>`).join('');
  market.innerHTML = '<option value="">All markets</option>' + (filters.markets || []).map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
  type.value = currentType; market.value = currentMarket;
  const botSelect = $('#ruleForm select[name="bot_id"]');
  botSelect.innerHTML = '<option value="">All bots</option>' + state.bots.map(bot => `<option value="${bot.id}">${escapeHtml(bot.strategy_name)} (${escapeHtml(bot.market)})</option>`).join('');
}

function applyBotFilters() {
  const term = $('#botSearch').value.trim().toLowerCase();
  const status = $('#statusFilter').value;
  const type = $('#typeFilter').value;
  const market = $('#marketFilter').value;
  const sort = $('#sortFilter').value;
  const valueFor = (bot) => ({ pnl: bot.total_profit ?? bot.pnl ?? -Infinity, roi: bot.profit_rate ?? bot.pnl_rate ?? -Infinity, updated: new Date(bot.updated_at).valueOf(), name: bot.strategy_name, market: bot.market }[sort]);
  state.filteredBots = state.bots.filter(bot => (!term || `${bot.strategy_name} ${bot.market} ${bot.strategy_id}`.toLowerCase().includes(term)) && (!status || bot.status === status) && (!type || bot.strategy_type === type) && (!market || bot.market === market)).sort((a,b) => typeof valueFor(a) === 'string' ? String(valueFor(a)).localeCompare(String(valueFor(b))) : Number(valueFor(b)) - Number(valueFor(a)));
  renderBots();
}

function renderBots() {
  const tbody = $('#botsTableBody');
  tbody.innerHTML = state.filteredBots.map(bot => {
    const pnl = bot.total_profit ?? bot.pnl;
    const roi = bot.profit_rate ?? bot.pnl_rate;
    return `<tr>
      <td class="strategy-cell"><strong>${escapeHtml(bot.strategy_name)}</strong><small>${escapeHtml(bot.market)} · ${strategyLabel(bot.strategy_type)}</small></td>
      <td><span class="status-badge ${escapeHtml(bot.status)}">${escapeHtml(bot.status)}</span></td>
      <td>${fmtMoney(bot.invest_amount)}</td><td>${fmtMoney(bot.current_value)}</td>
      <td class="${valueClass(pnl)}">${fmtMoney(pnl)}</td><td class="${valueClass(roi)}">${fmtPct(roi)}</td>
      <td class="${valueClass(bot.grid_profit)}">${fmtMoney(bot.grid_profit)}</td><td>${fmtDuration(bot.runtime_seconds)}</td>
      <td><button class="row-button" data-bot-id="${bot.id}">Details →</button></td></tr>`;
  }).join('');
  $('#botsEmpty').classList.toggle('hidden', state.filteredBots.length > 0);
}

function renderOverviewAlerts() {
  const target = $('#overviewAlerts');
  const items = state.alertEvents.slice(0,4);
  target.innerHTML = items.length ? items.map(eventHtml).join('') : '<div class="empty-state">No alert events.</div>';
}

function eventHtml(event) {
  return `<article class="event"><i class="event-dot"></i><div><p>${escapeHtml(event.message)}</p><small>${fmtDate(event.triggered_at)}</small></div>${event.acknowledged_at ? '<span class="status-badge">Ack</span>' : `<button class="text-button ack-event" data-event-id="${event.id}">Acknowledge</button>`}</article>`;
}

function renderAlerts() {
  $('#rulesList').innerHTML = state.rules.length ? state.rules.map(rule => `<article class="rule"><div><p><strong>${escapeHtml(rule.name)}</strong></p><small>${escapeHtml(rule.metric)} ${escapeHtml(rule.operator)} ${fmtNumber(rule.threshold,4)} · cooldown ${fmtDuration(rule.cooldown_seconds)}</small></div><div class="button-row"><label class="switch" title="Enable rule"><input class="rule-toggle" type="checkbox" data-rule-id="${rule.id}" ${rule.enabled ? 'checked' : ''}><span></span></label><button class="text-button delete-rule" data-rule-id="${rule.id}">Delete</button></div></article>`).join('') : '<div class="empty-state">No rules configured.</div>';
  $('#alertEvents').innerHTML = state.alertEvents.length ? state.alertEvents.map(eventHtml).join('') : '<div class="empty-state">No alert events.</div>';
}

function renderSystem() {
  if (!state.health) return;
  const health = state.health;
  $('#modeBadge').textContent = health.mode.toUpperCase();
  $('#modeBadge').className = `mode-badge ${health.mode}`;
  $('#connectionDot').className = health.status === 'ok' ? 'online' : 'offline';
  $('#connectionText').textContent = health.mode === 'demo' ? 'Demo data' : health.gate_configured ? 'Gate configured' : 'Credentials missing';
  const details = [
    ['Application', health.status], ['Mode', health.mode], ['Gate credentials', health.gate_configured ? 'Configured' : 'Not configured'],
    ['Collector', health.collector_running ? 'Synchronising' : 'Idle'], ['Poll interval', `${health.poll_seconds}s`],
    ['History retention', `${health.snapshot_retention_days} days`], ['Stop action', health.allow_bot_stop ? 'Enabled' : 'Disabled'],
  ];
  $('#healthDetails').innerHTML = details.map(([k,v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`).join('');
  $('#syncRuns').innerHTML = state.syncRuns.length ? state.syncRuns.map(run => `<article class="sync-run"><i class="sync-dot ${run.status === 'error' ? 'error' : ''}"></i><div><strong>${escapeHtml(run.status)}</strong><small>${fmtDate(run.started_at)} · ${run.bot_count} bots / ${run.detail_count} details${run.error ? ` · ${escapeHtml(run.error)}` : ''}</small></div><span class="type-badge">${escapeHtml(run.summary?.trigger || '—')}</span></article>`).join('') : '<div class="empty-state">No collection runs yet.</div>';
}

async function loadCore() {
  try {
    const hours = Number($('#historyRange').value);
    const [health, overviewData, botData, historyData, ruleData, eventData, syncData] = await Promise.all([
      api('/api/health'), api('/api/overview'), api('/api/bots'), api(`/api/portfolio/history?hours=${hours}`), api('/api/alerts/rules'), api(`/api/alerts/events?unacknowledged_only=${$('#unackedOnly').checked}`), api('/api/sync-runs?limit=20'),
    ]);
    state.health = health; state.overview = overviewData; state.bots = botData.items; state.history = historyData.items; state.rules = ruleData.items; state.alertEvents = eventData.items; state.syncRuns = syncData.items;
    populateFilterOptions(botData.filters);
    applyBotFilters(); renderOverview(); renderAlerts(); renderSystem();
  } catch (error) {
    $('#connectionDot').className = 'offline'; $('#connectionText').textContent = 'API unavailable';
    showToast(error.message, true);
  }
}

async function syncNow() {
  const button = $('#syncButton');
  button.disabled = true; button.textContent = 'Syncing…';
  try {
    const result = await api('/api/sync', { method: 'POST' });
    if (result.status === 'error') throw new Error(result.error || 'Sync failed');
    showToast(result.status === 'skipped' ? 'A sync is already running.' : `Sync complete: ${result.bot_count ?? 0} bots`);
    await loadCore();
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; button.textContent = 'Sync Gate'; }
}

async function openBot(botId) {
  try {
    const hours = Number($('#botHistoryRange').value);
    const [detail, history] = await Promise.all([api(`/api/bots/${botId}`), api(`/api/bots/${botId}/history?hours=${hours}`)]);
    state.currentBot = botId; state.currentBotData = detail; state.currentBotHistory = history.items;
    renderBotDialog(detail, history);
    if (!$('#botDialog').open) $('#botDialog').showModal();
  } catch (error) { showToast(error.message, true); }
}

function renderBotDialog(detail, history) {
  const bot = detail.bot;
  $('#dialogTitle').textContent = bot.strategy_name;
  $('#dialogSubtitle').textContent = `${bot.market} · ${strategyLabel(bot.strategy_type)} · ${bot.strategy_id}`;
  const stats = [
    ['Invested', fmtMoney(bot.invest_amount), null], ['Current value', fmtMoney(bot.current_value), bot.total_profit],
    ['Total PnL', fmtMoney(bot.total_profit ?? bot.pnl), bot.total_profit ?? bot.pnl], ['ROI', fmtPct(bot.profit_rate ?? bot.pnl_rate), bot.profit_rate ?? bot.pnl_rate],
    ['Grid profit', fmtMoney(bot.grid_profit), bot.grid_profit], ['Floating PnL', fmtMoney(bot.floating_pnl), bot.floating_pnl],
    ['Arbitrages', fmtNumber(bot.arbitrage_count,0), null], ['Runtime', fmtDuration(bot.runtime_seconds), null],
    ['Max drawdown', fmtPct(history.analytics?.max_drawdown_pct), -(history.analytics?.max_drawdown_pct || 0)], ['Status', bot.status, null],
  ];
  $('#botDetailMetrics').innerHTML = stats.map(([label,value,cls]) => `<div class="detail-stat"><span>${label}</span><strong class="${cls === null ? '' : valueClass(cls)}">${escapeHtml(value)}</strong></div>`).join('');
  $('#drawdownSummary').textContent = `Max ${fmtPct(history.analytics?.max_drawdown_pct)} · Current ${fmtPct(history.analytics?.current_drawdown_pct)} · Peak ${fmtMoney(history.analytics?.peak_value)}`;
  const definitions = [
    ['Strategy ID', bot.strategy_id], ['Type', strategyLabel(bot.strategy_type)], ['Gate status', bot.source_status], ['Created', fmtDate(bot.created_at_gate)], ['Last seen', fmtDate(bot.last_seen_at)],
    ['Price range', bot.price_range || '—'], ['Grid count', fmtNumber(bot.grid_count,0)], ['Finished rounds', fmtNumber(bot.finished_rounds,0)], ['Position side', bot.position_side || '—'],
    ['Position amount', fmtNumber(bot.position_amount,8)], ['Entry price', fmtMoney(bot.entry_price)], ['Position value', fmtMoney(bot.position_value)], ['Margin', fmtMoney(bot.margin)],
    ['Liquidation price', fmtMoney(bot.estimated_liquidation_price)], ['Maintenance margin', fmtPct(bot.maintenance_margin_ratio)], ['Stop supported', bot.stop_supported ? 'Yes' : 'No'],
  ];
  $('#botDefinitionList').innerHTML = definitions.map(([k,v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`).join('');
  state.currentRawKey = 'metrics';
  $$('.raw-tab').forEach(t => t.classList.toggle('active', t.dataset.raw === 'metrics'));
  renderBotRaw();
  $('#stopBotButton').disabled = !(state.health?.allow_bot_stop && bot.stop_supported);
  $('#dangerZone p').textContent = state.health?.allow_bot_stop ? (bot.stop_supported ? 'This sends Gate’s native stop request after typed confirmation.' : 'Gate reports stop is unavailable for this strategy.') : 'Disabled by default. Set ALLOW_BOT_STOP=true on the server to enable it.';
  drawBotChart();
}

function renderBotRaw() {
  const bot = state.currentBotData?.bot;
  if (!bot) return;
  $('#botRaw').textContent = JSON.stringify(bot[state.currentRawKey] ?? {}, null, 2);
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
    const result = await api(`/api/bots/${bot.id}/stop`, { method: 'POST', body: JSON.stringify({ confirmation }) });
    showToast('Stop request submitted to Gate.');
    $('#apiInspector').textContent = JSON.stringify(result, null, 2);
    switchTab('system'); $('#botDialog').close();
  } catch (error) { showToast(error.message, true); }
}

function exportCsv() {
  const headers = ['strategy_id','strategy_name','strategy_type','market','status','invest_amount','current_value','total_profit','profit_rate','grid_profit','floating_pnl','runtime_seconds','last_seen_at'];
  const quote = value => `"${String(value ?? '').replaceAll('"','""')}"`;
  const rows = [headers.join(','), ...state.filteredBots.map(bot => headers.map(key => quote(bot[key])).join(','))];
  const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `gate-bots-${new Date().toISOString().slice(0,10)}.csv`; a.click(); URL.revokeObjectURL(url);
}

async function acknowledgeEvent(id) {
  try { await api(`/api/alerts/events/${id}/acknowledge`, { method:'POST' }); await loadCore(); showToast('Alert acknowledged.'); }
  catch (error) { showToast(error.message, true); }
}

async function toggleRule(id, enabled) {
  try { await api(`/api/alerts/rules/${id}`, { method:'PATCH', body:JSON.stringify({ enabled }) }); showToast(`Rule ${enabled ? 'enabled' : 'disabled'}.`); }
  catch (error) { showToast(error.message, true); await loadCore(); }
}

async function deleteRule(id) {
  if (!confirm('Delete this alert rule?')) return;
  try { await api(`/api/alerts/rules/${id}`, { method:'DELETE' }); await loadCore(); showToast('Rule deleted.'); }
  catch (error) { showToast(error.message, true); }
}

async function createRule(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = Object.fromEntries(form.entries());
  payload.threshold = Number(payload.threshold); payload.cooldown_seconds = Number(payload.cooldown_seconds); payload.bot_id = payload.bot_id ? Number(payload.bot_id) : null;
  try { await api('/api/alerts/rules', { method:'POST', body:JSON.stringify(payload) }); $('#ruleDialog').close(); event.currentTarget.reset(); await loadCore(); showToast('Alert rule created.'); }
  catch (error) { showToast(error.message, true); }
}

async function inspectEndpoint(endpoint) {
  const inspector = $('#apiInspector'); inspector.textContent = 'Loading…';
  try { inspector.textContent = JSON.stringify(await api(endpoint), null, 2); }
  catch (error) { inspector.textContent = error.message; showToast(error.message, true); }
}

function bindEvents() {
  $$('.nav-item').forEach(button => button.addEventListener('click', () => switchTab(button.dataset.tab)));
  $$('[data-jump]').forEach(button => button.addEventListener('click', () => switchTab(button.dataset.jump)));
  $('#refreshButton').addEventListener('click', loadCore); $('#syncButton').addEventListener('click', syncNow);
  $('#historyRange').addEventListener('change', loadCore);
  ['#botSearch','#statusFilter','#typeFilter','#marketFilter','#sortFilter'].forEach(selector => $(selector).addEventListener(selector === '#botSearch' ? 'input' : 'change', applyBotFilters));
  $('#exportCsv').addEventListener('click', exportCsv);
  document.addEventListener('click', event => {
    const botButton = event.target.closest('[data-bot-id]'); if (botButton) openBot(Number(botButton.dataset.botId));
    const ack = event.target.closest('.ack-event'); if (ack) acknowledgeEvent(Number(ack.dataset.eventId));
    const del = event.target.closest('.delete-rule'); if (del) deleteRule(Number(del.dataset.ruleId));
  });
  document.addEventListener('change', event => { if (event.target.matches('.rule-toggle')) toggleRule(Number(event.target.dataset.ruleId), event.target.checked); });
  $('#unackedOnly').addEventListener('change', loadCore);
  $('#closeDialog').addEventListener('click', () => $('#botDialog').close());
  $('#botDialog').addEventListener('click', event => { if (event.target === $('#botDialog')) $('#botDialog').close(); });
  $('#botHistoryRange').addEventListener('change', () => state.currentBot && openBot(state.currentBot));
  $$('.raw-tab').forEach(button => button.addEventListener('click', () => { state.currentRawKey = button.dataset.raw; $$('.raw-tab').forEach(t => t.classList.toggle('active', t === button)); renderBotRaw(); }));
  $('#stopBotButton').addEventListener('click', stopCurrentBot);
  $('#addRuleButton').addEventListener('click', () => $('#ruleDialog').showModal());
  $('#closeRuleDialog').addEventListener('click', () => $('#ruleDialog').close()); $('#cancelRule').addEventListener('click', () => $('#ruleDialog').close());
  $('#ruleForm').addEventListener('submit', createRule);
  $('#testAccountButton').addEventListener('click', () => inspectEndpoint('/api/account'));
  $('#loadRecommendations').addEventListener('click', () => inspectEndpoint('/api/recommendations?limit=10'));
  $('#clearInspector').addEventListener('click', () => { $('#apiInspector').textContent = 'Select an action above to inspect a response.'; });
  window.addEventListener('resize', () => { drawPortfolioChart(); if ($('#botDialog').open) drawBotChart(); });
}

bindEvents();
loadCore();
setInterval(loadCore, 60000);
