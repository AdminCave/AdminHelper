/* AdminHelper – FRP Tunnels, Config, PKI, Status, Provisioning, Visitors */
'use strict';

// ── FRP Data Loading ───────────────────────────────────────────────────────
async function loadFrp() {
  try {
    const configs = await get('/api/frp/server-config');
    state.frpConfig = configs.length > 0 ? configs[0] : null;
    state.frpTunnels = await get('/api/frp/tunnels');
    if (state.servers.length === 0) {
      state.servers = await get('/api/servers');
    }
    renderTagFilter('tunnelTagSelect', state.frpTunnels, 'tunnelTagFilter');
    renderFrp();
  } catch (err) {
    toast(err.message, 'error');
  }
}

document.getElementById('tunnelTagSelect').addEventListener('change', function() {
  state.tunnelTagFilter = this.value;
  renderFrp();
});

document.getElementById('tunnelSearch').addEventListener('input', renderFrp);

// ── Render FRP Page ────────────────────────────────────────────────────────
function renderFrp() {
  const cfg = state.frpConfig;
  const infoEl = document.getElementById('frpConfigInfo');
  const downloadFrps = document.getElementById('downloadFrpsBtn');
  const downloadVisitor = document.getElementById('downloadVisitorBtn');

  if (cfg) {
    infoEl.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px 24px">
        <div><strong>Name:</strong> ${esc(cfg.name)}</div>
        <div><strong>Adresse:</strong> ${esc(cfg.serverAddr)}</div>
        <div><strong>Bind Port:</strong> ${cfg.bindPort}</div>
        ${cfg.vhostHttpsPort ? `<div><strong>HTTPS Port:</strong> ${cfg.vhostHttpsPort}</div>` : ''}
        ${cfg.subdomainHost ? `<div><strong>Subdomain:</strong> ${esc(cfg.subdomainHost)}</div>` : ''}
        ${cfg.dashboardPort ? `<div><strong>Dashboard:</strong> :${cfg.dashboardPort}</div>` : ''}
        <div><strong>mTLS:</strong> <span style="color:#22c55e">${t('page.frp.mtlsActive')}</span></div>
      </div>
    `;
    downloadFrps.style.display = '';
    downloadVisitor.style.display = '';
    document.getElementById('frpStatusBtn').style.display = '';
    document.getElementById('pkiBtn').style.display = '';
  } else {
    infoEl.textContent = t('page.frp.noConfig');
    downloadFrps.style.display = 'none';
    downloadVisitor.style.display = 'none';
    document.getElementById('frpStatusBtn').style.display = 'none';
    document.getElementById('pkiBtn').style.display = 'none';
  }

  // Tunnel nach Server gruppieren
  const container = document.getElementById('frpTunnelList');
  const emptyEl = document.getElementById('frpEmpty');
  container.innerHTML = '';

  const tunnelSearchEl = document.getElementById('tunnelSearch');
  const q = tunnelSearchEl ? tunnelSearchEl.value.toLowerCase() : '';
  const filteredTunnels = state.frpTunnels.filter(tn => {
    if (state.tunnelTagFilter && !(tn.tags || []).includes(state.tunnelTagFilter)) return false;
    if (q) {
      const server = state.servers.find(s => s.id === tn.serverId);
      const fields = [
        tn.name,
        tn.tunnelType,
        tn.protocol,
        (tn.tags || []).join(' '),
        tn.localIp + ':' + tn.localPort,
        String(tn.remotePort || ''),
        tn.customDomains,
        server ? server.name : '',
        server ? server.hostname : '',
      ].map(f => (f || '').toLowerCase());
      if (!fields.some(f => f.includes(q))) return false;
    }
    return true;
  });

  if (filteredTunnels.length === 0) {
    emptyEl.classList.remove('hidden');
    return;
  }
  emptyEl.classList.add('hidden');

  const byServer = {};
  filteredTunnels.forEach(tun => {
    const sid = tun.serverId || '__none__';
    if (!byServer[sid]) byServer[sid] = [];
    byServer[sid].push(tun);
  });

  Object.entries(byServer).forEach(([sid, tunnels]) => {
    const server = state.servers.find(s => s.id === sid);
    const card = document.createElement('div');
    card.className = 'server-card';

    const title = server ? esc(server.name) : t('page.frp.unknownServer');
    const hostname = server ? ` · ${esc(server.hostname)}` : '';

    const tunnelRows = tunnels.map(tun => {
      const typeBadge = tun.tunnelType === 'stcp'
        ? '<span class="badge badge-ssh">STCP</span>'
        : '<span class="badge badge-web">HTTPS</span>';
      const protoBadge = `<span class="badge">${esc(tun.protocol).toUpperCase()}</span>`;
      const target = `${esc(tun.localIp)}:${tun.localPort}`;
      const tagBadges = (tun.tags || []).map(tag => `<span class="badge" style="font-size:10px">${esc(tag)}</span>`).join(' ');
      const visitor = tun.visitorPort ? `Visitor :${tun.visitorPort}` : (tun.customDomains || '\u2013');
      const statusDot = tun.enabled
        ? `<span style="color:#22c55e" title="${t('action.enable')}">&#x25CF;</span>`
        : `<span style="color:#ef4444" title="${t('action.disable')}">&#x25CF;</span>`;
      return `<tr>
        <td>${statusDot}</td>
        <td>${typeBadge} ${protoBadge}</td>
        <td><strong>${esc(tun.name)}</strong> ${tagBadges}</td>
        <td>${target}</td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(visitor)}</td>
        <td style="text-align:right;white-space:nowrap">
          <button class="btn small" onclick="editTunnel('${esc(tun.id)}')">${t('action.edit')}</button>
          <button class="btn small ghost" onclick="deleteTunnel('${esc(tun.id)}')">${t('action.delete')}</button>
        </td>
      </tr>`;
    }).join('');

    card.innerHTML = `
      <div class="server-card-header" onclick="toggleServerCard(this)">
        <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0">
          <span class="server-chevron open">&#x25B6;</span>
          <div style="min-width:0">
            <strong>${title}</strong>
            <span style="color:var(--text-muted);font-size:13px;margin-left:8px">${hostname}</span>
          </div>
          <span style="color:var(--text-muted);font-size:12px;flex-shrink:0">${t('page.frp.tunnelCount', { count: tunnels.length })}</span>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0" onclick="event.stopPropagation()">
          ${server ? `<button class="btn small ghost" onclick="openProvisionModal('${esc(sid)}')">Provision</button>` : ''}
          ${server ? `<button class="btn small ghost" onclick="downloadFrpcToml('${esc(sid)}')">frpc.toml</button>` : ''}
        </div>
      </div>
      <div class="server-card-body">
        <table class="data-table" style="margin:0">
          <thead><tr><th></th><th>${t('label.type')}</th><th>${t('label.name')}</th><th>${t('monitor.cfg.target')}</th><th>Visitor / Domain</th><th></th></tr></thead>
          <tbody>${tunnelRows}</tbody>
        </table>
      </div>
    `;
    container.appendChild(card);
  });
}

