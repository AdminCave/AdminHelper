/* Simple Remote Manager – Monitoring */
'use strict';

// ── Load ���─────────────────────────────────────────────────────────────────
async function loadMonitoring() {
  try {
    const [checks, alerts] = await Promise.all([
      get('/api/monitoring/status'),
      get('/api/monitoring/alerts'),
    ]);
    state.monitorChecks = checks;
    state.monitorAlertRules = alerts;
    renderMonitorOverview();
    renderMonitorChecks();
    renderMonitorAlerts();
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
  document.getElementById('mcAgentResourcesConfig').classList.toggle('hidden', this.value !== 'agent_resources');
  document.getElementById('mcServiceProcessConfig').classList.toggle('hidden', this.value !== 'service_process');
  document.getElementById('mcSnmpConfig').classList.toggle('hidden', this.value !== 'snmp');
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

  // Agent Resources Config
  document.getElementById('mcAgentCpuWarn').value = cfg.cpu_warn ?? 80;
  document.getElementById('mcAgentCpuCrit').value = cfg.cpu_crit ?? 95;
  document.getElementById('mcAgentMemWarn').value = cfg.memory_warn ?? 80;
  document.getElementById('mcAgentMemCrit').value = cfg.memory_crit ?? 95;
  document.getElementById('mcAgentDiskWarn').value = cfg.disk_warn ?? 85;
  document.getElementById('mcAgentDiskCrit').value = cfg.disk_crit ?? 95;

  // Service Process Config
  document.getElementById('mcServiceNames').value = (cfg.services || []).join(', ');

  // SNMP Config
  document.getElementById('mcSnmpTarget').value = cfg.target || '';
  document.getElementById('mcSnmpPort').value = cfg.port || 161;
  document.getElementById('mcSnmpCommunity').value = cfg.community || 'public';
  document.getElementById('mcSnmpMode').value = cfg.mode || 'get';
  document.getElementById('mcSnmpOid').value = cfg.oid || '';
  document.getElementById('mcSnmpExpected').value = cfg.expected_value || '';
  document.getElementById('mcSnmpTimeout').value = cfg.timeout || 5;
  document.getElementById('mcSnmpWarnThreshold').value = cfg.warning_threshold || '';
  document.getElementById('mcSnmpCritThreshold').value = cfg.critical_threshold || '';

  // Config-Sections umschalten
  const type = check?.checkType || 'ping';
  document.getElementById('mcPingConfig').classList.toggle('hidden', type !== 'ping');
  document.getElementById('mcTcpConfig').classList.toggle('hidden', type !== 'tcp');
  document.getElementById('mcHttpConfig').classList.toggle('hidden', type !== 'http');
  document.getElementById('mcAgentResourcesConfig').classList.toggle('hidden', type !== 'agent_resources');
  document.getElementById('mcServiceProcessConfig').classList.toggle('hidden', type !== 'service_process');
  document.getElementById('mcSnmpConfig').classList.toggle('hidden', type !== 'snmp');

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
  if (type === 'agent_resources') {
    return {
      cpu_warn: parseInt(document.getElementById('mcAgentCpuWarn').value) || 80,
      cpu_crit: parseInt(document.getElementById('mcAgentCpuCrit').value) || 95,
      memory_warn: parseInt(document.getElementById('mcAgentMemWarn').value) || 80,
      memory_crit: parseInt(document.getElementById('mcAgentMemCrit').value) || 95,
      disk_warn: parseInt(document.getElementById('mcAgentDiskWarn').value) || 85,
      disk_crit: parseInt(document.getElementById('mcAgentDiskCrit').value) || 95,
    };
  }
  if (type === 'service_process') {
    return {
      services: document.getElementById('mcServiceNames').value
        .split(',').map(s => s.trim()).filter(Boolean),
    };
  }
  if (type === 'snmp') {
    const cfg = {
      target: document.getElementById('mcSnmpTarget').value.trim(),
      port: parseInt(document.getElementById('mcSnmpPort').value) || 161,
      community: document.getElementById('mcSnmpCommunity').value.trim() || 'public',
      mode: document.getElementById('mcSnmpMode').value,
      oid: document.getElementById('mcSnmpOid').value.trim(),
      timeout: parseInt(document.getElementById('mcSnmpTimeout').value) || 5,
    };
    const expected = document.getElementById('mcSnmpExpected').value.trim();
    if (expected) cfg.expected_value = expected;
    const warn = document.getElementById('mcSnmpWarnThreshold').value.trim();
    if (warn) cfg.warning_threshold = parseFloat(warn);
    const crit = document.getElementById('mcSnmpCritThreshold').value.trim();
    if (crit) cfg.critical_threshold = parseFloat(crit);
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

// ── Alert Rules ────────────────────────────────────────────────────────────
function renderMonitorAlerts() {
  const container = document.getElementById('monitorAlertList');
  const empty = document.getElementById('monitorAlertEmpty');
  if (!container) return;
  container.innerHTML = '';

  const rules = state.monitorAlertRules || [];
  if (rules.length === 0) {
    if (empty) empty.classList.remove('hidden');
    return;
  }
  if (empty) empty.classList.add('hidden');

  const rows = rules.map(r => {
    const channelLabel = r.channel === 'webhook' ? 'Webhook' : 'E-Mail';
    const filterParts = [];
    if (r.matchSeverity) filterParts.push(`Severity: ${r.matchSeverity}`);
    if (r.matchServerId) {
      const srv = (state.servers || []).find(s => s.id === r.matchServerId);
      filterParts.push(`Server: ${srv ? srv.name : r.matchServerId.substring(0, 8)}`);
    }
    const filters = filterParts.length > 0 ? filterParts.join(', ') : 'Alle';

    return `<tr class="${r.enabled ? '' : 'disabled-row'}">
      <td><strong>${esc(r.name)}</strong></td>
      <td><span class="badge badge-${r.channel}">${channelLabel}</span></td>
      <td style="color:var(--text-soft)">${esc(filters)}</td>
      <td style="color:var(--text-soft)">${r.cooldownMinutes} Min.</td>
      <td style="white-space:nowrap">
        <button class="btn small" onclick="editAlertRule('${r.id}')">Bearbeiten</button>
        <button class="btn small ghost" onclick="toggleAlertRule('${r.id}')">
          ${r.enabled ? 'Deaktivieren' : 'Aktivieren'}
        </button>
        <button class="btn small ghost" onclick="deleteAlertRule('${r.id}')">L\u00f6schen</button>
      </td>
    </tr>`;
  }).join('');

  container.innerHTML = `<table class="data-table" style="margin:0">
    <thead><tr><th>Name</th><th>Kanal</th><th>Filter</th><th>Cooldown</th><th>Aktionen</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

// ── Alert Rule Modal ─────────────────────────────────────────────────────
document.getElementById('addAlertRuleBtn')?.addEventListener('click', () => openAlertRuleModal(null));

document.getElementById('arChannel')?.addEventListener('change', function() {
  document.getElementById('arWebhookConfig').classList.toggle('hidden', this.value !== 'webhook');
  document.getElementById('arEmailConfig').classList.toggle('hidden', this.value !== 'email');
});

function openAlertRuleModal(rule) {
  state.editingAlertRuleId = rule ? rule.id : null;
  document.getElementById('alertRuleModalTitle').textContent = rule ? 'Alert-Rule bearbeiten' : 'Neue Alert-Rule';

  // Server-Dropdown
  const serverSelect = document.getElementById('arMatchServerId');
  serverSelect.innerHTML = '<option value="">-- Alle Server --</option>' +
    (state.servers || []).map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');

  document.getElementById('arName').value = rule?.name || '';
  document.getElementById('arChannel').value = rule?.channel || 'webhook';
  document.getElementById('arMatchSeverity').value = rule?.matchSeverity || '';
  document.getElementById('arMatchServerId').value = rule?.matchServerId || '';
  document.getElementById('arCooldown').value = rule?.cooldownMinutes ?? 30;

  const cfg = rule?.channelConfig || {};
  document.getElementById('arWebhookUrl').value = cfg.url || '';
  document.getElementById('arEmailRecipients').value = (cfg.recipients || []).join(', ');

  const channel = rule?.channel || 'webhook';
  document.getElementById('arWebhookConfig').classList.toggle('hidden', channel !== 'webhook');
  document.getElementById('arEmailConfig').classList.toggle('hidden', channel !== 'email');

  showModal('alertRuleModal');
}

function _buildAlertChannelConfig() {
  const channel = document.getElementById('arChannel').value;
  if (channel === 'webhook') {
    return { url: document.getElementById('arWebhookUrl').value.trim() };
  }
  if (channel === 'email') {
    return {
      recipients: document.getElementById('arEmailRecipients').value
        .split(',').map(s => s.trim()).filter(Boolean),
    };
  }
  return {};
}

document.getElementById('alertRuleForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = {
    name: document.getElementById('arName').value.trim(),
    channel: document.getElementById('arChannel').value,
    match_severity: document.getElementById('arMatchSeverity').value || null,
    match_server_id: document.getElementById('arMatchServerId').value || null,
    cooldown_minutes: parseInt(document.getElementById('arCooldown').value) || 30,
    channel_config: _buildAlertChannelConfig(),
  };
  try {
    if (state.editingAlertRuleId) {
      await put(`/api/monitoring/alerts/${state.editingAlertRuleId}`, data);
      toast('Alert-Rule gespeichert');
    } else {
      await post('/api/monitoring/alerts', data);
      toast('Alert-Rule erstellt');
    }
    closeModal('alertRuleModal');
    await loadMonitoring();
  } catch (err) {
    toast(err.message, 'error');
  }
});

function editAlertRule(id) {
  const r = (state.monitorAlertRules || []).find(r => r.id === id);
  if (r) openAlertRuleModal(r);
}

async function toggleAlertRule(id) {
  try {
    await post(`/api/monitoring/alerts/${id}/toggle`);
    toast('Alert-Rule aktualisiert');
    await loadMonitoring();
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function deleteAlertRule(id) {
  if (!confirm('Alert-Rule wirklich loeschen?')) return;
  try {
    await del(`/api/monitoring/alerts/${id}`);
    toast('Alert-Rule geloescht');
    await loadMonitoring();
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ── Alert Log ────────────────────────────────────────────────────────────
async function loadAlertLog() {
  try {
    const logs = await get('/api/monitoring/alerts/log?limit=50');
    const container = document.getElementById('monitorAlertLogBody');
    if (!container) return;

    if (logs.length === 0) {
      container.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-soft)">Keine Alerts versendet</td></tr>';
      return;
    }

    container.innerHTML = logs.map(l => {
      const time = _formatTime(l.sentAt);
      const check = state.monitorChecks.find(c => c.id === l.checkId);
      const checkName = check ? check.name : l.checkId.substring(0, 8);
      return `<tr>
        <td style="font-size:12px;color:var(--text-soft)">${esc(time)}</td>
        <td>${esc(checkName)}</td>
        <td><span class="monitor-dot monitor-${l.oldStatus}"></span> ${esc(l.oldStatus)}</td>
        <td><span class="monitor-dot monitor-${l.newStatus}"></span> ${esc(l.newStatus)}</td>
        <td>${l.success ? '<span style="color:var(--green)">Gesendet</span>' : '<span style="color:var(--red)">Fehler</span>'}</td>
        <td style="font-size:12px;color:var(--text-soft)">${l.error ? esc(l.error) : '\u2013'}</td>
      </tr>`;
    }).join('');
  } catch (err) {
    toast(err.message, 'error');
  }
}
