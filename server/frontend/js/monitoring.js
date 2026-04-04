/* Simple Remote Manager – Monitoring */
'use strict';

// ── Load ���─────────────────────────────────────────────────────────────────
async function loadMonitoring() {
  try {
    state.monitorChecks = await get('/api/monitoring/status');
    renderMonitorOverview();
    renderMonitorChecks();
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ── Overview Cards ────────────────────────────────────────────────────────
function renderMonitorOverview() {
  const container = document.getElementById('monitorOverview');
  const checks = state.monitorChecks;
  const counts = { total: checks.length, ok: 0, warning: 0, critical: 0 };

  checks.forEach(c => {
    const st = c.state?.status || 'pending';
    if (st === 'ok') counts.ok++;
    else if (st === 'warning') counts.warning++;
    else if (st === 'critical') counts.critical++;
  });

  container.innerHTML = `
    <div class="monitor-summary-card">
      <div class="monitor-summary-value">${counts.total}</div>
      <div class="monitor-summary-label">Gesamt</div>
    </div>
    <div class="monitor-summary-card monitor-summary-ok">
      <div class="monitor-summary-value">${counts.ok}</div>
      <div class="monitor-summary-label">OK</div>
    </div>
    <div class="monitor-summary-card monitor-summary-warning">
      <div class="monitor-summary-value">${counts.warning}</div>
      <div class="monitor-summary-label">Warnung</div>
    </div>
    <div class="monitor-summary-card monitor-summary-critical">
      <div class="monitor-summary-value">${counts.critical}</div>
      <div class="monitor-summary-label">Kritisch</div>
    </div>
  `;
}

// ── Check List ────��───────────────────────────────────────────────────────
function renderMonitorChecks() {
  const container = document.getElementById('monitorCheckList');
  const empty = document.getElementById('monitorEmpty');
  container.innerHTML = '';

  const checks = state.monitorChecks;
  if (checks.length === 0) {
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  // Gruppieren nach Server
  const byServer = {};
  const noServer = [];
  checks.forEach(c => {
    if (c.serverId) {
      if (!byServer[c.serverId]) byServer[c.serverId] = { name: null, checks: [] };
      byServer[c.serverId].checks.push(c);
    } else {
      noServer.push(c);
    }
  });

  // Server-Namen auflösen
  (state.servers || []).forEach(s => {
    if (byServer[s.id]) byServer[s.id].name = s.name;
  });

  // Server-Gruppen rendern
  Object.entries(byServer).forEach(([serverId, group]) => {
    const worstStatus = _worstStatus(group.checks);
    container.appendChild(_renderCheckGroup(group.name || serverId, group.checks, worstStatus));
  });

  // Checks ohne Server
  if (noServer.length > 0) {
    container.appendChild(_renderCheckGroup('Ohne Server', noServer, _worstStatus(noServer)));
  }
}

function _worstStatus(checks) {
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

function _renderCheckGroup(title, checks, worstStatus) {
  const card = document.createElement('div');
  card.className = 'server-card';
  card.innerHTML = `
    <div class="server-card-header" onclick="toggleServerCard(this)">
      <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0">
        <span class="server-chevron">&#x25B6;</span>
        <span class="monitor-dot monitor-${worstStatus}"></span>
        <strong>${esc(title)}</strong>
        <span style="color:var(--text-soft);font-size:12px">${checks.length} Check${checks.length !== 1 ? 's' : ''}</span>
      </div>
    </div>
    <div class="server-card-body hidden">
      ${_renderCheckTable(checks)}
    </div>
  `;
  return card;
}

function _renderCheckTable(checks) {
  const rows = checks.map(c => {
    const st = c.state?.status || 'pending';
    const msg = c.state?.message || '\u2013';
    const lastCheck = c.state?.lastCheck ? _formatTime(c.state.lastCheck) : 'Noch nie';
    const typeBadge = c.checkType.toUpperCase();
    return `<tr>
      <td><span class="monitor-dot monitor-${st}"></span></td>
      <td><span class="badge badge-${c.checkType}">${esc(typeBadge)}</span></td>
      <td><strong>${esc(c.name)}</strong></td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-soft)">${esc(msg)}</td>
      <td style="color:var(--text-soft);font-size:12px">${esc(lastCheck)}</td>
      <td style="white-space:nowrap">
        <button class="btn small" onclick="runMonitorCheck('${c.id}')" title="Jetzt ausfuehren">&#x25B6;</button>
        <button class="btn small" onclick="editMonitorCheck('${c.id}')">Bearbeiten</button>
        <button class="btn small ghost" onclick="toggleMonitorCheck('${c.id}')">
          ${c.enabled ? 'Deaktivieren' : 'Aktivieren'}
        </button>
        <button class="btn small ghost" onclick="deleteMonitorCheck('${c.id}')">L\u00f6schen</button>
      </td>
    </tr>`;
  }).join('');

  return `<table class="data-table" style="margin:0">
    <thead><tr><th></th><th>Typ</th><th>Name</th><th>Status</th><th>Letzter Check</th><th>Aktionen</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function _formatTime(isoStr) {
  try {
    const d = new Date(isoStr);
    return d.toLocaleString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit', day: '2-digit', month: '2-digit' });
  } catch {
    return isoStr;
  }
}

// ── Check Modal ───────────────────────────────────────────────────────────
document.getElementById('addMonitorCheckBtn').addEventListener('click', () => openMonitorCheckModal(null));

// Check-Typ wechsel: Config-Felder anzeigen/verstecken
document.getElementById('mcCheckType').addEventListener('change', function() {
  document.getElementById('mcPingConfig').classList.toggle('hidden', this.value !== 'ping');
  document.getElementById('mcTcpConfig').classList.toggle('hidden', this.value !== 'tcp');
  document.getElementById('mcHttpConfig').classList.toggle('hidden', this.value !== 'http');
});

function openMonitorCheckModal(check) {
  state.editingMonitorCheckId = check ? check.id : null;
  document.getElementById('monitorCheckModalTitle').textContent = check ? 'Check bearbeiten' : 'Neuer Check';

  // Server-Dropdown befuellen
  const serverSelect = document.getElementById('mcServerId');
  serverSelect.innerHTML = '<option value="">-- Kein Server --</option>' +
    (state.servers || []).map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');

  // Felder zuruecksetzen
  document.getElementById('mcName').value = check?.name || '';
  document.getElementById('mcServerId').value = check?.serverId || '';
  document.getElementById('mcCheckType').value = check?.checkType || 'ping';
  document.getElementById('mcInterval').value = check?.interval || '5m';
  document.getElementById('mcSeverity').value = check?.severity || 'critical';
  document.getElementById('mcConsecutiveFails').value = check?.consecutiveFails ?? 3;
  document.getElementById('mcDescription').value = check?.description || '';

  // Config-Felder
  const cfg = check?.config || {};
  document.getElementById('mcPingTarget').value = cfg.target || '';
  document.getElementById('mcPingTimeout').value = cfg.timeout || 5;
  document.getElementById('mcTcpTarget').value = cfg.target || '';
  document.getElementById('mcTcpPort').value = cfg.port || '';
  document.getElementById('mcTcpTimeout').value = cfg.timeout || 5;
  document.getElementById('mcHttpUrl').value = cfg.url || '';
  document.getElementById('mcHttpMethod').value = cfg.method || 'GET';
  document.getElementById('mcHttpStatus').value = cfg.expected_status || 200;
  document.getElementById('mcHttpTimeout').value = cfg.timeout || 10;
  document.getElementById('mcHttpVerifySsl').value = cfg.verify_ssl !== false ? 'true' : 'false';
  document.getElementById('mcHttpSearch').value = cfg.search_string || '';

  // Config-Sections umschalten
  const type = check?.checkType || 'ping';
  document.getElementById('mcPingConfig').classList.toggle('hidden', type !== 'ping');
  document.getElementById('mcTcpConfig').classList.toggle('hidden', type !== 'tcp');
  document.getElementById('mcHttpConfig').classList.toggle('hidden', type !== 'http');

  showModal('monitorCheckModal');
}

function _buildCheckConfig() {
  const type = document.getElementById('mcCheckType').value;
  if (type === 'ping') {
    return {
      target: document.getElementById('mcPingTarget').value.trim(),
      timeout: parseInt(document.getElementById('mcPingTimeout').value) || 5,
    };
  }
  if (type === 'tcp') {
    return {
      target: document.getElementById('mcTcpTarget').value.trim(),
      port: parseInt(document.getElementById('mcTcpPort').value) || 0,
      timeout: parseInt(document.getElementById('mcTcpTimeout').value) || 5,
    };
  }
  if (type === 'http') {
    const cfg = {
      url: document.getElementById('mcHttpUrl').value.trim(),
      method: document.getElementById('mcHttpMethod').value,
      expected_status: parseInt(document.getElementById('mcHttpStatus').value) || 200,
      timeout: parseInt(document.getElementById('mcHttpTimeout').value) || 10,
      verify_ssl: document.getElementById('mcHttpVerifySsl').value === 'true',
    };
    const search = document.getElementById('mcHttpSearch').value.trim();
    if (search) cfg.search_string = search;
    return cfg;
  }
  return {};
}

document.getElementById('monitorCheckForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = {
    name: document.getElementById('mcName').value.trim(),
    server_id: document.getElementById('mcServerId').value || null,
    check_type: document.getElementById('mcCheckType').value,
    interval: document.getElementById('mcInterval').value,
    severity: document.getElementById('mcSeverity').value,
    consecutive_fails: parseInt(document.getElementById('mcConsecutiveFails').value) || 3,
    description: document.getElementById('mcDescription').value.trim() || null,
    config: _buildCheckConfig(),
  };
  try {
    if (state.editingMonitorCheckId) {
      await put(`/api/monitoring/checks/${state.editingMonitorCheckId}`, data);
      toast('Check gespeichert');
    } else {
      await post('/api/monitoring/checks', data);
      toast('Check erstellt');
    }
    closeModal('monitorCheckModal');
    await loadMonitoring();
  } catch (err) {
    toast(err.message, 'error');
  }
});

// ── Actions ─────────��─────────────────────────────────────────────────────
function editMonitorCheck(id) {
  const c = state.monitorChecks.find(c => c.id === id);
  if (c) openMonitorCheckModal(c);
}

async function runMonitorCheck(id) {
  try {
    await post(`/api/monitoring/checks/${id}/run`);
    toast('Check ausgefuehrt');
    await loadMonitoring();
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function toggleMonitorCheck(id) {
  try {
    await post(`/api/monitoring/checks/${id}/toggle`);
    toast('Check aktualisiert');
    await loadMonitoring();
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function deleteMonitorCheck(id) {
  if (!confirm('Check wirklich loeschen?')) return;
  try {
    await del(`/api/monitoring/checks/${id}`);
    toast('Check geloescht');
    await loadMonitoring();
  } catch (err) {
    toast(err.message, 'error');
  }
}
