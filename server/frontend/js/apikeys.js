/* Simple Remote Manager – API Keys */
'use strict';

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
