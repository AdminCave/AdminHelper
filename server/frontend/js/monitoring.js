/* Simple Remote Manager – Monitoring */
'use strict';

// ── Load ���─────────────────────────────────────────────────────────────────
// ── Tab-Switching ────────────────────────────────────────────────────────
document.querySelectorAll('.monitor-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.monitor-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.monitor-tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    const target = document.querySelector(`.monitor-tab-content[data-mtab="${tab.dataset.mtab}"]`);
    if (target) target.classList.add('active');
    if (tab.dataset.mtab === 'log') loadAlertLog();
  });
});

// ── Filter ───────────────────────────────────────────────────────────────
['monitorServerFilter', 'monitorTypeFilter', 'monitorStatusFilter', 'monitorTagFilter'].forEach(id => {
  document.getElementById(id)?.addEventListener('change', function() {
    state[id] = this.value;
    _applyMonitorFilters();
  });
});
document.getElementById('monitorSearch')?.addEventListener('input', function() {
  state.monitorSearch = this.value;
  _applyMonitorFilters();
});

function _applyMonitorFilters() {
  const filtered = _filterChecks();
  renderMonitorOverview(filtered);
  renderMonitorChecks(filtered);
}

function _filterChecks() {
  let checks = state.monitorChecks;
  const serverMap = {};
  (state.servers || []).forEach(s => { serverMap[s.id] = s; });

  if (state.monitorServerFilter) {
    checks = checks.filter(c => c.serverId === state.monitorServerFilter);
  }
  if (state.monitorTypeFilter) {
    checks = checks.filter(c => c.checkType === state.monitorTypeFilter);
  }
  if (state.monitorStatusFilter) {
    checks = checks.filter(c => (c.state?.status || 'pending') === state.monitorStatusFilter);
  }
  if (state.monitorTagFilter) {
    const tag = state.monitorTagFilter;
    checks = checks.filter(c => {
      const srv = serverMap[c.serverId];
      return srv && (srv.tags || []).includes(tag);
    });
  }
  if (state.monitorSearch) {
    const q = state.monitorSearch.toLowerCase();
    checks = checks.filter(c => {
      const srvName = serverMap[c.serverId]?.name || '';
      return c.name.toLowerCase().includes(q)
        || (c.state?.message || '').toLowerCase().includes(q)
        || srvName.toLowerCase().includes(q);
    });
  }
  return checks;
}

function _populateMonitorFilters() {
  const checks = state.monitorChecks;
  const serverMap = {};
  (state.servers || []).forEach(s => { serverMap[s.id] = s; });

  // Server-Filter
  const serverIds = [...new Set(checks.map(c => c.serverId).filter(Boolean))];
  const serverSelect = document.getElementById('monitorServerFilter');
  const prevServer = state.monitorServerFilter;
  serverSelect.innerHTML = '<option value="">Alle Server</option>' +
    serverIds.map(id => {
      const name = serverMap[id]?.name || id.substring(0, 8);
      return `<option value="${id}" ${id === prevServer ? 'selected' : ''}>${esc(name)}</option>`;
    }).join('');

  // Typ-Filter
  const types = [...new Set(checks.map(c => c.checkType))].sort();
  const typeSelect = document.getElementById('monitorTypeFilter');
  const prevType = state.monitorTypeFilter;
  typeSelect.innerHTML = '<option value="">Alle Typen</option>' +
    types.map(t => `<option value="${t}" ${t === prevType ? 'selected' : ''}>${t}</option>`).join('');

  // Tag-Filter
  const tagSet = new Set();
  serverIds.forEach(id => {
    (serverMap[id]?.tags || []).forEach(t => tagSet.add(t));
  });
  const tags = [...tagSet].sort();
  const tagSelect = document.getElementById('monitorTagFilter');
  const prevTag = state.monitorTagFilter;
  tagSelect.innerHTML = '<option value="">Alle Tags</option>' +
    tags.map(t => `<option value="${t}" ${t === prevTag ? 'selected' : ''}>${esc(t)}</option>`).join('');

  // Status-Filter und Suche behalten ihren Wert
  document.getElementById('monitorStatusFilter').value = state.monitorStatusFilter;
  document.getElementById('monitorSearch').value = state.monitorSearch;
}