// ── FRP Config Modal ───────────────────────────────────────────────────────
document.getElementById('frpConfigBtn').addEventListener('click', () => openFrpConfigModal());

function openFrpConfigModal() {
  const cfg = state.frpConfig;
  document.getElementById('frpConfigModalTitle').textContent = cfg ? t('modal.frpConfig.title') : t('modal.frpConfig.titleNew');
  document.getElementById('fcName').value        = cfg?.name          || '';
  document.getElementById('fcServerAddr').value   = cfg?.serverAddr    || '';
  document.getElementById('fcBindPort').value     = cfg?.bindPort      || 7000;
  document.getElementById('fcVhostPort').value    = cfg?.vhostHttpsPort || '';
  document.getElementById('fcAuthToken').value    = cfg?.authToken     || '';
  document.getElementById('fcSubdomainHost').value = cfg?.subdomainHost || '';
  document.getElementById('fcMaxPorts').value     = cfg?.maxPortsPerClient || '';
  document.getElementById('fcDashPort').value     = cfg?.dashboardPort  || '';
  document.getElementById('fcDashUser').value     = cfg?.dashboardUser  || '';
  document.getElementById('fcDashPass').value     = cfg?.dashboardPassword || '';
  showModal('frpConfigModal');
}

document.getElementById('frpConfigForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = {
    name:                document.getElementById('fcName').value.trim(),
    server_addr:         document.getElementById('fcServerAddr').value.trim(),
    bind_port:           parseInt(document.getElementById('fcBindPort').value) || 7000,
    vhost_https_port:    parseInt(document.getElementById('fcVhostPort').value) || null,
    auth_token:          document.getElementById('fcAuthToken').value.trim() || null,
    subdomain_host:      document.getElementById('fcSubdomainHost').value.trim() || null,
    max_ports_per_client: parseInt(document.getElementById('fcMaxPorts').value) || null,
    dashboard_port:      parseInt(document.getElementById('fcDashPort').value) || null,
    dashboard_user:      document.getElementById('fcDashUser').value.trim() || null,
    dashboard_password:  document.getElementById('fcDashPass').value.trim() || null,
  };
  try {
    if (state.frpConfig) {
      await put(`/api/frp/server-config/${state.frpConfig.id}`, data);
      toast(t('toast.frpConfig.saved'));
    } else {
      await post('/api/frp/server-config', data);
      toast(t('toast.frpConfig.created'));
    }
    closeModal('frpConfigModal');
    await loadFrp();
  } catch (err) {
    toast(err.message, 'error');
  }
});

