/* Simple Remote Manager – Monitoring */
'use strict';

// ── Load ���─────────────────────────────────────────────────────────────────
async function loadMonitoring() {
  try {
    const [checks, alerts, templates] = await Promise.all([
      get('/api/monitoring/status'),
      get('/api/monitoring/alerts'),
      get('/api/monitoring/templates'),
    ]);
    state.monitorChecks = checks;
    state.monitorAlertRules = alerts;
    state.monitorTemplates = templates;
    renderMonitorOverview();
    renderMonitorChecks();
    renderMonitorAlerts();
    renderMonitorTemplates();
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
      <td><strong>${esc(c.name)}</strong>${c.templateId ? ' <span class="badge badge-tpl" title="Von Template verwaltet">TPL</span>' : ''}</td>
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
  document.getElementById('mcProxmoxBackupConfig').classList.toggle('hidden', this.value !== 'proxmox_backup');
  document.getElementById('mcZfsHealthConfig').classList.toggle('hidden', this.value !== 'zfs_health');
  document.getElementById('mcDockerHealthConfig').classList.toggle('hidden', this.value !== 'docker_health');
});

// Service-Modus umschalten
document.getElementById('mcServiceMode')?.addEventListener('change', function() {
  document.getElementById('mcServiceListFields').classList.toggle('hidden', this.value !== 'list');
  document.getElementById('mcServiceAutoFields').classList.toggle('hidden', this.value !== 'auto');
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
  const svcMode = cfg.mode || 'list';
  document.getElementById('mcServiceMode').value = svcMode;
  document.getElementById('mcServiceNames').value = (cfg.services || []).join(', ');
  document.getElementById('mcServiceIgnore').value = (cfg.ignore || []).join(', ');
  document.getElementById('mcServiceListFields').classList.toggle('hidden', svcMode !== 'list');
  document.getElementById('mcServiceAutoFields').classList.toggle('hidden', svcMode !== 'auto');

  // Proxmox Backup Config
  document.getElementById('mcPveBackupMaxAge').value = cfg.max_backup_age_hours ?? 26;
  document.getElementById('mcPveBackupExclude').value = (cfg.exclude_vmids || []).join(', ');
  document.getElementById('mcPveBackupExcludeStopped').value = (cfg.exclude_stopped !== false) ? 'true' : 'false';

  // ZFS Health Config
  document.getElementById('mcZfsCapWarn').value = cfg.capacity_warn ?? 80;
  document.getElementById('mcZfsCapCrit').value = cfg.capacity_crit ?? 90;

  // Docker Health Config
  document.getElementById('mcDockerIgnore').value = (cfg.ignore_containers || []).join(', ');

  // Config-Sections umschalten
  const type = check?.checkType || 'ping';
  document.getElementById('mcPingConfig').classList.toggle('hidden', type !== 'ping');
  document.getElementById('mcTcpConfig').classList.toggle('hidden', type !== 'tcp');
  document.getElementById('mcHttpConfig').classList.toggle('hidden', type !== 'http');
  document.getElementById('mcAgentResourcesConfig').classList.toggle('hidden', type !== 'agent_resources');
  document.getElementById('mcServiceProcessConfig').classList.toggle('hidden', type !== 'service_process');
  document.getElementById('mcProxmoxBackupConfig').classList.toggle('hidden', type !== 'proxmox_backup');
  document.getElementById('mcZfsHealthConfig').classList.toggle('hidden', type !== 'zfs_health');
  document.getElementById('mcDockerHealthConfig').classList.toggle('hidden', type !== 'docker_health');

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
    const mode = document.getElementById('mcServiceMode').value;
    if (mode === 'auto') {
      return {
        mode: 'auto',
        ignore: document.getElementById('mcServiceIgnore').value
          .split(',').map(s => s.trim()).filter(Boolean),
      };
    }
    return {
      mode: 'list',
      services: document.getElementById('mcServiceNames').value
        .split(',').map(s => s.trim()).filter(Boolean),
    };
  }
  if (type === 'proxmox_backup') {
    return {
      max_backup_age_hours: parseInt(document.getElementById('mcPveBackupMaxAge').value) || 26,
      exclude_vmids: document.getElementById('mcPveBackupExclude').value
        .split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n)),
      exclude_stopped: document.getElementById('mcPveBackupExcludeStopped').value === 'true',
    };
  }
  if (type === 'zfs_health') {
    return {
      capacity_warn: parseInt(document.getElementById('mcZfsCapWarn').value) || 80,
      capacity_crit: parseInt(document.getElementById('mcZfsCapCrit').value) || 90,
    };
  }
  if (type === 'docker_health') {
    return {
      ignore_containers: document.getElementById('mcDockerIgnore').value
        .split(',').map(s => s.trim()).filter(Boolean),
    };
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

// ── Templates ────────────────────────────────────────────────────────────
function renderMonitorTemplates() {
  const container = document.getElementById('monitorTemplateList');
  const empty = document.getElementById('monitorTemplateEmpty');
  if (!container) return;
  container.innerHTML = '';

  const templates = state.monitorTemplates || [];
  if (templates.length === 0) {
    if (empty) empty.classList.remove('hidden');
    return;
  }
  if (empty) empty.classList.add('hidden');

  const rows = templates.map(t => {
    const checkCount = (t.checkDefinitions || []).length;
    const alertCount = (t.alertDefinitions || []).length;
    const serverCount = (t.assignments || []).length;
    const serverNames = (t.assignments || []).map(a => a.serverName).join(', ') || '\u2013';

    return `<tr>
      <td><strong>${esc(t.name)}</strong></td>
      <td style="color:var(--text-soft)">${esc(t.description || '')}</td>
      <td>${checkCount} Checks, ${alertCount} Alerts</td>
      <td style="color:var(--text-soft);font-size:12px" title="${esc(serverNames)}">${serverCount} Server</td>
      <td style="white-space:nowrap">
        <button class="btn small" onclick="editTemplate('${t.id}')">Bearbeiten</button>
        <button class="btn small ghost" onclick="deleteTemplate('${t.id}')">L\u00f6schen</button>
      </td>
    </tr>`;
  }).join('');

  container.innerHTML = `<table class="data-table" style="margin:0">
    <thead><tr><th>Name</th><th>Beschreibung</th><th>Inhalt</th><th>Server</th><th>Aktionen</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

// ── Template Modal ───────────────────────────────────────────────────────
document.getElementById('addTemplateBtn')?.addEventListener('click', () => openTemplateModal(null));

function openTemplateModal(template) {
  state.editingTemplateId = template ? template.id : null;
  document.getElementById('templateModalTitle').textContent = template ? 'Template bearbeiten' : 'Neues Template';

  document.getElementById('tplName').value = template?.name || '';
  document.getElementById('tplDescription').value = template?.description || '';

  state.templateCheckDefs = (template?.checkDefinitions || []).map(d => ({...d}));
  state.templateAlertDefs = (template?.alertDefinitions || []).map(d => ({...d}));

  _renderTemplateCheckDefs();
  _renderTemplateAlertDefs();
  showModal('monitorTemplateModal');
}

function _renderTemplateCheckDefs() {
  const container = document.getElementById('tplCheckDefs');
  if (!container) return;

  if (state.templateCheckDefs.length === 0) {
    container.innerHTML = '<div style="color:var(--text-soft);font-size:13px;padding:8px 0">Keine Checks definiert</div>';
    return;
  }

  container.innerHTML = state.templateCheckDefs.map((def, i) => {
    const typeBadge = def.check_type ? def.check_type.toUpperCase() : 'PING';
    const cfg = def.config || {};
    return `<div class="tpl-def-row" style="margin-bottom:8px;padding:8px 10px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px">
      <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">
        <span class="badge badge-${def.check_type || 'ping'}" style="flex-shrink:0;font-size:10px">${esc(typeBadge)}</span>
        <input value="${esc(def.name || '')}" onchange="state.templateCheckDefs[${i}].name=this.value" style="flex:1;min-width:120px" placeholder="Name ({{server_name}})" />
        <select onchange="state.templateCheckDefs[${i}].check_type=this.value;state.templateCheckDefs[${i}].config=_tplCheckDefaults(this.value);_renderTemplateCheckDefs()" style="width:110px">
          ${['ping','tcp','http','agent_ping','agent_resources','service_process','proxmox_backup','zfs_health','docker_health']
            .map(t => `<option value="${t}" ${def.check_type===t?'selected':''}>${t}</option>`).join('')}
        </select>
        <select onchange="state.templateCheckDefs[${i}].interval=this.value" style="width:65px">
          ${['1m','5m','15m','30m','1h','6h','12h','24h']
            .map(v => `<option value="${v}" ${def.interval===v?'selected':''}>${v}</option>`).join('')}
        </select>
        <select onchange="state.templateCheckDefs[${i}].severity=this.value" style="width:80px">
          ${['critical','warning','info']
            .map(v => `<option value="${v}" ${def.severity===v?'selected':''}>${v}</option>`).join('')}
        </select>
        <button type="button" class="btn small ghost" onclick="removeTemplateCheckDef(${i})" title="Entfernen">&#x2715;</button>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;font-size:13px">
        ${_tplCheckConfigFields(def.check_type, cfg, i)}
      </div>
    </div>`;
  }).join('');
}

function _tplCheckDefaults(type) {
  const h = '{{hostname}}';
  switch (type) {
    case 'ping':           return { target: h, timeout: 5 };
    case 'tcp':            return { target: h, port: 22, timeout: 5 };
    case 'http':           return { url: 'http://{{hostname}}', method: 'GET', expected_status: 200, timeout: 10, verify_ssl: true };
    case 'agent_ping':      return { server_id: '{{server_id}}', stale_minutes: 5 };
    case 'agent_resources': return { cpu_warn: 80, cpu_crit: 95, memory_warn: 80, memory_crit: 95 };
    case 'service_process': return { mode: 'auto', ignore: [] };
    case 'proxmox_backup':  return { max_backup_age_hours: 26, exclude_vmids: [], exclude_stopped: true };
    case 'zfs_health':      return { capacity_warn: 80, capacity_crit: 90 };
    case 'docker_health':   return { ignore_containers: [] };
    default:                return {};
  }
}

function _tplCfgInput(idx, key, val, placeholder, opts) {
  const w = opts?.width || '120px';
  const type = opts?.type || 'text';
  return `<label style="display:flex;flex-direction:column;gap:2px;color:var(--text-soft)">
    <span style="font-size:11px">${esc(placeholder)}</span>
    <input value="${esc(val ?? '')}" ${type==='number'?'type="number"':''} style="width:${w};font-size:12px"
      onchange="state.templateCheckDefs[${idx}].config.${key}=${type==='number'?'Number(this.value)||0':'this.value'}" />
  </label>`;
}

function _tplCfgSelect(idx, key, val, label, options) {
  const opts = options.map(o => {
    const v = typeof o === 'string' ? o : o.value;
    const l = typeof o === 'string' ? o : o.label;
    return `<option value="${v}" ${val===v?'selected':''}>${esc(l)}</option>`;
  }).join('');
  return `<label style="display:flex;flex-direction:column;gap:2px;color:var(--text-soft)">
    <span style="font-size:11px">${esc(label)}</span>
    <select style="width:auto;font-size:12px" onchange="state.templateCheckDefs[${idx}].config.${key}=this.value">${opts}</select>
  </label>`;
}

function _tplCheckConfigFields(type, cfg, idx) {
  const inp = (key, val, ph, o) => _tplCfgInput(idx, key, val, ph, o);
  const sel = (key, val, ph, o) => _tplCfgSelect(idx, key, val, ph, o);

  switch (type) {
    case 'ping':
      return inp('target', cfg.target, 'Ziel', {width:'160px'})
        + inp('timeout', cfg.timeout, 'Timeout (s)', {width:'70px', type:'number'});

    case 'tcp':
      return inp('target', cfg.target, 'Ziel', {width:'160px'})
        + inp('port', cfg.port, 'Port', {width:'70px', type:'number'})
        + inp('timeout', cfg.timeout, 'Timeout (s)', {width:'70px', type:'number'});

    case 'http':
      return inp('url', cfg.url, 'URL', {width:'220px'})
        + sel('method', cfg.method, 'Methode', ['GET','POST','PUT','HEAD'])
        + inp('expected_status', cfg.expected_status, 'Status', {width:'60px', type:'number'})
        + inp('timeout', cfg.timeout, 'Timeout (s)', {width:'70px', type:'number'})
        + `<label style="display:flex;flex-direction:column;gap:2px;color:var(--text-soft)">
            <span style="font-size:11px">SSL pruefen</span>
            <select style="width:auto;font-size:12px" onchange="state.templateCheckDefs[${idx}].config.verify_ssl=this.value==='true'">
              <option value="true" ${(cfg.verify_ssl??true)?'selected':''}>Ja</option>
              <option value="false" ${!(cfg.verify_ssl??true)?'selected':''}>Nein</option>
            </select>
          </label>`
        + inp('search_string', cfg.search_string, 'Suchtext', {width:'120px'});

    case 'agent_ping':
      return inp('server_id', cfg.server_id, 'Server-ID ({{server_id}})', {width:'220px'})
        + inp('stale_minutes', cfg.stale_minutes, 'Timeout (Min.)', {width:'80px', type:'number'});

    case 'agent_resources':
      return inp('cpu_warn', cfg.cpu_warn, 'CPU Warn %', {width:'70px', type:'number'})
        + inp('cpu_crit', cfg.cpu_crit, 'CPU Crit %', {width:'70px', type:'number'})
        + inp('memory_warn', cfg.memory_warn, 'RAM Warn %', {width:'70px', type:'number'})
        + inp('memory_crit', cfg.memory_crit, 'RAM Crit %', {width:'70px', type:'number'});

    case 'service_process':
      return sel('mode', cfg.mode || 'auto', 'Modus', [{value:'auto',label:'Auto'},{value:'list',label:'Liste'}])
        + (cfg.mode === 'list'
          ? inp('services', (cfg.services||[]).join(', '), 'Services', {width:'200px'})
          : inp('ignore', (cfg.ignore||[]).join(', '), 'Ignorieren', {width:'200px'}));

    case 'proxmox_backup':
      return inp('max_backup_age_hours', cfg.max_backup_age_hours, 'Max. Alter (h)', {width:'80px', type:'number'})
        + inp('exclude_vmids', (cfg.exclude_vmids||[]).join(', '), 'VMIDs ausschl.', {width:'120px'})
        + sel('exclude_stopped', String(cfg.exclude_stopped ?? true), 'Gestoppte ign.', [{value:'true',label:'Ja'},{value:'false',label:'Nein'}]);

    case 'zfs_health':
      return inp('capacity_warn', cfg.capacity_warn, 'Kap. Warn %', {width:'80px', type:'number'})
        + inp('capacity_crit', cfg.capacity_crit, 'Kap. Crit %', {width:'80px', type:'number'});

    case 'docker_health':
      return inp('ignore_containers', (cfg.ignore_containers||[]).join(', '), 'Ignorieren', {width:'200px'});

    default:
      return `<span style="color:var(--text-soft);font-size:12px">Keine Config-Felder</span>`;
  }
}

function addTemplateCheckDef() {
  state.templateCheckDefs.push({
    def_id: crypto.randomUUID(),
    name: 'Ping {{server_name}}',
    check_type: 'ping',
    config: { target: '{{hostname}}', timeout: 5 },
    interval: '5m',
    severity: 'critical',
    consecutive_fails: 3,
  });
  _renderTemplateCheckDefs();
}

function removeTemplateCheckDef(index) {
  state.templateCheckDefs.splice(index, 1);
  _renderTemplateCheckDefs();
}


function _renderTemplateAlertDefs() {
  const container = document.getElementById('tplAlertDefs');
  if (!container) return;

  if (state.templateAlertDefs.length === 0) {
    container.innerHTML = '<div style="color:var(--text-soft);font-size:13px;padding:8px 0">Keine Alerts definiert</div>';
    return;
  }

  container.innerHTML = state.templateAlertDefs.map((def, i) => {
    const channelLabel = def.channel === 'email' ? 'E-Mail' : 'Webhook';
    const cc = def.channel_config || {};
    const channelFields = def.channel === 'email'
      ? `<label style="display:flex;flex-direction:column;gap:2px;color:var(--text-soft);flex:1">
           <span style="font-size:11px">Empfaenger</span>
           <input value="${esc(cc.to || '')}" style="font-size:12px" placeholder="admin@example.com"
             onchange="state.templateAlertDefs[${i}].channel_config.to=this.value" />
         </label>
         <label style="display:flex;flex-direction:column;gap:2px;color:var(--text-soft)">
           <span style="font-size:11px">SMTP Host</span>
           <input value="${esc(cc.smtp_host || '')}" style="width:130px;font-size:12px" placeholder="smtp.example.com"
             onchange="state.templateAlertDefs[${i}].channel_config.smtp_host=this.value" />
         </label>
         <label style="display:flex;flex-direction:column;gap:2px;color:var(--text-soft)">
           <span style="font-size:11px">Port</span>
           <input value="${cc.smtp_port || 587}" type="number" style="width:60px;font-size:12px"
             onchange="state.templateAlertDefs[${i}].channel_config.smtp_port=Number(this.value)||587" />
         </label>`
      : `<label style="display:flex;flex-direction:column;gap:2px;color:var(--text-soft);flex:1">
           <span style="font-size:11px">Webhook URL</span>
           <input value="${esc(cc.url || '')}" style="font-size:12px" placeholder="https://hooks.example.com/alert"
             onchange="state.templateAlertDefs[${i}].channel_config.url=this.value" />
         </label>`;
    return `<div class="tpl-def-row" style="margin-bottom:8px;padding:8px 10px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px">
      <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">
        <span class="badge badge-${def.channel || 'webhook'}" style="flex-shrink:0;font-size:10px">${esc(channelLabel)}</span>
        <input value="${esc(def.name || '')}" onchange="state.templateAlertDefs[${i}].name=this.value" style="flex:1;min-width:120px" placeholder="Name" />
        <select onchange="state.templateAlertDefs[${i}].channel=this.value;state.templateAlertDefs[${i}].channel_config={};_renderTemplateAlertDefs()" style="width:90px">
          <option value="webhook" ${def.channel==='webhook'?'selected':''}>Webhook</option>
          <option value="email" ${def.channel==='email'?'selected':''}>E-Mail</option>
        </select>
        <select onchange="state.templateAlertDefs[${i}].match_severity=this.value||null" style="width:80px">
          <option value="" ${!def.match_severity?'selected':''}>Alle</option>
          <option value="critical" ${def.match_severity==='critical'?'selected':''}>Critical</option>
          <option value="warning" ${def.match_severity==='warning'?'selected':''}>Warning</option>
        </select>
        <label style="display:flex;flex-direction:column;gap:2px;color:var(--text-soft)">
          <span style="font-size:11px">Cooldown</span>
          <input value="${def.cooldown_minutes||30}" onchange="state.templateAlertDefs[${i}].cooldown_minutes=parseInt(this.value)||30" style="width:50px;font-size:12px" type="number" />
        </label>
        <button type="button" class="btn small ghost" onclick="removeTemplateAlertDef(${i})" title="Entfernen">&#x2715;</button>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;font-size:13px">
        ${channelFields}
      </div>
    </div>`;
  }).join('');
}

function addTemplateAlertDef() {
  state.templateAlertDefs.push({
    def_id: crypto.randomUUID(),
    name: 'Alert {{server_name}}',
    channel: 'webhook',
    channel_config: { url: '' },
    match_severity: 'critical',
    cooldown_minutes: 30,
    enabled: true,
  });
  _renderTemplateAlertDefs();
}

function removeTemplateAlertDef(index) {
  state.templateAlertDefs.splice(index, 1);
  _renderTemplateAlertDefs();
}


document.getElementById('templateForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = {
    name: document.getElementById('tplName').value.trim(),
    description: document.getElementById('tplDescription').value.trim() || null,
    check_definitions: state.templateCheckDefs,
    alert_definitions: state.templateAlertDefs,
  };
  try {
    if (state.editingTemplateId) {
      const result = await put(`/api/monitoring/templates/${state.editingTemplateId}`, data);
      const sync = result.syncResult;
      toast(`Template gespeichert — ${sync.created} erstellt, ${sync.updated} aktualisiert, ${sync.deleted} geloescht (${sync.servers} Server)`);
    } else {
      await post('/api/monitoring/templates', data);
      toast('Template erstellt');
    }
    closeModal('monitorTemplateModal');
    await loadMonitoring();
  } catch (err) {
    toast(err.message, 'error');
  }
});

function editTemplate(id) {
  const t = (state.monitorTemplates || []).find(t => t.id === id);
  if (t) openTemplateModal(t);
}

async function deleteTemplate(id) {
  const t = (state.monitorTemplates || []).find(t => t.id === id);
  const serverCount = (t?.assignments || []).length;
  const msg = serverCount > 0
    ? `Template "${t.name}" wirklich loeschen? Alle Checks bei ${serverCount} Server(n) werden geloescht!`
    : `Template "${t?.name}" wirklich loeschen?`;
  if (!confirm(msg)) return;
  try {
    await del(`/api/monitoring/templates/${id}`);
    toast('Template geloescht');
    await loadMonitoring();
  } catch (err) {
    toast(err.message, 'error');
  }
}
