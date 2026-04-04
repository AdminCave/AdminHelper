/* Simple Remote Manager – Users */
'use strict';

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