// ── Tunnel Modal ───────────────────────────────────────────────────────────
document.getElementById('addTunnelBtn').addEventListener('click', () => openTunnelModal(null));

function openTunnelModal(tunnel) {
  if (!state.frpConfig) {
    toast(t('page.frp.createConfigFirst'), 'error');
    return;
  }
  state.editingTunnelId = tunnel ? tunnel.id : null;
  document.getElementById('frpTunnelModalTitle').textContent = tunnel ? t('modal.tunnel.title') : t('modal.tunnel.titleNew');

  const sel = document.getElementById('ftServer');
  sel.innerHTML = `<option value="">${t('modal.tunnel.selectServer')}</option>`;
  state.servers.forEach(s => {
    sel.innerHTML += `<option value="${esc(s.id)}">${esc(s.name)} (${esc(s.hostname)})</option>`;
  });

  document.getElementById('ftServer').value    = tunnel?.serverId   || '';
  document.getElementById('ftName').value       = tunnel?.name       || '';
  document.getElementById('ftType').value       = tunnel?.tunnelType || 'stcp';
  document.getElementById('ftProtocol').value   = tunnel?.protocol   || 'ssh';
  document.getElementById('ftLocalIp').value    = tunnel?.localIp    || '127.0.0.1';
  document.getElementById('ftLocalPort').value  = tunnel?.localPort  || '';
  document.getElementById('ftSecret').value     = tunnel?.secretKey  || '';
  document.getElementById('ftVisitorPort').value = tunnel?.visitorPort || '';
  document.getElementById('ftDomains').value    = tunnel?.customDomains || '';
  document.getElementById('ftTags').value       = (tunnel?.tags || []).join(', ');
  document.getElementById('ftAutoConn').checked = !!(tunnel?.connectionId);

  _updateTunnelFormFields();
  showModal('frpTunnelModal');
}

function _updateTunnelFormFields() {
  const type = document.getElementById('ftType').value;
  const isStcp = type === 'stcp';
  document.getElementById('ftSecretField').style.display   = isStcp ? '' : 'none';
  document.getElementById('ftVisitorField').style.display  = isStcp ? '' : 'none';
  document.getElementById('ftDomainsField').style.display  = isStcp ? 'none' : '';
  document.getElementById('ftAutoConnField').style.display = '';
}

document.getElementById('ftType').addEventListener('change', _updateTunnelFormFields);

