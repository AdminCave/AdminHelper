/* AdminHelper – Users */
'use strict';

async function loadUsers() {
  try {
    state.users = await get('/api/users');
    if (state.servers.length === 0) {
      state.servers = await get('/api/servers');
    }
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
      <td><strong>${esc(u.username)}</strong>${isMe ? ` <span style="color:var(--text-muted);font-size:12px">${t('page.users.me')}</span>` : ''}</td>
      <td><span class="badge badge-${u.is_admin ? 'admin' : 'user'}">${u.is_admin ? t('role.admin') : t('role.user')}</span></td>
      <td>${date}</td>
      <td>
        <div style="display:flex;gap:6px">
          <button class="btn small" onclick="editUser(${u.id})">${t('action.edit')}</button>
          ${!isMe ? `<button class="btn small ghost" onclick="deleteUser(${u.id})">${t('action.delete')}</button>` : ''}
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

document.getElementById('addUserBtn').addEventListener('click', () => openUserModal(null));

function openUserModal(user) {
  state.editingUserId = user ? user.id : null;
  document.getElementById('userModalTitle').textContent = user ? t('modal.user.title') : t('modal.user.titleNew');
  document.getElementById('ufUsername').value  = user?.username || '';
  document.getElementById('ufUsername').disabled = !!user;
  document.getElementById('ufPassword').value  = '';
  document.getElementById('ufPassword').required = !user;
  document.getElementById('ufPasswordLabel').textContent = user ? t('modal.user.passwordEdit') : t('modal.user.password');
  document.getElementById('ufIsAdmin').checked = user?.is_admin || false;

  // Server-Checkboxen rendern
  const selectedIds = new Set(user?.server_ids || []);
  const listEl = document.getElementById('ufServerList');
  if (state.servers.length > 0) {
    listEl.innerHTML = state.servers.map(s => `
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
        <input type="checkbox" value="${esc(s.id)}" ${selectedIds.has(s.id) ? 'checked' : ''} />
        <span>${esc(s.name)}</span>
        <span style="color:var(--text-muted);font-size:11px">${esc(s.hostname)}</span>
      </label>
    `).join('');
  } else {
    listEl.innerHTML = `<span style="color:var(--text-muted);font-size:12px">${t('page.users.noServers')}</span>`;
  }

  showModal('userModal');
}

document.getElementById('userForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const serverCheckboxes = document.querySelectorAll('#ufServerList input[type="checkbox"]:checked');
  const serverIds = Array.from(serverCheckboxes).map(cb => cb.value);
  const pw = document.getElementById('ufPassword').value;

  try {
    if (state.editingUserId) {
      const data = { is_admin: document.getElementById('ufIsAdmin').checked, server_ids: serverIds };
      if (pw) data.password = pw;
      await put(`/api/users/${state.editingUserId}`, data);
      toast(t('toast.user.saved'));
    } else {
      if (!pw) { toast(t('modal.user.passwordRequired'), 'error'); return; }
      await post('/api/users', {
        username: document.getElementById('ufUsername').value.trim(),
        password: pw,
        is_admin: document.getElementById('ufIsAdmin').checked,
        server_ids: serverIds,
      });
      toast(t('toast.user.created'));
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
  if (!confirm(t('confirm.user.delete'))) return;
  try {
    await del(`/api/users/${id}`);
    toast(t('toast.user.deleted'));
    await loadUsers();
  } catch (err) {
    toast(err.message, 'error');
  }
}
