/* Simple Remote Manager – Server Web UI */
'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  token: localStorage.getItem('srm_token') || null,
  user: null,
  connections: [],
  users: [],
  apikeys: [],
  hooks: [],
  editingConnId: null,
  editingUserId: null,
  editingHookId: null,
};

// ── API helpers ────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  if (state.token) headers['Authorization'] = `Bearer ${state.token}`;
  const res = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

const get  = (path)        => api('GET',    path);
const post = (path, body)  => api('POST',   path, body);
const put  = (path, body)  => api('PUT',    path, body);
const del  = (path)        => api('DELETE', path);

// ── Toast ──────────────────────────────────────────────────────────────────
let toastTimer;
function toast(msg, type = 'success') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast show ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3000);
}

// ── Router ─────────────────────────────────────────────────────────────────
function navigate(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const pageEl = document.getElementById(`page${cap(page)}`);
  if (pageEl) pageEl.classList.add('active');
  document.querySelectorAll(`.nav-item[data-page="${page}"]`).forEach(n => n.classList.add('active'));
  location.hash = `/${page}`;
  if (page === 'connections') loadConnections();
  if (page === 'users')       loadUsers();
  if (page === 'apikeys')     loadApiKeys();
  if (page === 'hooks')       loadHooks();
}

function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

// ── Login ──────────────────────────────────────────────────────────────────
document.getElementById('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const errEl = document.getElementById('loginError');
  errEl.classList.remove('show');
  try {
    const data = await post('/api/auth/login', {
      username: document.getElementById('loginUser').value,
      password: document.getElementById('loginPass').value,
    });
    state.token = data.access_token;
    localStorage.setItem('srm_token', state.token);
    await initApp();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.add('show');
  }
});

// ── Init ───────────────────────────────────────────────────────────────────
async function initApp() {
  try {
    state.user = await get('/api/auth/me');
  } catch {
    logout();
    return;
  }

  document.getElementById('loginPage').classList.add('hidden');
  document.getElementById('appLayout').classList.remove('hidden');

  document.getElementById('userName').textContent = state.user.username;
  document.getElementById('userRole').textContent = state.user.is_admin ? 'Admin' : 'Benutzer';
  document.getElementById('userAvatar').textContent = state.user.username.charAt(0).toUpperCase();

  if (state.user.is_admin) {
    document.getElementById('adminNav').classList.remove('hidden');
    document.getElementById('addConnBtn').classList.remove('hidden');
    document.getElementById('exportConnBtn').classList.remove('hidden');
    document.getElementById('importConnBtn').classList.remove('hidden');
    document.getElementById('connActionsHeader').textContent = 'Aktionen';
  }

  const hash = location.hash.replace('#/', '') || 'connections';
  navigate(hash);
}

// ── Logout ─────────────────────────────────────────────────────────────────
document.getElementById('logoutBtn').addEventListener('click', logout);
function logout() {
  state.token = null;
  localStorage.removeItem('srm_token');
  location.reload();
}

// ── Nav ────────────────────────────────────────────────────────────────────
document.querySelectorAll('.nav-item[data-page]').forEach(btn => {
  btn.addEventListener('click', () => navigate(btn.dataset.page));
});

// ── Connections ────────────────────────────────────────────────────────────
async function loadConnections() {
  try {
    state.connections = await get('/api/connections');
    renderConnections();
  } catch (err) {
    toast(err.message, 'error');
  }
}

const connSearch = document.getElementById('connSearch');
connSearch.addEventListener('input', renderConnections);