document.getElementById('ftServer').addEventListener('change', () => {
  const serverId = document.getElementById('ftServer').value;

  // Tags vorbelegen
  const tagsEl = document.getElementById('ftTags');
  if (!tagsEl.value.trim()) {
    const server = state.servers.find(s => s.id === serverId);
    if (server && server.tags && server.tags.length > 0) {
      tagsEl.value = server.tags.join(', ');
    }
  }

});

document.getElementById('ftProtocol').addEventListener('change', () => {
  const proto = document.getElementById('ftProtocol').value;
  const portEl = document.getElementById('ftLocalPort');
  if (!portEl.value) {
    if (proto === 'ssh') portEl.value = 22;
    else if (proto === 'rdp') portEl.value = 3389;
    else if (proto === 'web') portEl.value = 8006;
  }
});

document.getElementById('frpTunnelForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = {
    server_id:     document.getElementById('ftServer').value,
    frp_config_id: state.frpConfig.id,
    name:          document.getElementById('ftName').value.trim(),
    tunnel_type:   document.getElementById('ftType').value,
    protocol:      document.getElementById('ftProtocol').value,
    local_ip:      document.getElementById('ftLocalIp').value.trim(),
    local_port:    parseInt(document.getElementById('ftLocalPort').value),
    secret_key:    document.getElementById('ftSecret').value.trim() || null,
    custom_domains: document.getElementById('ftDomains').value.trim() || null,
    visitor_port:  parseInt(document.getElementById('ftVisitorPort').value) || null,
    auto_create_connection: document.getElementById('ftAutoConn').checked,
    tags: parseTags(document.getElementById('ftTags').value),
  };
  try {
    if (state.editingTunnelId) {
      await put(`/api/frp/tunnels/${state.editingTunnelId}`, data);
      toast(t('toast.tunnel.saved'));
    } else {
      await post('/api/frp/tunnels', data);
      toast(t('toast.tunnel.created'));
    }

    closeModal('frpTunnelModal');
    await loadFrp();
  } catch (err) {
    toast(err.message, 'error');
  }
});

function editTunnel(id) {
  const tun = state.frpTunnels.find(tun => tun.id === id);
  if (tun) openTunnelModal(tun);
}

