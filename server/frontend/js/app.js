/* Simple Remote Manager – App Entry Point (Login, Init, Nav, Startup) */
'use strict';

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
    localStorage.setItem('srm_token', data.access_token);
    localStorage.setItem('srm_refresh_token', data.refresh_token);
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
    // Server-Liste vorab laden
    try { state.servers = await get('/api/servers'); } catch { /* ignore */ }
  }

  const hash = location.hash.replace('#/', '') || 'connections';
  navigate(hash);
}

// ── Logout ─────────────────────────────────────────────────────────────────
document.getElementById('logoutBtn').addEventListener('click', logout);
function logout() {
  state.token = null;
  localStorage.removeItem('srm_token');
  localStorage.removeItem('srm_refresh_token');
  location.reload();
}

// ── Nav ────────────────────────────────────────────────────────────────────
document.querySelectorAll('.nav-item[data-page]').forEach(btn => {
  btn.addEventListener('click', () => navigate(btn.dataset.page));
});

function navigate(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const pageEl = document.getElementById(`page${cap(page)}`);
  if (pageEl) pageEl.classList.add('active');
  document.querySelectorAll(`.nav-item[data-page="${page}"]`).forEach(n => n.classList.add('active'));
  location.hash = `/${page}`;
  if (page === 'connections') loadConnections();
  if (page === 'servers')     loadServers();
  if (page === 'users')       loadUsers();
  if (page === 'apikeys')     loadApiKeys();
  if (page === 'hooks')       loadHooks();
  if (page === 'frp')         loadFrp();
}

// ── Startup ────────────────────────────────────────────────────────────────
if (state.token) {
  initApp();
}