function renderConnections() {
  const q = connSearch.value.toLowerCase();
  const filtered = state.connections.filter(c =>
    !q ||
    c.name.toLowerCase().includes(q) ||
    (c.host || '').toLowerCase().includes(q) ||
    (c.url || '').toLowerCase().includes(q) ||
    (c.tags || []).some(t => t.toLowerCase().includes(q))
  );

  const tbody = document.getElementById('connBody');
  const empty = document.getElementById('connEmpty');
  tbody.innerHTML = '';

  if (filtered.length === 0) {
    empty.classList.remove('hidden');
    document.getElementById('connSubtitle').textContent = 'Keine Verbindungen gefunden';
    return;
  }

  empty.classList.add('hidden');
  document.getElementById('connSubtitle').textContent = `${state.connections.length} Verbindung${state.connections.length !== 1 ? 'en' : ''}`;

  filtered.forEach(c => {
    const tr = document.createElement('tr');
    const host = c.kind === 'web' ? (c.url || '–') : (c.host || '–');
    const port = c.port ? String(c.port) : '–';
    const tags = (c.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join(' ');
    const actions = state.user?.is_admin
      ? `<div style="display:flex;gap:6px">
           <button class="btn small" onclick="editConn('${esc(c.id)}')">Bearbeiten</button>
           <button class="btn small ghost" onclick="deleteConn('${esc(c.id)}')">Löschen</button>
         </div>`
      : '';
    tr.innerHTML = `
      <td><strong>${esc(c.name)}</strong></td>
      <td><span class="badge badge-${esc(c.kind)}">${esc(c.kind).toUpperCase()}</span></td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(host)}</td>
      <td>${esc(port)}</td>
      <td>${esc(c.username || '–')}</td>
      <td>${tags}</td>
      <td>${actions}</td>
    `;
    tbody.appendChild(tr);
  });
}

document.getElementById('addConnBtn').addEventListener('click', () => openConnModal(null));

function openConnModal(conn) {
  state.editingConnId = conn ? conn.id : null;
  document.getElementById('connModalTitle').textContent = conn ? 'Verbindung bearbeiten' : 'Neue Verbindung';

  document.getElementById('cfName').value    = conn?.name     || '';
  document.getElementById('cfKind').value    = conn?.kind     || 'ssh';
  document.getElementById('cfHost').value    = conn?.host     || '';
  document.getElementById('cfPort').value    = conn?.port     || '';
  document.getElementById('cfUser').value    = conn?.username || '';
  document.getElementById('cfDomain').value  = conn?.domain   || '';
  document.getElementById('cfUrl').value     = conn?.url      || '';
  document.getElementById('cfKey').value     = conn?.keyPath  || '';
  document.getElementById('cfTags').value    = (conn?.tags || []).join(', ');
  document.getElementById('cfNotes').value   = conn?.notes    || '';

  updateConnFormFields();
  showModal('connModal');
}

document.getElementById('cfKind').addEventListener('change', updateConnFormFields);

function updateConnFormFields() {
  const kind = document.getElementById('cfKind').value;
  const isWeb = kind === 'web';
  const isRdp = kind === 'rdp';
  setVisible('cfHostField',   !isWeb);
  setVisible('cfPortField',   !isWeb);
  setVisible('cfUserField',   true);
  setVisible('cfDomainField', isRdp);
  setVisible('cfUrlField',    isWeb);
  setVisible('cfKeyField',    kind === 'ssh');

  if (!isWeb && !document.getElementById('cfPort').value) {
    document.getElementById('cfPort').value = kind === 'ssh' ? '22' : kind === 'rdp' ? '3389' : '';
  }
}

function setVisible(id, show) {
  document.getElementById(id).classList.toggle('hidden', !show);
}

document.getElementById('connForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const kind = document.getElementById('cfKind').value;
  const conn = {
    id:        state.editingConnId || undefined,
    name:      document.getElementById('cfName').value.trim(),
    kind,
    host:      document.getElementById('cfHost').value.trim(),
    port:      parseInt(document.getElementById('cfPort').value) || null,
    username:  document.getElementById('cfUser').value.trim(),
    domain:    document.getElementById('cfDomain').value.trim(),
    url:       document.getElementById('cfUrl').value.trim(),
    keyPath:   document.getElementById('cfKey').value.trim(),
    tags:      document.getElementById('cfTags').value.split(',').map(t => t.trim()).filter(Boolean),
    notes:     document.getElementById('cfNotes').value.trim(),
    trustCert: false,
  };
  try {
    if (state.editingConnId) {
      await put(`/api/connections/${state.editingConnId}`, conn);
      toast('Verbindung gespeichert');
    } else {
      await post('/api/connections', conn);
      toast('Verbindung erstellt');
    }
    closeModal('connModal');
    await loadConnections();
  } catch (err) {
    toast(err.message, 'error');
  }
});

function editConn(id) {
  const c = state.connections.find(c => c.id === id);
  if (c) openConnModal(c);
}

