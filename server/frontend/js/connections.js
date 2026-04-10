/* AdminHelper – Connections */
'use strict';

async function loadConnections() {
  try {
    state.connections = await get('/api/connections');
    renderTagFilter('connTagSelect', state.connections, 'connTagFilter');
    renderConnections();
  } catch (err) {
    toast(err.message, 'error');
  }
}

const connSearch = document.getElementById('connSearch');
connSearch.addEventListener('input', renderConnections);

document.getElementById('connTagSelect').addEventListener('change', function() {
  state.connTagFilter = this.value;
  renderConnections();
});

function renderConnections() {
  const q = connSearch.value.toLowerCase();
  const filtered = state.connections.filter(c => {
    if (state.connTagFilter && !(c.tags || []).includes(state.connTagFilter)) return false;
    if (q && ![
      c.name,
      c.host || '',
      c.url || '',
      c.kind || '',
      c.username || '',
      (c.tags || []).join(' '),
    ].some(f => f.toLowerCase().includes(q))) return false;
    return true;
  });

  const tbody = document.getElementById('connBody');
  const empty = document.getElementById('connEmpty');
  tbody.innerHTML = '';

  if (filtered.length === 0) {
    empty.classList.remove('hidden');
    document.getElementById('connSubtitle').textContent = t('page.connections.none');
    return;
  }

  empty.classList.add('hidden');
  document.getElementById('connSubtitle').textContent = t(state.connections.length !== 1 ? 'page.connections.countPlural' : 'page.connections.count', { count: state.connections.length });

  filtered.forEach(c => {
    const tr = document.createElement('tr');
    const host = c.kind === 'web' ? (c.url || '–') : (c.host || '–');
    const port = c.port ? String(c.port) : '–';
    const tags = (c.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join(' ');
    const actions = state.user?.is_admin
      ? `<div style="display:flex;gap:6px">
           <button class="btn small" onclick="editConn('${esc(c.id)}')">${t('action.edit')}</button>
           <button class="btn small ghost" onclick="deleteConn('${esc(c.id)}')">${t('action.delete')}</button>
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
  document.getElementById('connModalTitle').textContent = conn ? t('modal.connection.title') : t('modal.connection.titleNew');

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

  // Server-Dropdown befüllen
  const cfServer = document.getElementById('cfServer');
  cfServer.innerHTML = `<option value="">${t('modal.connection.noServer')}</option>`;
  state.servers.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.id;
    opt.textContent = `${s.name} (${s.hostname})`;
    cfServer.appendChild(opt);
  });
  cfServer.value = conn?.serverId || '';

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
    tags:      parseTags(document.getElementById('cfTags').value),
    notes:     document.getElementById('cfNotes').value.trim(),
    trustCert: false,
    serverId:  document.getElementById('cfServer').value || null,
  };
  try {
    if (state.editingConnId) {
      await put(`/api/connections/${state.editingConnId}`, conn);
      toast(t('toast.connection.saved'));
    } else {
      await post('/api/connections', conn);
      toast(t('toast.connection.created'));
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
  if (!confirm(t('confirm.connection.delete'))) return;
  try {
    await del(`/api/connections/${id}`);
    toast(t('toast.connection.deleted'));
    await loadConnections();
  } catch (err) {
    toast(err.message, 'error');
  }
}

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
      if (!Array.isArray(data)) throw new Error('invalid');
      document.getElementById('importInfo').textContent =
        t(data.length !== 1 ? 'import.foundPlural' : 'import.found', { count: data.length });
    } catch {
      document.getElementById('importInfo').textContent = t('import.invalidJson');
    }
  };
  reader.readAsText(file);
});

document.getElementById('importSubmitBtn').addEventListener('click', async () => {
  const file = document.getElementById('importFile').files[0];
  if (!file) { toast(t('import.selectFile'), 'error'); return; }
  const mode = document.getElementById('importMode').value;

  let connections;
  try {
    connections = JSON.parse(await file.text());
    if (!Array.isArray(connections)) throw new Error();
  } catch {
    toast(t('import.invalidJsonShort'), 'error');
    return;
  }

  const msg = mode === 'replace'
    ? t('import.confirmReplace', { count: connections.length })
    : t(connections.length !== 1 ? 'import.confirmMergePlural' : 'import.confirmMerge', { count: connections.length });
  if (!confirm(msg)) return;

  try {
    const result = await post('/api/connections/import', { connections, mode });
    toast(t(result.imported !== 1 ? 'import.resultPlural' : 'import.result', { count: result.imported }));
    closeModal('importModal');
    await loadConnections();
  } catch (err) {
    toast(err.message, 'error');
  }
});
