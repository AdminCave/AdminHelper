/* Simple Remote Manager – Server Web UI */
'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  token: localStorage.getItem('srm_token') || null,
  user: null,
  connections: [],
  users: [],
  apikeys: [],
  editingConnId: null,
  editingUserId: null,
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
    id:        state.editingConnId || (crypto.randomUUID?.() ?? ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c => (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16))),
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
