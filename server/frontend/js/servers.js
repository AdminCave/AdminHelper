/* AdminHelper – Servers */
'use strict';

async function loadServers() {
  try {
    state.servers = await get('/api/servers');
    // Monitoring-Status fuer Status-Dots laden (still fail)
    try { state.monitorChecks = await get('/api/monitoring/status'); } catch { /* ignore */ }
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

    const monitorStatus = _getServerMonitorStatus(s.id);
    card.innerHTML = `
      <div class="server-card-header" onclick="toggleServerCard(this)">
        <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0">
          <span class="server-chevron">&#x25B6;</span>
          ${monitorStatus ? `<span class="monitor-dot monitor-${monitorStatus}" title="Monitoring: ${monitorStatus}"></span>` : ''}
          <div style="min-width:0">
            <strong>${esc(s.name)}</strong>
            <span style="color:var(--text-muted);font-size:13px;margin-left:8px">${esc(s.hostname)}${osLabel}</span>
          </div>
          <span style="color:var(--text-muted);font-size:12px;flex-shrink:0">${t(connCount !== 1 ? 'page.servers.connCountPlural' : 'page.servers.connCount', { count: connCount })}</span>
          ${tags ? `<div style="display:flex;gap:4px;flex-shrink:0">${tags}</div>` : ''}
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0" onclick="event.stopPropagation()">
          <button class="btn small" onclick="editServer('${esc(s.id)}')">${t('action.edit')}</button>
          <button class="btn small ghost" onclick="deleteServer('${esc(s.id)}')">${t('action.delete')}</button>
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
          <strong style="color:var(--text-muted)">${t('page.servers.noServer')}</strong>
          <span style="color:var(--text-muted);font-size:12px">${t(standalone.length !== 1 ? 'page.servers.connCountPlural' : 'page.servers.connCount', { count: standalone.length })}</span>
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
    return `<div style="padding:12px;color:var(--text-muted);font-size:13px">${t('page.servers.noConnections')}</div>`;
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
  return `<table class="data-table" style="margin:0"><thead><tr><th>${t('table.type')}</th><th>${t('table.name')}</th><th>${t('table.hostUrl')}</th><th>${t('table.port')}</th><th>${t('table.user')}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function toggleServerCard(headerEl) {
  const body = headerEl.nextElementSibling;
  const chevron = headerEl.querySelector('.server-chevron');
  body.classList.toggle('hidden');
  chevron.classList.toggle('open');
}

document.getElementById('addServerBtn').addEventListener('click', () => openServerModal(null));

async function openServerModal(server) {
  state.editingServerId = server ? server.id : null;
  document.getElementById('serverModalTitle').textContent = server ? t('modal.server.title') : t('modal.server.titleNew');
  document.getElementById('sfName').value     = server?.name     || '';
  document.getElementById('sfHostname').value = server?.hostname || '';
  document.getElementById('sfOsType').value   = server?.osType   || '';
  document.getElementById('sfTags').value     = (server?.tags || []).join(', ');
  document.getElementById('sfNotes').value    = server?.notes    || '';

  // Template-Dropdown befuellen
  const sel = document.getElementById('sfTemplates');
  try {
    const templates = await get('/api/monitoring/templates');
    let assignedIds = [];
    if (server) {
      const assignments = await get(`/api/monitoring/templates/assignments/${server.id}`);
      assignedIds = assignments.map(a => a.templateId);
    }
    sel.innerHTML = templates.map(t =>
      `<option value="${esc(t.id)}"${assignedIds.includes(t.id) ? ' selected' : ''}>${esc(t.name)}</option>`
    ).join('');
    sel.dataset.originalIds = JSON.stringify(assignedIds);
  } catch {
    sel.innerHTML = `<option disabled>${t('modal.server.templatesUnavailable')}</option>`;
    sel.dataset.originalIds = '[]';
  }

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
    let serverId = state.editingServerId;
    if (serverId) {
      await put(`/api/servers/${serverId}`, data);
      toast(t('toast.server.saved'));
    } else {
      const created = await post('/api/servers', data);
      serverId = created.id;
      toast(t('toast.server.created'));
    }

    await _syncTemplateAssignments(serverId, data.hostname, data.name);

    closeModal('serverModal');
    await loadServers();
  } catch (err) {
    toast(err.message, 'error');
  }
});

async function _syncTemplateAssignments(serverId, hostname, serverName) {
  const sel = document.getElementById('sfTemplates');
  const oldIds = new Set(JSON.parse(sel.dataset.originalIds || '[]'));
  const newIds = new Set([...sel.selectedOptions].map(o => o.value));

  const toAdd = [...newIds].filter(id => !oldIds.has(id));
  const toRemove = [...oldIds].filter(id => !newIds.has(id));

  const calls = [
    ...toAdd.map(id => post(`/api/monitoring/templates/${id}/assign`, {
      server_id: serverId, hostname, server_name: serverName,
    }).catch(() => null)),
    ...toRemove.map(id => del(`/api/monitoring/templates/${id}/assign/${serverId}`).catch(() => null)),
  ];
  if (calls.length) await Promise.all(calls);
}

function editServer(id) {
  const s = state.servers.find(s => s.id === id);
  if (s) openServerModal(s);
}

async function deleteServer(id) {
  if (!confirm(t('confirm.server.delete'))) return;
  try {
    await del(`/api/servers/${id}`);
    toast(t('toast.server.deleted'));
    await loadServers();
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ── Monitoring Status-Dot fuer Server-Cards ───────────────────────────────
function _getServerMonitorStatus(serverId) {
  const checks = (state.monitorChecks || []).filter(c => c.serverId === serverId);
  if (checks.length === 0) return null;
  let worst = 'ok';
  for (const c of checks) {
    const st = c.state?.status || 'pending';
    if (st === 'critical') return 'critical';
    if (st === 'warning') worst = 'warning';
    if (st === 'unknown' && worst === 'ok') worst = 'unknown';
    if (st === 'pending' && worst === 'ok') worst = 'pending';
  }
  return worst;
}