async function deleteConn(id) {
  if (!confirm('Verbindung wirklich löschen?')) return;
  try {
    await del(`/api/connections/${id}`);
    toast('Verbindung gelöscht');
    await loadConnections();
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ── Users ──────────────────────────────────────────────────────────────────
async function loadUsers() {
  try {
    state.users = await get('/api/users');
    renderUsers();
  } catch (err) {
    toast(err.message, 'error');
  }
}

function renderUsers() {
  const tbody = document.getElementById('userBody');
  const empty = document.getElementById('userEmpty');
  tbody.innerHTML = '';

  if (state.users.length === 0) { empty.classList.remove('hidden'); return; }
  empty.classList.add('hidden');

  state.users.forEach(u => {
    const tr = document.createElement('tr');
    const date = u.created_at ? new Date(u.created_at).toLocaleDateString('de-DE') : '–';
    const isMe = u.id === state.user?.id;
    tr.innerHTML = `
      <td><strong>${esc(u.username)}</strong>${isMe ? ' <span style="color:var(--text-soft);font-size:12px">(ich)</span>' : ''}</td>
      <td><span class="badge badge-${u.is_admin ? 'admin' : 'user'}">${u.is_admin ? 'Admin' : 'Benutzer'}</span></td>
      <td>${date}</td>
      <td>
        <div style="display:flex;gap:6px">
          <button class="btn small" onclick="editUser(${u.id})">Bearbeiten</button>
          ${!isMe ? `<button class="btn small ghost" onclick="deleteUser(${u.id})">Löschen</button>` : ''}
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

document.getElementById('addUserBtn').addEventListener('click', () => openUserModal(null));

function openUserModal(user) {
  state.editingUserId = user ? user.id : null;
  document.getElementById('userModalTitle').textContent = user ? 'Benutzer bearbeiten' : 'Neuer Benutzer';
  document.getElementById('ufUsername').value  = user?.username || '';
  document.getElementById('ufUsername').disabled = !!user;
  document.getElementById('ufPassword').value  = '';
  document.getElementById('ufPassword').required = !user;
  document.getElementById('ufPasswordLabel').textContent = user ? 'Neues Passwort (leer = unverändert)' : 'Passwort *';
  document.getElementById('ufIsAdmin').checked = user?.is_admin || false;
  showModal('userModal');
}

document.getElementById('userForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    username: document.getElementById('ufUsername').value.trim(),
    is_admin: document.getElementById('ufIsAdmin').checked,
  };
  const pw = document.getElementById('ufPassword').value;
  if (pw) payload.password = pw;

  try {
    if (state.editingUserId) {
      await put(`/api/users/${state.editingUserId}`, { password: pw || undefined, is_admin: payload.is_admin });
      toast('Benutzer gespeichert');
    } else {
      if (!pw) { toast('Passwort erforderlich', 'error'); return; }
      await post('/api/users', { ...payload, password: pw });
      toast('Benutzer erstellt');
    }
    closeModal('userModal');
    await loadUsers();
  } catch (err) {
    toast(err.message, 'error');
  }
});

function editUser(id) {
  const u = state.users.find(u => u.id === id);
  if (u) openUserModal(u);
}

async function deleteUser(id) {
  if (!confirm('Benutzer wirklich löschen?')) return;
  try {
    await del(`/api/users/${id}`);
    toast('Benutzer gelöscht');
    await loadUsers();
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ── API-Keys ───────────────────────────────────────────────────────────────
async function loadApiKeys() {
  try {
    state.apikeys = await get('/api/api-keys');
    renderApiKeys();
  } catch (err) {
    toast(err.message, 'error');
  }
}

function renderApiKeys() {
  const tbody = document.getElementById('apikeyBody');
  const empty = document.getElementById('apikeyEmpty');
  tbody.innerHTML = '';

  if (state.apikeys.length === 0) { empty.classList.remove('hidden'); return; }
  empty.classList.add('hidden');

  state.apikeys.forEach(k => {
    const tr = document.createElement('tr');
    const date = k.created_at ? new Date(k.created_at).toLocaleDateString('de-DE') : '–';
    tr.innerHTML = `
      <td><strong>${esc(k.name)}</strong></td>
      <td><span class="badge badge-${esc(k.permission)}">${k.permission === 'read_write' ? 'Lesen & Schreiben' : 'Nur lesen'}</span></td>
      <td>${date}</td>
      <td>
        <button class="btn small ghost" onclick="deleteApiKey(${k.id})">Löschen</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

document.getElementById('addApiKeyBtn').addEventListener('click', () => {
  document.getElementById('akName').value = '';
  document.getElementById('akPermission').value = 'read';
  showModal('apiKeyModal');
});

document.getElementById('apiKeyForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const result = await post('/api/api-keys', {
      name:       document.getElementById('akName').value.trim(),
      permission: document.getElementById('akPermission').value,
    });
    closeModal('apiKeyModal');
    document.getElementById('keyRevealValue').textContent = result.key;
    showModal('keyRevealModal');
    await loadApiKeys();
  } catch (err) {
    toast(err.message, 'error');
  }
});

document.getElementById('copyKeyBtn').addEventListener('click', () => {
  const key = document.getElementById('keyRevealValue').textContent;
  navigator.clipboard.writeText(key).then(() => toast('In Zwischenablage kopiert'));
});

async function deleteApiKey(id) {
  if (!confirm('API-Key wirklich löschen?')) return;
  try {
    await del(`/api/api-keys/${id}`);
    toast('API-Key gelöscht');
    await loadApiKeys();
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ── Hooks ───────────────────────────────────────────────────────────────────
const HOOK_EVENTS = [
  { value: 'connection.created',   label: 'Verbindung erstellt' },
  { value: 'connection.updated',   label: 'Verbindung geändert' },
  { value: 'connection.deleted',   label: 'Verbindung gelöscht' },
  { value: 'connections.imported', label: 'Verbindungen importiert' },
  { value: 'user.created',         label: 'Benutzer erstellt' },
  { value: 'user.deleted',         label: 'Benutzer gelöscht' },
  { value: 'server.startup',       label: 'Server gestartet' },
];

const HOOK_SCRIPT_HELP = {
  webhook:  'Kontext: <code>payload</code>, <code>headers</code>, <code>params</code>',
  event:    'Kontext: <code>event_type</code>, <code>event_data</code>',
  schedule: 'Kontext: <code>triggered_at</code>, <code>last_run</code>',
};

const HOOK_TYPE_LABEL = { webhook: 'Webhook', event: 'Event', schedule: 'Schedule' };

// Event-Checkboxes einmalig aufbauen
(function () {
  const grid = document.getElementById('hkEventsGrid');
  HOOK_EVENTS.forEach(evt => {
    const lbl = document.createElement('label');
    lbl.className = 'checkbox-label';
    lbl.innerHTML =
      `<input type="checkbox" name="hkEvent" value="${esc(evt.value)}" /> ` +
      `${esc(evt.label)}<br/><span style="font-size:10px;color:var(--text-soft)">${esc(evt.value)}</span>`;
    grid.appendChild(lbl);
  });
}());

document.getElementById('hkType').addEventListener('change', _updateHookFormFields);
document.getElementById('hkInterval').addEventListener('change', () => {
  const custom = document.getElementById('hkInterval').value === 'custom';
  document.getElementById('hkCronField').classList.toggle('hidden', !custom);
});

function _updateHookFormFields() {
  const type = document.getElementById('hkType').value;
  document.getElementById('hkEventsField').classList.toggle('hidden', type !== 'event');
  document.getElementById('hkIntervalField').classList.toggle('hidden', type !== 'schedule');
  if (type !== 'schedule') document.getElementById('hkCronField').classList.add('hidden');
  const base = 'Verfügbar: <code>load_connections()</code>, <code>save_connections(list)</code>, <code>uuid4()</code>, <code>result</code>, <code>logs</code>, <code>log(msg)</code> – <code>import</code> erlaubt';
  document.getElementById('hkScriptHelp').innerHTML =
    (HOOK_SCRIPT_HELP[type] ? HOOK_SCRIPT_HELP[type] + ' · ' : '') + base;
}

async function loadHooks() {
  try {
    state.hooks = await get('/api/hooks');
    renderHooks();
  } catch (err) {
    toast(err.message, 'error');
  }
}

function renderHooks() {
  const tbody = document.getElementById('hookBody');
  const empty = document.getElementById('hookEmpty');
  tbody.innerHTML = '';
  if (state.hooks.length === 0) { empty.classList.remove('hidden'); return; }
  empty.classList.add('hidden');

  state.hooks.forEach(h => {
    const tr = document.createElement('tr');
    const lastRun = h.last_run ? new Date(h.last_run).toLocaleString('de-DE') : '–';

    let details = '–';
    if (h.hook_type === 'webhook') {
      details = `<code style="font-size:11px;color:var(--accent)">/api/hooks/trigger/…</code>`;
    } else if (h.hook_type === 'event') {
      details = (h.event_triggers || []).map(e => `<span class="tag">${esc(e)}</span>`).join(' ') || '–';
    } else if (h.hook_type === 'schedule') {
      details = `<strong>${esc(h.schedule_interval || '–')}</strong>`;
      if (h.next_run) {
        details += `<br/><span style="font-size:11px;color:var(--text-soft)">Nächster: ${esc(new Date(h.next_run).toLocaleString('de-DE'))}</span>`;
      }
    }

    const actions = [
      `<button class="btn small" onclick="editHook('${esc(h.id)}')">Bearbeiten</button>`,
      `<button class="btn small ghost" onclick="runHook('${esc(h.id)}','${esc(h.name)}')">Ausführen</button>`,
      h.hook_type === 'webhook'
        ? `<button class="btn small ghost" onclick="rotateHookToken('${esc(h.id)}','${esc(h.name)}')">Token rotieren</button>`
        : '',
      `<button class="btn small ghost" onclick="toggleHookEnabled('${esc(h.id)}')">${h.enabled ? 'Deaktivieren' : 'Aktivieren'}</button>`,
      `<button class="btn small ghost" onclick="deleteHook('${esc(h.id)}')">Löschen</button>`,
    ].filter(Boolean).join('');

    tr.innerHTML = `
      <td>
        <strong>${esc(h.name)}</strong>
        ${h.description ? `<br/><span style="font-size:11px;color:var(--text-soft)">${esc(h.description)}</span>` : ''}
      </td>
      <td><span class="badge badge-${esc(h.hook_type)}">${esc(HOOK_TYPE_LABEL[h.hook_type] || h.hook_type)}</span></td>
      <td>${details}</td>
      <td><span class="badge badge-${h.enabled ? 'active' : 'inactive'}">${h.enabled ? 'Aktiv' : 'Inaktiv'}</span></td>
      <td style="font-size:12px;color:var(--text-soft)">${esc(lastRun)}</td>
      <td><div style="display:flex;gap:6px;flex-wrap:wrap">${actions}</div></td>
    `;
    tbody.appendChild(tr);
  });
}

document.getElementById('addHookBtn').addEventListener('click', () => openHookModal(null));

function openHookModal(hook) {
  state.editingHookId = hook ? hook.id : null;
  document.getElementById('hookModalTitle').textContent = hook ? 'Hook bearbeiten' : 'Neuer Hook';
  document.getElementById('hkName').value   = hook?.name        || '';
  document.getElementById('hkDesc').value   = hook?.description || '';
  document.getElementById('hkScript').value = hook?.script      || '';

  const typeSelect = document.getElementById('hkType');
  typeSelect.value    = hook?.hook_type || 'webhook';
  typeSelect.disabled = !!hook;  // Typ nach Erstellung nicht mehr änderbar

  // Event-Checkboxes
  document.querySelectorAll('input[name="hkEvent"]').forEach(cb => {
    cb.checked = (hook?.event_triggers || []).includes(cb.value);
  });

  // Intervall
  const VALID = ['5m', '15m', '30m', '1h', '6h', '12h', '24h'];
  const iv = hook?.schedule_interval || '1h';
  if (VALID.includes(iv)) {
    document.getElementById('hkInterval').value = iv;
    document.getElementById('hkCronField').classList.add('hidden');
  } else {
    document.getElementById('hkInterval').value = 'custom';
    document.getElementById('hkCron').value = iv;
    document.getElementById('hkCronField').classList.remove('hidden');
  }

  _updateHookFormFields();
  showModal('hookModal');
}

document.getElementById('hookForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const type = document.getElementById('hkType').value;
  const data = {
    name:        document.getElementById('hkName').value.trim(),
    description: document.getElementById('hkDesc').value.trim() || null,
    hook_type:   type,
    script:      document.getElementById('hkScript').value,
  };

  if (type === 'event') {
    data.event_triggers = [...document.querySelectorAll('input[name="hkEvent"]:checked')].map(cb => cb.value);
    if (!data.event_triggers.length) { toast('Bitte mindestens ein Event auswählen', 'error'); return; }
  }
  if (type === 'schedule') {
    const iv = document.getElementById('hkInterval').value;
    data.schedule_interval = iv === 'custom' ? document.getElementById('hkCron').value.trim() : iv;
    if (!data.schedule_interval) { toast('Bitte ein Intervall angeben', 'error'); return; }
  }

  try {
    if (state.editingHookId) {
      await put(`/api/hooks/${state.editingHookId}`, data);
      toast('Hook gespeichert');
      closeModal('hookModal');
      await loadHooks();
    } else {
      const result = await post('/api/hooks', data);
      closeModal('hookModal');
      if (type === 'webhook' && result.token) {
        showHookToken(result.token, 'Hook erstellt');
      } else {
        toast('Hook erstellt');
      }
      await loadHooks();
    }
  } catch (err) {
    toast(err.message, 'error');
  }
});

async function editHook(id) {
  try {
    const hook = await get(`/api/hooks/${id}`);
    openHookModal(hook);
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function deleteHook(id) {
  if (!confirm('Hook wirklich löschen?')) return;
  try {
    await del(`/api/hooks/${id}`);
    toast('Hook gelöscht');
    await loadHooks();
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function toggleHookEnabled(id) {
  try {
    await post(`/api/hooks/${id}/toggle`);
    await loadHooks();
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function rotateHookToken(id, name) {
  if (!confirm(`Token für „${name}" wirklich neu generieren? Der alte Token wird ungültig.`)) return;
  try {
    const result = await post(`/api/hooks/${id}/rotate`);
    showHookToken(result.token, 'Neuer Token generiert');
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function runHook(id, name) {
  try {
    toast('Hook wird ausgeführt…');
    const result = await post(`/api/hooks/${id}/run`);
    document.getElementById('hookRunTitle').textContent = `Ergebnis: ${name}`;
    document.getElementById('hookRunResult').textContent = JSON.stringify(result, null, 2);
    showModal('hookRunModal');
  } catch (err) {
    toast(err.message, 'error');
  }
}

function showHookToken(token, title) {
  document.getElementById('webhookTokenTitle').textContent = title;
  document.getElementById('webhookTokenValue').textContent = token;
  document.getElementById('webhookTriggerUrl').textContent = `${location.origin}/api/hooks/trigger/${token}`;
  showModal('webhookTokenModal');
}

document.getElementById('copyWebhookTokenBtn').addEventListener('click', () => {
  navigator.clipboard.writeText(document.getElementById('webhookTokenValue').textContent)
    .then(() => toast('Token kopiert'));
});

// ── Export / Import ────────────────────────────────────────────────────────
document.getElementById('exportConnBtn').addEventListener('click', async () => {
  try {
    const res = await fetch('/api/connections/export', {
      headers: { Authorization: `Bearer ${state.token}` },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'connections.json';
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    toast(err.message, 'error');
  }
});

document.getElementById('importConnBtn').addEventListener('click', () => {
  document.getElementById('importFile').value = '';
  document.getElementById('importMode').value = 'merge';
  document.getElementById('importInfo').textContent = '';
  showModal('importModal');
});

document.getElementById('importFile').addEventListener('change', () => {
  const file = document.getElementById('importFile').files[0];
  if (!file) { document.getElementById('importInfo').textContent = ''; return; }
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const data = JSON.parse(e.target.result);
      if (!Array.isArray(data)) throw new Error('Keine Liste');
      document.getElementById('importInfo').textContent =
        `${data.length} Verbindung${data.length !== 1 ? 'en' : ''} gefunden.`;
    } catch {
      document.getElementById('importInfo').textContent = 'Ungültige JSON-Datei.';
    }
  };
  reader.readAsText(file);
});

document.getElementById('importSubmitBtn').addEventListener('click', async () => {
  const file = document.getElementById('importFile').files[0];
  if (!file) { toast('Bitte eine Datei auswählen', 'error'); return; }
  const mode = document.getElementById('importMode').value;

  let connections;
  try {
    connections = JSON.parse(await file.text());
    if (!Array.isArray(connections)) throw new Error();
  } catch {
    toast('Ungültige JSON-Datei', 'error');
    return;
  }

  const msg = mode === 'replace'
    ? `Alle bestehenden Verbindungen werden gelöscht und durch ${connections.length} importierte ersetzt. Fortfahren?`
    : `${connections.length} Verbindung${connections.length !== 1 ? 'en' : ''} hinzufügen?`;
  if (!confirm(msg)) return;

  try {
    const result = await post('/api/connections/import', { connections, mode });
    toast(`${result.imported} Verbindung${result.imported !== 1 ? 'en' : ''} importiert`);
    closeModal('importModal');
    await loadConnections();
  } catch (err) {
    toast(err.message, 'error');
  }
});

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

// ── Escape helper ──────────────────────────────────────────────────────────
function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;');
}

// ── Startup ────────────────────────────────────────────────────────────────
if (state.token) {
  initApp();
}
