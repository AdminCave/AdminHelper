/* Simple Remote Manager – Servers */
'use strict';

async function loadServers() {
  try {
    state.servers = await get('/api/servers');
    renderTagFilter('serverTagSelect', state.servers, 'serverTagFilter');
    renderServers();
  } catch (err) {
    toast(err.message, 'error');
  }
}

document.getElementById('serverTagSelect').addEventListener('change', function() {
  state.serverTagFilter = this.value;
  renderServers();
});

const serverSearch = document.getElementById('serverSearch');
serverSearch.addEventListener('input', renderServers);

function renderServers() {
  const q = serverSearch.value.toLowerCase();
  const container = document.getElementById('serverList');
  const empty = document.getElementById('serverEmpty');
  container.innerHTML = '';

  let filtered = state.servers.filter(s =>
    !q ||
    s.name.toLowerCase().includes(q) ||
    s.hostname.toLowerCase().includes(q) ||
    (s.tags || []).some(t => t.toLowerCase().includes(q)) ||
    (s.connections || []).some(c =>
      c.name.toLowerCase().includes(q) ||
      (c.host || '').toLowerCase().includes(q)
    )
  );

  if (state.serverTagFilter) {
    filtered = filtered.filter(s => (s.tags || []).includes(state.serverTagFilter));
  }

  const assignedIds = new Set();
  state.servers.forEach(s => (s.connections || []).forEach(c => assignedIds.add(c.id)));
  const standalone = (state.connections || []).filter(c => !assignedIds.has(c.id) && !c.serverId);

  if (filtered.length === 0 && standalone.length === 0) {
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  filtered.forEach(s => {
    const card = document.createElement('div');
    card.className = 'server-card';
    const tags = (s.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join(' ');
    const connCount = (s.connections || []).length;
    const osLabel = s.osType ? ` · ${esc(s.osType)}` : '';

    card.innerHTML = `
      <div class="server-card-header" onclick="toggleServerCard(this)">
        <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0">
          <span class="server-chevron">&#x25B6;</span>
          <div style="min-width:0">
            <strong>${esc(s.name)}</strong>
            <span style="color:var(--text-soft);font-size:13px;margin-left:8px">${esc(s.hostname)}${osLabel}</span>
          </div>
          <span style="color:var(--text-soft);font-size:12px;flex-shrink:0">${connCount} Verbindung${connCount !== 1 ? 'en' : ''}</span>
          ${tags ? `<div style="display:flex;gap:4px;flex-shrink:0">${tags}</div>` : ''}
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0" onclick="event.stopPropagation()">
          <button class="btn small" onclick="editServer('${esc(s.id)}')">Bearbeiten</button>
          <button class="btn small ghost" onclick="deleteServer('${esc(s.id)}')">L\u00f6schen</button>
        </div>
      </div>
      <div class="server-card-body hidden">
        ${_renderServerConnections(s.connections || [])}
      </div>
    `;
    container.appendChild(card);
  });

  if (standalone.length > 0) {
    const card = document.createElement('div');
    card.className = 'server-card';
    card.innerHTML = `
      <div class="server-card-header" onclick="toggleServerCard(this)">
        <div style="display:flex;align-items:center;gap:10px;flex:1">
          <span class="server-chevron">&#x25B6;</span>
          <strong style="color:var(--text-soft)">Ohne Server</strong>
          <span style="color:var(--text-soft);font-size:12px">${standalone.length} Verbindung${standalone.length !== 1 ? 'en' : ''}</span>
        </div>
      </div>
      <div class="server-card-body hidden">
        ${_renderServerConnections(standalone)}
      </div>
    `;
    container.appendChild(card);
  }
}

function _renderServerConnections(conns) {
  if (conns.length === 0) {
    return '<div style="padding:12px;color:var(--text-soft);font-size:13px">Keine Verbindungen zugeordnet.</div>';
  }
  const rows = conns.map(c => {
    const host = c.kind === 'web' ? (c.url || '\u2013') : (c.host || '\u2013');
    const port = c.port ? String(c.port) : '\u2013';
    return `<tr>
      <td><span class="badge badge-${esc(c.kind)}">${esc(c.kind).toUpperCase()}</span></td>
      <td><strong>${esc(c.name)}</strong></td>
      <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(host)}</td>
      <td>${esc(port)}</td>
      <td>${esc(c.username || '\u2013')}</td>
    </tr>`;
  }).join('');
  return `<table class="data-table" style="margin:0"><thead><tr><th>Typ</th><th>Name</th><th>Host / URL</th><th>Port</th><th>Benutzer</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function toggleServerCard(headerEl) {
  const body = headerEl.nextElementSibling;
  const chevron = headerEl.querySelector('.server-chevron');
  body.classList.toggle('hidden');
  chevron.classList.toggle('open');
}

document.getElementById('addServerBtn').addEventListener('click', () => openServerModal(null));

function openServerModal(server) {
  state.editingServerId = server ? server.id : null;
  document.getElementById('serverModalTitle').textContent = server ? 'Server bearbeiten' : 'Neuer Server';
  document.getElementById('sfName').value     = server?.name     || '';
  document.getElementById('sfHostname').value = server?.hostname || '';
  document.getElementById('sfOsType').value   = server?.osType   || '';
  document.getElementById('sfTags').value     = (server?.tags || []).join(', ');
  document.getElementById('sfNotes').value    = server?.notes    || '';
  showModal('serverModal');
}

document.getElementById('serverForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = {
    name:     document.getElementById('sfName').value.trim(),
    hostname: document.getElementById('sfHostname').value.trim(),
    os_type:  document.getElementById('sfOsType').value || null,
    tags:     parseTags(document.getElementById('sfTags').value),
    notes:    document.getElementById('sfNotes').value.trim(),
  };
  try {
    if (state.editingServerId) {
      await put(`/api/servers/${state.editingServerId}`, data);
      toast('Server gespeichert');
    } else {
      await post('/api/servers', data);
      toast('Server erstellt');
    }
    closeModal('serverModal');
    await loadServers();
  } catch (err) {
    toast(err.message, 'error');
  }
});

function editServer(id) {
  const s = state.servers.find(s => s.id === id);
  if (s) openServerModal(s);
}

async function deleteServer(id) {
  if (!confirm('Server wirklich l\u00f6schen? Zugeordnete Verbindungen werden zu Standalone.')) return;
  try {
    await del(`/api/servers/${id}`);
    toast('Server gel\u00f6scht');
    await loadServers();
  } catch (err) {
    toast(err.message, 'error');
  }
}