async function deleteTunnel(id) {
  if (!confirm(t('confirm.tunnel.delete'))) return;
  try {
    await del(`/api/frp/tunnels/${id}`);
    toast(t('toast.tunnel.deleted'));
    await loadFrp();
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ── Config Downloads ───────────────────────────────────────────────────────
async function _fetchToml(url) {
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${state.token}` },
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return res.text();
}

document.getElementById('downloadFrpsBtn').addEventListener('click', async () => {
  try {
    const toml = await _fetchToml('/api/frp/generate/frps-toml');
    _showConfigPreview('frps.toml', toml);
  } catch (err) { toast(err.message, 'error'); }
});

document.getElementById('downloadVisitorBtn').addEventListener('click', async () => {
  try {
    const toml = await _fetchToml('/api/frp/generate/visitor-toml');
    _showConfigPreview('visitor.toml', toml);
  } catch (err) { toast(err.message, 'error'); }
});

async function downloadFrpcToml(serverId) {
  try {
    const toml = await _fetchToml(`/api/frp/generate/frpc-toml/${serverId}`);
    const server = state.servers.find(s => s.id === serverId);
    _showConfigPreview(`frpc.toml (${server?.name || serverId})`, toml);
  } catch (err) { toast(err.message, 'error'); }
}

function _showConfigPreview(title, content) {
  const el = document.getElementById('frpPreviewContent');
  document.getElementById('frpPreviewTitle').textContent = title;
  el.textContent = content;
  el.style.whiteSpace = 'pre-wrap';
  document.getElementById('copyFrpConfigBtn').style.display = '';
  showModal('frpPreviewModal');
}

function _showHtmlPreview(title, html) {
  const el = document.getElementById('frpPreviewContent');
  document.getElementById('frpPreviewTitle').textContent = title;
  el.innerHTML = html;
  el.style.whiteSpace = 'normal';
  document.getElementById('copyFrpConfigBtn').style.display = 'none';
  showModal('frpPreviewModal');
}

document.getElementById('copyFrpConfigBtn').addEventListener('click', () => {
  const text = document.getElementById('frpPreviewContent').textContent;
  navigator.clipboard.writeText(text).then(() => toast(t('toast.frp.copied')));
});

// Bulk-ZIP
document.getElementById('bulkZipBtn').addEventListener('click', async () => {
  try {
    const res = await fetch('/api/frp/generate/bulk-zip', {
      headers: { Authorization: `Bearer ${state.token}` },
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'frp-configs.zip';
    a.click();
    URL.revokeObjectURL(url);
    toast(t('toast.frp.zipDownloaded'));
  } catch (err) {
    toast(err.message, 'error');
  }
});


// ── PKI Management ─────────────────────────────────────────────────────────
document.getElementById('pkiBtn').addEventListener('click', async () => {
  try {
    const status = await get('/api/frp/pki/status');
    const _dl = currentLanguage === 'en' ? 'en-GB' : 'de-DE';
    let html = '<div style="display:flex;flex-direction:column;gap:16px">';

    html += '<div style="background:var(--bg-elevated);padding:12px;border-radius:var(--radius-sm)">';
    html += `<h4 style="margin:0 0 8px">${t('frp.pki.caTitle')}</h4>`;
    if (status.caExists) {
      html += `<p style="margin:0;color:var(--text-muted)">${t('frp.pki.caValidUntil')} <strong>${new Date(status.caExpiry).toLocaleDateString(_dl)}</strong></p>`;
      html += `<div style="display:flex;gap:8px;margin-top:8px">`;
      html += `<button class="btn small" onclick="pkiDownload('ca.crt')">${t('frp.pki.caDownload')}</button>`;
      html += `<button class="btn small primary" onclick="pkiGenerateCA()">${t('frp.pki.caRegenerate')}</button>`;
      html += `</div>`;
    } else {
      html += `<p style="margin:0;color:var(--text-muted)">${t('frp.pki.caNotExist')}</p>`;
      html += `<button class="btn small primary" style="margin-top:8px" onclick="pkiGenerateCA()">${t('frp.pki.caCreate')}</button>`;
    }
    html += '</div>';

    html += '<div style="background:var(--bg-elevated);padding:12px;border-radius:var(--radius-sm)">';
    html += `<h4 style="margin:0 0 8px">${t('frp.pki.serverCertTitle')}</h4>`;
    if (status.serverCertExists) {
      html += `<p style="margin:0;color:var(--text-muted)">${t('frp.pki.caValidUntil')} <strong>${new Date(status.serverCertExpiry).toLocaleDateString(_dl)}</strong></p>`;
      html += `<div style="display:flex;gap:8px;margin-top:8px">`;
      html += `<button class="btn small" onclick="pkiDownload('frps.crt')">frps.crt</button>`;
      html += `<button class="btn small" onclick="pkiDownload('frps.key')">frps.key</button>`;
      if (status.caExists) {
        html += `<button class="btn small primary" onclick="pkiGenerateServerCert()">${t('frp.pki.serverCertRegenerate')}</button>`;
      }
      html += `</div>`;
    } else {
      html += `<p style="margin:0;color:var(--text-muted)">${t('frp.pki.serverCertNotExist')}</p>`;
      if (status.caExists) {
        html += `<button class="btn small" style="margin-top:8px" onclick="pkiGenerateServerCert()">${t('frp.pki.serverCertGenerate')}</button>`;
      }
    }
    html += '</div>';

    html += '<div style="background:var(--bg-elevated);padding:12px;border-radius:var(--radius-sm)">';
    html += `<h4 style="margin:0 0 8px">${t('frp.pki.clientCertsTitle')}</h4>`;
    if (status.clientCerts.length > 0) {
      html += `<table class="data-table" style="margin:0"><thead><tr><th>${t('label.name')}</th><th>${t('frp.pki.expiry')}</th><th></th></tr></thead><tbody>`;
      status.clientCerts.forEach(c => {
        html += `<tr><td>${esc(c.name)}</td><td>${new Date(c.expiry).toLocaleDateString(_dl)}</td>
          <td style="text-align:right;white-space:nowrap">
            <button class="btn small ghost" onclick="pkiDownloadBundle('${esc(c.name)}')">ZIP</button>
            <button class="btn small ghost" onclick="pkiDownload('${esc(c.name)}.crt')">crt</button>
            <button class="btn small ghost" onclick="pkiDownload('${esc(c.name)}.key')">key</button>
          </td></tr>`;
      });
      html += '</tbody></table>';
    } else {
      html += `<p style="margin:0;color:var(--text-muted)">${t('frp.pki.clientCertsNone')}</p>`;
    }
    if (status.caExists) {
      html += `<div style="display:flex;gap:8px;margin-top:8px;align-items:center">
        <input id="pkiClientName" type="text" placeholder="${t('frp.pki.clientNamePlaceholder')}" style="flex:1" />
        <button class="btn small" onclick="pkiGenerateClientCert()">${t('frp.pki.generate')}</button>
      </div>`;
    }
    html += '</div></div>';

    _showHtmlPreview(t('frp.pki.title'), html);
  } catch (err) {
    toast(err.message, 'error');
  }
});

async function pkiGenerateCA() {
  if (!confirm(t('confirm.pki.regenerateCA'))) return;
  try {
    const result = await post('/api/frp/pki/ca');
    const _dl = currentLanguage === 'en' ? 'en-GB' : 'de-DE';
    toast(t('toast.pki.caCreated', { date: new Date(result.expiry).toLocaleDateString(_dl) }));
    document.getElementById('pkiBtn').click();
  } catch (err) { toast(err.message, 'error'); }
}

async function pkiGenerateServerCert() {
  try {
    const addr = state.frpConfig?.serverAddr || 'localhost';
    const result = await post('/api/frp/pki/server-cert', { server_addr: addr });
    toast(t('toast.pki.serverCertCreated', { name: result.commonName }));
    document.getElementById('pkiBtn').click();
  } catch (err) { toast(err.message, 'error'); }
}

async function pkiDownload(filename) {
  try {
    const res = await fetch(`/api/frp/pki/download/${encodeURIComponent(filename)}`, {
      headers: { Authorization: `Bearer ${state.token}` },
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) { toast(err.message, 'error'); }
}

async function pkiDownloadBundle(clientName) {
  try {
    const res = await fetch(`/api/frp/pki/download-client-bundle/${encodeURIComponent(clientName)}`, {
      headers: { Authorization: `Bearer ${state.token}` },
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${clientName}-pki.zip`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) { toast(err.message, 'error'); }
}

async function pkiGenerateClientCert() {
  const name = document.getElementById('pkiClientName')?.value?.trim();
  if (!name) { toast(t('toast.pki.enterClientName'), 'error'); return; }
  try {
    const result = await post(`/api/frp/pki/client-cert/${encodeURIComponent(name)}`);
    toast(t('toast.pki.clientCertCreated', { name: result.commonName }));
    document.getElementById('pkiBtn').click();
  } catch (err) { toast(err.message, 'error'); }
}

// ── FRP Status Monitoring ──────────────────────────────────────────────────
document.getElementById('frpStatusBtn').addEventListener('click', async () => {
  try {
    const status = await get('/api/frp/status');
    let html = '';

    if (status.error) {
      html = `<p style="color:var(--danger)">${t('frp.status.unreachable', { error: esc(status.error) })}</p>`;
    } else {
      const proxies = status.proxies || [];
      if (proxies.length === 0) {
        html = `<p style="color:var(--text-muted)">${t('frp.status.noProxies')}</p>`;
      } else {
        html += `<table class="data-table" style="margin:0"><thead><tr><th></th><th>${t('label.name')}</th><th>${t('label.type')}</th><th>${t('frp.status.connections')}</th><th>Traffic In</th><th>Traffic Out</th></tr></thead><tbody>`;
        proxies.forEach(p => {
          const online = p.status === 'online';
          const dot = online
            ? '<span style="color:#22c55e" title="Online">&#x25CF;</span>'
            : '<span style="color:#ef4444" title="Offline">&#x25CF;</span>';
          const trafficIn = _formatBytes(p.todayTrafficIn || 0);
          const trafficOut = _formatBytes(p.todayTrafficOut || 0);
          html += `<tr><td>${dot}</td><td>${esc(p.name)}</td><td>${esc(p.type || '-')}</td><td>${p.curConns || 0}</td><td>${trafficIn}</td><td>${trafficOut}</td></tr>`;
        });
        html += '</tbody></table>';
      }
    }

    _showHtmlPreview(t('frp.status.title'), html);
  } catch (err) {
    toast(err.message, 'error');
  }
});

function _formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// ── Provisioning ───────────────────────────────────────────────────────────
let _provisionServerId = null;

async function openProvisionModal(serverId) {
  _provisionServerId = serverId;
  const server = state.servers.find(s => s.id === serverId);
  document.getElementById('provisionModalTitle').textContent = t('frp.provision.title', { name: server?.name || serverId });
  document.getElementById('provisionOneLiner').classList.add('hidden');
  showModal('provisionModal');
  await _loadProvisionTokens(serverId);
}

document.getElementById('createProvisionTokenBtn').addEventListener('click', async () => {
  if (!_provisionServerId) return;
  try {
    const result = await post(`/api/frp/provision/${_provisionServerId}/token`);
    const srmUrl = window.location.origin;
    let cmd = `# FRP-Client einrichten\nsudo adminhelper-agent frpc init \\\n  --url ${srmUrl} \\\n  --token ${result.token} \\\n  --server-id ${_provisionServerId} \\\n  --insecure`;

    // Monitoring-Agent Key generieren und Befehl anhaengen
    try {
      const agentKey = await post(`/api/monitoring/agent-keys/${_provisionServerId}`);
      cmd += `\n\n# Monitoring-Agent einrichten\nsudo adminhelper-agent monitor init \\\n  --url ${srmUrl}/api/monitoring \\\n  --api-key ${agentKey.apiKey} \\\n  --server-id ${_provisionServerId} \\\n  --insecure`;
    } catch { /* Monitoring nicht erreichbar — nur FRP anzeigen */ }

    document.getElementById('provisionCommand').textContent = cmd;
    document.getElementById('provisionOneLiner').classList.remove('hidden');
    toast(t('toast.provision.created'));
    await _loadProvisionTokens(_provisionServerId);
  } catch (err) {
    toast(err.message, 'error');
  }
});

function copyProvisionCommand() {
  const text = document.getElementById('provisionCommand').textContent;
  navigator.clipboard.writeText(text).then(() => toast(t('toast.provision.commandCopied')));
}

async function _loadProvisionTokens(serverId) {
  const el = document.getElementById('provisionTokenListContent');
  try {
    const tokens = await get(`/api/frp/provision/${serverId}/tokens`);
    if (tokens.length === 0) {
      el.textContent = t('frp.provision.noTokens');
      return;
    }
    const _dl = currentLanguage === 'en' ? 'en-GB' : 'de-DE';
    let html = `<table class="data-table" style="margin:0;font-size:13px"><thead><tr><th>${t('label.created')}</th><th>${t('frp.pki.expiry')}</th><th>${t('label.status')}</th></tr></thead><tbody>`;
    tokens.forEach(tk => {
      const created = new Date(tk.createdAt).toLocaleString(_dl);
      const expires = new Date(tk.expiresAt).toLocaleString(_dl);
      let statusBadge;
      if (tk.usedAt) {
        statusBadge = `<span style="color:#22c55e">${t('frp.provision.used', { time: new Date(tk.usedAt).toLocaleString(_dl) })}</span>`;
      } else if (tk.isValid) {
        statusBadge = `<span style="color:var(--accent)">${t('frp.provision.active')}</span>`;
      } else {
        statusBadge = `<span style="color:#ef4444">${t('frp.provision.expired')}</span>`;
      }
      html += `<tr><td>${created}</td><td>${expires}</td><td>${statusBadge}</td></tr>`;
    });
    html += '</tbody></table>';
    el.innerHTML = html;
  } catch (err) {
    el.textContent = t('frp.provision.loadError');
  }
}