// ── Load ─────────────────────────────────────────────────────────────────
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
    _populateMonitorFilters();
    const filtered = _filterChecks();
    renderMonitorOverview(filtered);
    renderMonitorChecks(filtered);
    renderMonitorAlerts();
    renderMonitorTemplates();
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ── Overview Cards ────────────────────────────────────────────────────────
function renderMonitorOverview(checks) {
  const container = document.getElementById('monitorOverview');
  if (!checks) checks = state.monitorChecks;
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
function renderMonitorChecks(checks) {
  const container = document.getElementById('monitorCheckList');
  const empty = document.getElementById('monitorEmpty');
  container.innerHTML = '';

  if (!checks) checks = state.monitorChecks;
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
    return `<tr class="check-row" data-check-id="${c.id}" onclick="toggleCheckDetail('${c.id}', this)" style="cursor:pointer">
      <td><span class="monitor-dot monitor-${st}"></span></td>
      <td><span class="badge badge-${c.checkType}">${esc(typeBadge)}</span></td>
      <td><strong>${esc(c.name)}</strong>${c.templateId ? ' <span class="badge badge-tpl" title="Von Template verwaltet">TPL</span>' : ''}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-soft)">${esc(msg)}</td>
      <td style="color:var(--text-soft);font-size:12px">${esc(lastCheck)}</td>
      <td style="white-space:nowrap" onclick="event.stopPropagation()">
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

// ── Check Detail Panel ────────────────────────────────────────────────────
let _openDetailCheckId = null;
let _detailChart = null;

function toggleCheckDetail(checkId, trEl) {
  const existing = trEl.nextElementSibling;
  if (existing && existing.classList.contains('check-detail-row')) {
    existing.remove();
    if (_detailChart) { _detailChart.destroy(); _detailChart = null; }
    _openDetailCheckId = null;
    return;
  }
  // Andere offene Detail-Rows schliessen
  document.querySelectorAll('.check-detail-row').forEach(r => r.remove());
  if (_detailChart) { _detailChart.destroy(); _detailChart = null; }

  const check = state.monitorChecks.find(c => c.id === checkId);
  if (!check) return;
  _openDetailCheckId = checkId;

  const detailTr = document.createElement('tr');
  detailTr.className = 'check-detail-row';
  const td = document.createElement('td');
  td.setAttribute('colspan', '6');
  td.innerHTML = _buildDetailPanel(check);
  detailTr.appendChild(td);
  trEl.after(detailTr);

  if (check.checkType === 'agent_resources') {
    _initGaugeClickHandlers(check);
  }
  if (!_NO_CHART_TYPES.includes(check.checkType)) {
    _loadDetailMetrics(checkId, '1h', check);
  }
}

const _NO_CHART_TYPES = ['service_process', 'docker_health', 'proxmox_backup', 'agent_resources'];

function _buildDetailPanel(check) {
  const configKv = _formatCheckConfigWeb(check);
  let configHtml = '';
  if (configKv.length > 0) {
    configHtml = '<div class="check-detail-config"><strong>Konfiguration</strong><div class="check-cfg-grid">' +
      configKv.map(([k, v]) => `<span class="check-cfg-key">${esc(k)}:</span><span class="check-cfg-val">${esc(String(v))}</span>`).join('') +
      '</div></div>';
  }

  const typeContentHtml = _renderTypeContentHtml(check);
  const hasChart = !_NO_CHART_TYPES.includes(check.checkType);

  const chartHtml = hasChart ? `
      <div class="check-detail-current" id="checkDetailCurrent_${check.id}"></div>
      <div class="check-detail-periods">
        <button class="btn small active" onclick="_switchDetailPeriod('${check.id}', '1h', this)">1h</button>
        <button class="btn small" onclick="_switchDetailPeriod('${check.id}', '6h', this)">6h</button>
        <button class="btn small" onclick="_switchDetailPeriod('${check.id}', '24h', this)">24h</button>
        <button class="btn small" onclick="_switchDetailPeriod('${check.id}', '7d', this)">7d</button>
      </div>
      <div class="check-detail-chart" id="checkDetailChart_${check.id}"></div>
      <div class="check-detail-timeline" id="checkDetailTimeline_${check.id}"></div>
  ` : '';

  return `
    <div class="check-detail-panel">
      ${configHtml}
      ${typeContentHtml}
      ${chartHtml}
    </div>`;
}

// ── Type-Specific Renderers (Web) ──────────────────────────────────

function _renderTypeContentHtml(check) {
  const details = check.state?.details;
  switch (check.checkType) {
    case 'agent_resources': return _renderResourceGaugesHtml(details, check.config, check.id);
    case 'service_process': return _renderServiceListHtml(details);
    case 'docker_health': return _renderContainerListHtml(details);
    case 'proxmox_backup': return _renderBackupListHtml(details);
    case 'zfs_health': return _renderZfsGaugesHtml(details);
    case 'agent_ping': return _renderAgentPingHtml(check);
    default: return '';
  }
}

function _gaugeClass(pct, warn, crit) {
  if (pct >= crit) return 'gauge-crit';
  if (pct >= warn) return 'gauge-warn';
  return 'gauge-ok';
}

function _gaugeItemHtml(label, pct, detailText, cls, metricName) {
  const clickable = metricName ? ' mon-gauge-clickable' : '';
  const dataAttr = metricName ? ` data-metric="${esc(metricName)}"` : '';
  return `<div class="mon-gauge-item${clickable}"${dataAttr}>
    <span class="mon-gauge-label">${esc(label)}</span>
    <div class="mon-gauge-bar">
      <div class="mon-gauge-fill ${cls}" style="width:${Math.min(pct, 100)}%"></div>
      <span class="mon-gauge-text">${pct.toFixed(1)}%</span>
    </div>
    ${detailText ? `<span class="mon-gauge-detail">${esc(detailText)}</span>` : ''}
  </div>`;
}

function _itemRowHtml(name, category, statusText) {
  const catCls = category === 'critical' ? 'item-crit' : category === 'warn' ? 'item-warn' : 'item-ok';
  return `<div class="mon-item-row">
    <span class="mon-item-dot ${catCls}"></span>
    <span class="mon-item-name">${esc(name)}</span>
    <span class="mon-item-status">${esc(statusText)}</span>
  </div>`;
}

function _renderResourceGaugesHtml(details, config, checkId) {
  if (!details) return '';
  const cpuWarn = config?.cpu_warn || 80, cpuCrit = config?.cpu_crit || 95;
  const memWarn = config?.memory_warn || 80, memCrit = config?.memory_crit || 95;
  const diskWarn = config?.disk_warn || 85, diskCrit = config?.disk_crit || 95;
  let html = `<div class="mon-gauge-grid" id="gaugeGrid_${checkId}">`;
  if (details.cpu != null) {
    html += _gaugeItemHtml('CPU', details.cpu, null, _gaugeClass(details.cpu, cpuWarn, cpuCrit), 'monitor_agent_cpu_percent');
  }
  if (details.memory != null) {
    const memDetail = details.memory_total_mb ? `${details.memory_used_mb || 0} / ${details.memory_total_mb} MB` : null;
    html += _gaugeItemHtml('RAM', details.memory, memDetail, _gaugeClass(details.memory, memWarn, memCrit), 'monitor_agent_memory_percent');
  }
  for (const disk of details.disks || []) {
    const diskDetail = disk.total_gb != null ? `${(disk.used_gb || 0).toFixed(1)} / ${disk.total_gb.toFixed(1)} GB` : null;
    html += _gaugeItemHtml(disk.mount, disk.percent, diskDetail, _gaugeClass(disk.percent, diskWarn, diskCrit), 'monitor_agent_disk_percent');
  }
  html += '</div>';
  html += `<div class="mon-gauge-chart-area hidden" id="gaugeChartArea_${checkId}"></div>`;
  return html;
}

function _renderServiceListHtml(details) {
  if (!details) return '';
  if (details.mode === 'auto') {
    const failed = details.failed || [];
    const inactive = details.enabled_inactive || [];
    if (failed.length === 0 && inactive.length === 0) {
      return '<div class="mon-all-ok"><span class="mon-item-dot item-ok"></span> Alle systemd-Units OK</div>';
    }
    let html = '<div class="mon-item-list">';
    if (failed.length > 0) {
      html += '<div class="mon-section-title">Failed</div>';
      for (const svc of failed) html += _itemRowHtml(svc, 'critical', 'failed');
    }
    if (inactive.length > 0) {
      html += '<div class="mon-section-title">Inaktiv (Autostart)</div>';
      for (const svc of inactive) html += _itemRowHtml(svc, 'warn', 'inactive');
    }
    html += '</div>';
    return html;
  }
  // list mode
  const watched = details.watched || [];
  if (watched.length === 0) return '';
  const allOk = watched.every(s => s.running);
  if (allOk) return `<div class="mon-all-ok"><span class="mon-item-dot item-ok"></span> Alle ${watched.length} Services aktiv</div>`;
  let html = '<div class="mon-item-list">';
  for (const svc of watched) {
    html += _itemRowHtml(svc.name, svc.running ? 'ok' : 'critical', svc.running ? 'running' : 'down');
  }
  html += '</div>';
  return html;
}

function _renderContainerListHtml(details) {
  if (!details?.containers?.length) return '';
  const allOk = details.containers.every(c => c.category === 'ok');
  if (allOk) return `<div class="mon-all-ok"><span class="mon-item-dot item-ok"></span> Alle ${details.containers.length} Container laufen</div>`;
  const sorted = [...details.containers].sort((a, b) => {
    const order = { critical: 0, warning: 1, ok: 2 };
    return (order[a.category] ?? 2) - (order[b.category] ?? 2);
  });
  let html = '<div class="mon-item-list">';
  for (const c of sorted) {
    const catMap = { critical: 'critical', warning: 'warn', ok: 'ok' };
    const imgBadge = c.image ? `<span class="mon-item-badge">${esc(c.image.split(':')[0].split('/').pop())}</span>` : '';
    html += `<div class="mon-item-row">
      <span class="mon-item-dot ${catMap[c.category] === 'critical' ? 'item-crit' : catMap[c.category] === 'warn' ? 'item-warn' : 'item-ok'}"></span>
      <span class="mon-item-name">${esc(c.name)}</span>
      ${imgBadge}
      <span class="mon-item-status">${esc(c.state)}</span>
    </div>`;
  }
  html += '</div>';
  return html;
}

function _renderBackupListHtml(details) {
  if (!details?.vms?.length) return '';
  const allOk = details.vms.every(v => v.backupStatus === 'ok');
  if (allOk) return `<div class="mon-all-ok"><span class="mon-item-dot item-ok"></span> Alle ${details.vms.length} VMs/CTs haben aktuelle Backups</div>`;
  const sorted = [...details.vms].sort((a, b) => {
    const order = { missing: 0, outdated: 1, ok: 2 };
    return (order[a.backupStatus] ?? 2) - (order[b.backupStatus] ?? 2);
  });
  let html = '<div class="mon-item-list">';
  for (const vm of sorted) {
    const catMap = { ok: 'ok', outdated: 'warn', missing: 'critical' };
    const cat = catMap[vm.backupStatus] || 'ok';
    const statusText = vm.backupStatus === 'ok' ? 'OK' : vm.backupStatus === 'missing' ? 'Kein Backup' : `Veraltet (${vm.ageHours}h)`;
    html += `<div class="mon-item-row">
      <span class="mon-item-dot ${cat === 'critical' ? 'item-crit' : cat === 'warn' ? 'item-warn' : 'item-ok'}"></span>
      <span class="mon-item-badge">${esc((vm.type || 'vm').toUpperCase())}</span>
      <span class="mon-item-name">${esc(vm.name)} (${vm.vmid})</span>
      <span class="mon-item-status">${esc(statusText)}</span>
    </div>`;
  }
  html += '</div>';
  return html;
}

function _renderZfsGaugesHtml(details) {
  if (!details?.pools?.length) return '';
  let html = '<div class="mon-gauge-grid">';
  for (const pool of details.pools) {
    const healthCls = pool.health === 'ONLINE' ? 'health-online' : pool.health === 'DEGRADED' ? 'health-degraded' : 'health-faulted';
    html += `<div class="mon-gauge-item">
      <span class="mon-gauge-label">${esc(pool.name)}</span>
      <div class="mon-gauge-bar">
        <div class="mon-gauge-fill ${_gaugeClass(pool.capacityPercent, 80, 90)}" style="width:${Math.min(pool.capacityPercent, 100)}%"></div>
        <span class="mon-gauge-text">${pool.capacityPercent}%</span>
      </div>
      <span class="mon-health-badge ${healthCls}">${esc(pool.health)}</span>
    </div>`;
  }
  html += '</div>';
  return html;
}

function _renderAgentPingHtml(check) {
  const msg = check.state?.message || '';
  const match = msg.match(/(\d+)/);
  const seconds = match ? parseInt(match[1], 10) : null;
  if (seconds == null) return '';
  const display = seconds < 120 ? `${seconds}s` : `${Math.round(seconds / 60)}m`;
  return `<div class="mon-last-seen"><span class="mon-last-seen-value">${display}</span><span class="mon-last-seen-unit">seit letztem Report</span></div>`;
}

let _gaugeActiveMetric = null;

function _initGaugeClickHandlers(check) {
  const grid = document.getElementById(`gaugeGrid_${check.id}`);
  const chartArea = document.getElementById(`gaugeChartArea_${check.id}`);
  if (!grid || !chartArea) return;

  _gaugeActiveMetric = null;

  grid.addEventListener('click', (e) => {
    const gaugeItem = e.target.closest('.mon-gauge-clickable');
    if (!gaugeItem) return;
    const metric = gaugeItem.dataset.metric;
    const diskMount = gaugeItem.querySelector('.mon-gauge-label')?.textContent;
    const metricKey = metric + (diskMount || '');

    if (_gaugeActiveMetric === metricKey) {
      chartArea.classList.add('hidden');
      chartArea.innerHTML = '';
      grid.querySelectorAll('.mon-gauge-item').forEach(g => g.classList.remove('mon-gauge-active'));
      _gaugeActiveMetric = null;
      if (_detailChart) { _detailChart.destroy(); _detailChart = null; }
      return;
    }

    _gaugeActiveMetric = metricKey;
    grid.querySelectorAll('.mon-gauge-item').forEach(g => g.classList.remove('mon-gauge-active'));
    gaugeItem.classList.add('mon-gauge-active');

    chartArea.classList.remove('hidden');
    chartArea.innerHTML = `
      <div class="check-detail-periods">
        <button class="btn small active" onclick="_switchGaugePeriod('${check.id}', '1h', this, '${metric}', '${esc(diskMount || '')}')">1h</button>
        <button class="btn small" onclick="_switchGaugePeriod('${check.id}', '6h', this, '${metric}', '${esc(diskMount || '')}')">6h</button>
        <button class="btn small" onclick="_switchGaugePeriod('${check.id}', '24h', this, '${metric}', '${esc(diskMount || '')}')">24h</button>
        <button class="btn small" onclick="_switchGaugePeriod('${check.id}', '7d', this, '${metric}', '${esc(diskMount || '')}')">7d</button>
      </div>
      <div class="check-detail-chart" id="gaugeChart_${check.id}"></div>
    `;
    _loadGaugeChart(check.id, '1h', metric, diskMount);
  });
}

function _switchGaugePeriod(checkId, period, btn, metric, diskMount) {
  btn.parentElement.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  _loadGaugeChart(checkId, period, metric, diskMount || null);
}

async function _loadGaugeChart(checkId, period, metricFilter, diskMount) {
  const chartEl = document.getElementById(`gaugeChart_${checkId}`);
  if (!chartEl) return;
  const check = state.monitorChecks.find(c => c.id === checkId);
  if (!check) return;

  chartEl.innerHTML = '<span style="color:var(--text-soft)">Lade Metriken...</span>';

  try {
    const data = await get(`/api/monitoring/checks/${checkId}/metrics?period=${period}`);
    const allSeries = data.data || [];
    const filtered = allSeries.filter(s => {
      const name = s.metric?.__name__ || '';
      if (name !== metricFilter) return false;
      if (metricFilter === 'monitor_agent_disk_percent' && diskMount) {
        const mount = s.metric?.mount || s.metric?.mountpoint || '/';
        return mount === diskMount;
      }
      return true;
    });
    if (filtered.length === 0) {
      chartEl.innerHTML = '<span style="color:var(--text-soft)">Keine Metrik-Daten verfuegbar</span>';
      return;
    }
    _renderDetailChart(chartEl, { data: filtered }, check);
  } catch (err) {
    chartEl.innerHTML = `<span style="color:var(--red)">Fehler: ${esc(err.message)}</span>`;
  }
}

function _switchDetailPeriod(checkId, period, btn) {
  const check = state.monitorChecks.find(c => c.id === checkId);
  if (!check) return;
  btn.parentElement.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  _loadDetailMetrics(checkId, period, check);
}

async function _loadDetailMetrics(checkId, period, check) {
  const chartEl = document.getElementById(`checkDetailChart_${checkId}`);
  const timelineEl = document.getElementById(`checkDetailTimeline_${checkId}`);
  const currentEl = document.getElementById(`checkDetailCurrent_${checkId}`);
  if (!chartEl) return;

  chartEl.innerHTML = '<span style="color:var(--text-soft)">Lade Metriken...</span>';

  try {
    const data = await get(`/api/monitoring/checks/${checkId}/metrics?period=${period}`);
    _renderDetailCurrentValues(currentEl, data, check);
    _renderDetailChart(chartEl, data, check);
    _renderDetailTimeline(timelineEl, data.statusHistory || []);
  } catch (err) {
    chartEl.innerHTML = `<span style="color:var(--red)">Fehler: ${esc(err.message)}</span>`;
  }
}

function _renderDetailCurrentValues(el, data, check) {
  if (!el) return;
  const series = data.data || [];
  if (series.length === 0) { el.innerHTML = ''; return; }

  const items = series.map(s => {
    const name = s.metric?.__name__ || 'Wert';
    const vals = s.values || [];
    const last = vals.length > 0 ? parseFloat(vals[vals.length - 1][1]) : null;
    if (last === null) return null;
    const unit = _checkTypeUnitWeb(check.checkType);
    const label = name.replace(/^monitor_/, '').replace(/_/g, ' ');
    return `<span class="check-current-item"><strong>${esc(label)}</strong>: ${last.toFixed(1)}${unit}</span>`;
  }).filter(Boolean);

  el.innerHTML = items.join('');
}

function _renderDetailChart(container, data, check) {
  if (_detailChart) { _detailChart.destroy(); _detailChart = null; }
  container.innerHTML = '';

  const series = data.data || [];
  if (series.length === 0) {
    container.innerHTML = '<span style="color:var(--text-soft)">Keine Metrik-Daten verfuegbar</span>';
    return;
  }

  // Zeitstempel aus der ersten Serie als X-Achse
  const timestamps = series[0].values.map(v => v[0]);
  const uData = [timestamps];
  const uSeries = [{}];

  const colors = ['#4a9eff', '#ff6b6b', '#ffa726', '#66bb6a', '#ab47bc', '#26c6da'];
  series.forEach((s, i) => {
    const name = (s.metric?.__name__ || `Serie ${i + 1}`).replace(/^monitor_/, '').replace(/_/g, ' ');
    uData.push(s.values.map(v => parseFloat(v[1])));
    const isCount = ['service_process', 'proxmox_backup', 'docker_health'].includes(check.checkType);
    uSeries.push({
      label: name,
      stroke: colors[i % colors.length],
      width: 2,
      fill: isCount ? colors[i % colors.length] + '20' : undefined,
    });
  });

  const unit = _checkTypeUnitWeb(check.checkType);
  const isPercent = ['agent_resources', 'zfs_health'].includes(check.checkType);

  const opts = {
    width: container.clientWidth || 600,
    height: 200,
    series: uSeries,
    axes: [
      {},
      {
        label: unit,
        ...(isPercent ? { range: [0, 100] } : {}),
      },
    ],
    cursor: { show: true },
    legend: { show: series.length > 1 },
  };

  try {
    _detailChart = new uPlot(opts, uData, container);
  } catch (e) {
    container.innerHTML = '<span style="color:var(--text-soft)">Chart konnte nicht geladen werden</span>';
  }
}

function _renderDetailTimeline(container, statusHistory) {
  if (!container) return;
  const result = statusHistory[0];
  if (!result || !result.values || result.values.length < 2) {
    container.innerHTML = '';
    return;
  }

  const statusMap = { 0: 'ok', 1: 'warning', 2: 'critical', 3: 'unknown', 4: 'pending' };
  const colorMap = { ok: 'var(--green)', warning: 'var(--yellow)', critical: 'var(--red)', unknown: 'var(--text-soft)', pending: '#666' };
  const values = result.values;
  const totalTime = values[values.length - 1][0] - values[0][0];
  if (totalTime <= 0) { container.innerHTML = ''; return; }

  let segments = '';
  for (let i = 0; i < values.length - 1; i++) {
    const status = statusMap[parseInt(values[i][1])] || 'unknown';
    const duration = values[i + 1][0] - values[i][0];
    const pct = (duration / totalTime) * 100;
    segments += `<div class="check-timeline-seg" style="width:${pct}%;background:${colorMap[status]}" title="${status}"></div>`;
  }

  container.innerHTML = `<div class="check-detail-timeline-label">Status-Verlauf</div><div class="check-timeline-bar">${segments}</div>`;
}

function _formatCheckConfigWeb(check) {
  const c = check.config || {};
  const type = check.checkType;
  const kv = [];
  if (type === 'ping') {
    kv.push(['Ziel', c.target], ['Timeout', `${c.timeout || 5}s`]);
  } else if (type === 'tcp') {
    kv.push(['Ziel', `${c.target}:${c.port}`], ['Timeout', `${c.timeout || 5}s`]);
  } else if (type === 'http') {
    kv.push(['URL', c.url], ['Methode', c.method || 'GET'], ['Expected', c.expected_status || 200]);
    if (c.verify_ssl === false) kv.push(['SSL', 'deaktiviert']);
    if (c.search_string) kv.push(['Suchtext', c.search_string]);
  } else if (type === 'agent_ping') {
    kv.push(['Stale-Schwelle', `${c.stale_minutes || 5} min`]);
  } else if (type === 'agent_resources') {
    kv.push(['CPU', `Warn ${c.cpu_warn || 80}% / Crit ${c.cpu_crit || 95}%`],
            ['RAM', `Warn ${c.memory_warn || 80}% / Crit ${c.memory_crit || 95}%`],
            ['Disk', `Warn ${c.disk_warn || 85}% / Crit ${c.disk_crit || 95}%`]);
  } else if (type === 'service_process') {
    kv.push(['Modus', c.mode || 'auto']);
    if (c.services?.length) kv.push(['Services', c.services.join(', ')]);
    if (c.ignore?.length) kv.push(['Ignoriert', c.ignore.join(', ')]);
  } else if (type === 'proxmox_backup') {
    kv.push(['Max. Alter', `${c.max_backup_age_hours || 26}h`]);
    if (c.exclude_vmids?.length) kv.push(['Exclude VMIDs', c.exclude_vmids.join(', ')]);
  } else if (type === 'zfs_health') {
    kv.push(['Kapazitaet', `Warn ${c.capacity_warn || 80}% / Crit ${c.capacity_crit || 90}%`]);
  } else if (type === 'docker_health') {
    if (c.ignore_containers?.length) kv.push(['Ignoriert', c.ignore_containers.join(', ')]);
    kv.push(['Restart-Check', c.check_restarts !== false ? 'aktiv' : 'aus']);
  }
  return kv;
}

function _checkTypeUnitWeb(checkType) {
  if (['ping', 'tcp', 'http'].includes(checkType)) return ' ms';
  if (['agent_resources', 'zfs_health'].includes(checkType)) return '%';
  if (checkType === 'agent_ping') return ' s';
  return '';
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
