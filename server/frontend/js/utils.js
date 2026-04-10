/* AdminHelper – Shared Utilities */
'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  token: localStorage.getItem('srm_token') || null,
  user: null,
  connections: [],
  users: [],
  apikeys: [],
  hooks: [],
  servers: [],
  editingConnId: null,
  editingUserId: null,
  editingHookId: null,
  editingServerId: null,
  frpConfig: null,
  frpTunnels: [],
  editingTunnelId: null,
  connTagFilter: '',
  serverTagFilter: '',
  tunnelTagFilter: '',
  monitorChecks: [],
  editingMonitorCheckId: null,
  monitorAlertRules: [],
  editingAlertRuleId: null,
  monitorTemplates: [],
  editingTemplateId: null,
  templateCheckDefs: [],
  templateAlertDefs: [],
  monitorServerFilter: '',
  monitorTypeFilter: '',
  monitorStatusFilter: '',
  monitorTagFilter: '',
  monitorSearch: '',
};

// ── API helpers ────────────────────────────────────────────────────────────
let _refreshing = null;

async function _tryRefreshToken() {
  if (_refreshing) return _refreshing;
  const refreshToken = localStorage.getItem('srm_refresh_token');
  if (!refreshToken) return false;

  _refreshing = fetch('/api/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  }).then(async (res) => {
    if (!res.ok) return false;
    const data = await res.json();
    state.token = data.access_token;
    localStorage.setItem('srm_token', data.access_token);
    localStorage.setItem('srm_refresh_token', data.refresh_token);
    return true;
  }).catch(() => false).finally(() => { _refreshing = null; });

  return _refreshing;
}

async function api(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  if (state.token) headers['Authorization'] = `Bearer ${state.token}`;
  const jsonBody = body !== undefined ? JSON.stringify(body) : undefined;
  let res = await fetch(path, { method, headers, body: jsonBody });

  // Bei 401: Refresh versuchen und Request wiederholen
  if (res.status === 401 && !path.includes('/auth/')) {
    const refreshed = await _tryRefreshToken();
    if (refreshed) {
      headers['Authorization'] = `Bearer ${state.token}`;
      res = await fetch(path, { method, headers, body: jsonBody });
    } else {
      logout();
      throw new Error(t('session.expired'));
    }
  }

  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

const get  = (path)        => api('GET',    path);
const post = (path, body)  => api('POST',   path, body);
const put  = (path, body)  => api('PUT',    path, body);
const del  = (path)        => api('DELETE', path);

// ── Helpers ───────────────────────────────────────────────────────────────
function parseTags(value) {
  const seen = new Set();
  return value.split(',').map(t => t.trim().slice(0, 50)).filter(t => {
    if (!t || seen.has(t)) return false;
    seen.add(t);
    return true;
  });
}

// ── Toast ──────────────────────────────────────────────────────────────────
let toastTimer;
function toast(msg, type = 'success') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast show ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3000);
}

// ── Escape helper ──────────────────────────────────────────────────────────
function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;');
}

// ── Modal helpers ──────────────────────────────────────────────────────────
function showModal(id) {
  document.getElementById(id).classList.remove('hidden');
}
function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}

document.querySelectorAll('[data-close]').forEach(btn => {
  btn.addEventListener('click', () => closeModal(btn.dataset.close));
});
document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) backdrop.classList.add('hidden');
  });
});

// ── Tag Filter ─────────────────────────────────────────────────────────────
function renderTagFilter(selectId, items, stateKey) {
  const select = document.getElementById(selectId);
  if (!select) return;
  const allTags = [...new Set(items.flatMap(i => i.tags || []))].sort();
  select.classList.remove('hidden');
  const prev = state[stateKey];
  select.innerHTML = `<option value="">${t('label.allTags')}</option>` +
    allTags.map(t => `<option value="${esc(t)}"${prev === t ? ' selected' : ''}>${esc(t)}</option>`).join('');
}

// ── Router helper ──────────────────────────────────────────────────────────
function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

function setVisible(id, show) {
  document.getElementById(id).classList.toggle('hidden', !show);
}
