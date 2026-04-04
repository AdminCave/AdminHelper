/* Simple Remote Manager – FRP Tunnels, Config, PKI, Status, Provisioning, Visitors */
'use strict';

// ── FRP Data Loading ───────────────────────────────────────────────────────
async function loadFrp() {
  try {
    const configs = await get('/api/frp/server-config');
    state.frpConfig = configs.length > 0 ? configs[0] : null;
    state.frpTunnels = await get('/api/frp/tunnels');
    state.visitors = await get('/api/frp/visitors');
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
        ${cfg.tlsForce ? `<div><strong>mTLS:</strong> <span style="color:#22c55e">Aktiv</span></div>` : ''}
      </div>
    `;
    downloadFrps.style.display = '';
    downloadVisitor.style.display = '';
    document.getElementById('frpStatusBtn').style.display = '';
    document.getElementById('pkiBtn').style.display = '';
  } else {
    infoEl.textContent = 'Noch keine FRP-Server Konfiguration vorhanden. Klicke auf "Konfigurieren" um zu starten.';
    downloadFrps.style.display = 'none';
    downloadVisitor.style.display = 'none';
    document.getElementById('frpStatusBtn').style.display = 'none';
    document.getElementById('pkiBtn').style.display = 'none';
  }

  // Visitor-Profile rendern
  const visitorListEl = document.getElementById('visitorList');
  if (state.visitors.length > 0) {
    visitorListEl.innerHTML = `<div style="display:flex;flex-wrap:wrap;gap:8px">${
      state.visitors.map(v => {
        const serverNames = v.servers ? v.servers.map(s => s.name).join(', ') : '';
        return `
        <div style="background:var(--surface);padding:8px 14px;border-radius:var(--radius-sm);display:flex;align-items:center;gap:10px">
          <strong style="color:var(--accent)">${esc(v.name)}</strong>
          ${v.displayName ? `<span>${esc(v.displayName)}</span>` : ''}
          <span style="color:var(--text-soft);font-size:11px">${serverNames || 'keine Server'}</span>
          <button class="btn small" onclick="editVisitor('${esc(v.id)}')" style="padding:2px 8px;font-size:11px">&#x270E;</button>
          <button class="btn small ghost" onclick="deleteVisitor('${esc(v.id)}')" style="padding:2px 8px;font-size:11px">&#x2715;</button>
        </div>`;
      }).join('')
    }</div>`;
  } else {
    visitorListEl.textContent = 'Keine Visitor-Profile vorhanden. Erstelle Profile, um individuelle visitor.toml-Configs zu generieren.';
  }

  // Tunnel nach Server gruppieren
  const container = document.getElementById('frpTunnelList');
  const emptyEl = document.getElementById('frpEmpty');
  container.innerHTML = '';

  const tunnelSearchEl = document.getElementById('tunnelSearch');
  const q = tunnelSearchEl ? tunnelSearchEl.value.toLowerCase() : '';
  const filteredTunnels = state.frpTunnels.filter(t => {
    if (state.tunnelTagFilter && !(t.tags || []).includes(state.tunnelTagFilter)) return false;
    if (q) {
      const server = state.servers.find(s => s.id === t.serverId);
      const fields = [
        t.name,
        t.tunnelType,
        t.protocol,
        (t.tags || []).join(' '),
        t.localIp + ':' + t.localPort,
        String(t.remotePort || ''),
        t.customDomains,
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
  filteredTunnels.forEach(t => {
    const sid = t.serverId || '__none__';
    if (!byServer[sid]) byServer[sid] = [];
    byServer[sid].push(t);
  });

  Object.entries(byServer).forEach(([sid, tunnels]) => {
    const server = state.servers.find(s => s.id === sid);
    const card = document.createElement('div');
    card.className = 'server-card';

    const title = server ? esc(server.name) : 'Unbekannter Server';
    const hostname = server ? ` · ${esc(server.hostname)}` : '';

    const tunnelRows = tunnels.map(t => {
      const typeBadge = t.tunnelType === 'stcp'
        ? '<span class="badge badge-ssh">STCP</span>'
        : '<span class="badge badge-web">HTTPS</span>';
      const protoBadge = `<span class="badge">${esc(t.protocol).toUpperCase()}</span>`;
      const target = `${esc(t.localIp)}:${t.localPort}`;
      const tagBadges = (t.tags || []).map(tag => `<span class="badge" style="font-size:10px">${esc(tag)}</span>`).join(' ');
      const visitor = t.visitorPort ? `Visitor :${t.visitorPort}` : (t.customDomains || '\u2013');
      const statusDot = t.enabled
        ? '<span style="color:#22c55e" title="Aktiv">&#x25CF;</span>'
        : '<span style="color:#ef4444" title="Deaktiviert">&#x25CF;</span>';
      return `<tr>
        <td>${statusDot}</td>
        <td>${typeBadge} ${protoBadge}</td>
        <td><strong>${esc(t.name)}</strong> ${tagBadges}</td>
        <td>${target}</td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(visitor)}</td>
        <td style="text-align:right;white-space:nowrap">
          <button class="btn small" onclick="editTunnel('${esc(t.id)}')">Bearbeiten</button>
          <button class="btn small ghost" onclick="deleteTunnel('${esc(t.id)}')">L\u00f6schen</button>
        </td>
      </tr>`;
    }).join('');

    card.innerHTML = `
      <div class="server-card-header" onclick="toggleServerCard(this)">
        <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0">
          <span class="server-chevron open">&#x25B6;</span>
          <div style="min-width:0">
            <strong>${title}</strong>
            <span style="color:var(--text-soft);font-size:13px;margin-left:8px">${hostname}</span>
          </div>
          <span style="color:var(--text-soft);font-size:12px;flex-shrink:0">${tunnels.length} Tunnel</span>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0" onclick="event.stopPropagation()">
          ${server ? `<button class="btn small ghost" onclick="openProvisionModal('${esc(sid)}')">Provision</button>` : ''}
          ${server ? `<button class="btn small ghost" onclick="downloadFrpcToml('${esc(sid)}')">frpc.toml</button>` : ''}
        </div>
      </div>
      <div class="server-card-body">
        <table class="data-table" style="margin:0">
          <thead><tr><th></th><th>Typ</th><th>Name</th><th>Ziel</th><th>Visitor / Domain</th><th></th></tr></thead>
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
  document.getElementById('frpConfigModalTitle').textContent = cfg ? 'FRP-Server bearbeiten' : 'Neue FRP-Server Konfiguration';
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
  document.getElementById('fcTlsForce').checked   = cfg?.tlsForce || false;
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
    tls_force:           document.getElementById('fcTlsForce').checked,
  };
  try {
    if (state.frpConfig) {
      await put(`/api/frp/server-config/${state.frpConfig.id}`, data);
      toast('FRP-Config gespeichert');
    } else {
      await post('/api/frp/server-config', data);
      toast('FRP-Config erstellt');
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
    toast('Bitte zuerst eine FRP-Server Konfiguration anlegen', 'error');
    return;
  }
  state.editingTunnelId = tunnel ? tunnel.id : null;
  document.getElementById('frpTunnelModalTitle').textContent = tunnel ? 'Tunnel bearbeiten' : 'Neuer Tunnel';

  const sel = document.getElementById('ftServer');
  sel.innerHTML = '<option value="">-- Server w\u00e4hlen --</option>';
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

  _updateTunnelFormFields();
  showModal('frpTunnelModal');
}

function _updateTunnelFormFields() {
  const type = document.getElementById('ftType').value;
  const isStcp = type === 'stcp';
  document.getElementById('ftSecretField').style.display  = isStcp ? '' : 'none';
  document.getElementById('ftVisitorField').style.display = isStcp ? '' : 'none';
  document.getElementById('ftDomainsField').style.display = isStcp ? 'none' : '';
}

document.getElementById('ftType').addEventListener('change', _updateTunnelFormFields);

document.getElementById('ftServer').addEventListener('change', () => {
  const tagsEl = document.getElementById('ftTags');
  if (tagsEl.value.trim()) return;
  const serverId = document.getElementById('ftServer').value;
  const server = state.servers.find(s => s.id === serverId);
  if (server && server.tags && server.tags.length > 0) {
    tagsEl.value = server.tags.join(', ');
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
      toast('Tunnel gespeichert');
    } else {
      await post('/api/frp/tunnels', data);
      toast('Tunnel erstellt');
    }
    closeModal('frpTunnelModal');
    await loadFrp();
  } catch (err) {
    toast(err.message, 'error');
  }
});

function editTunnel(id) {
  const t = state.frpTunnels.find(t => t.id === id);
  if (t) openTunnelModal(t);
}

async function deleteTunnel(id) {
  if (!confirm('Tunnel wirklich l\u00f6schen?')) return;
  try {
    await del(`/api/frp/tunnels/${id}`);
    toast('Tunnel gel\u00f6scht');
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
  if (state.visitors.length === 0) {
    try {
      const toml = await _fetchToml('/api/frp/generate/visitor-toml');
      _showConfigPreview('visitor.toml (alle Tunnel)', toml);
    } catch (err) { toast(err.message, 'error'); }
  } else {
    let html = '<div style="display:flex;flex-direction:column;gap:12px">';
    html += '<p style="margin:0;color:var(--text-soft)">Waehle ein Visitor-Profil fuer die Config:</p>';
    state.visitors.forEach(v => {
      const serverNames = v.servers ? v.servers.map(s => s.name).join(', ') : '';
      html += `<div style="background:var(--surface);padding:10px 14px;border-radius:var(--radius-sm);display:flex;justify-content:space-between;align-items:center">
        <div>
          <strong>${esc(v.name)}</strong>
          ${v.displayName ? `<span style="color:var(--text-soft);margin-left:8px">${esc(v.displayName)}</span>` : ''}
          <div style="font-size:11px;color:var(--text-soft)">${serverNames || 'Keine Server zugewiesen'}</div>
        </div>
        <button class="btn small primary" onclick="downloadVisitorToml('${esc(v.id)}', '${esc(v.name)}')">visitor.toml</button>
      </div>`;
    });
    html += `<div style="background:var(--surface);padding:10px 14px;border-radius:var(--radius-sm);display:flex;justify-content:space-between;align-items:center">
      <div><strong>Alle Tunnel</strong><div style="font-size:11px;color:var(--text-soft)">Globale visitor.toml mit allen STCP-Tunneln</div></div>
      <button class="btn small" onclick="downloadVisitorToml(null, 'global')">visitor.toml</button>
    </div>`;
    html += '</div>';
    _showHtmlPreview('Visitor-Config herunterladen', html);
  }
});

async function downloadVisitorToml(visitorId, name) {
  try {
    const url = visitorId
      ? `/api/frp/generate/visitor-toml?visitor_id=${visitorId}`
      : '/api/frp/generate/visitor-toml';
    const toml = await _fetchToml(url);
    closeModal('frpPreviewModal');
    _showConfigPreview(`visitor.toml (${name})`, toml);
  } catch (err) { toast(err.message, 'error'); }
}

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
  navigator.clipboard.writeText(text).then(() => toast('In Zwischenablage kopiert'));
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
    toast('ZIP heruntergeladen');
  } catch (err) {
    toast(err.message, 'error');
  }
});

// Auto-Connection Checkbox nur bei STCP
document.getElementById('ftType').addEventListener('change', () => {
  const isStcp = document.getElementById('ftType').value === 'stcp';
  document.getElementById('ftAutoConnField').style.display = isStcp ? '' : 'none';
  if (!isStcp) document.getElementById('ftAutoConn').checked = false;
});

// ── PKI Management ─────────────────────────────────────────────────────────
document.getElementById('pkiBtn').addEventListener('click', async () => {
  try {
    const status = await get('/api/frp/pki/status');
    let html = '<div style="display:flex;flex-direction:column;gap:16px">';

    html += '<div style="background:var(--surface);padding:12px;border-radius:var(--radius-sm)">';
    html += '<h4 style="margin:0 0 8px">Certificate Authority (CA)</h4>';
    if (status.caExists) {
      html += `<p style="margin:0;color:var(--text-soft)">Gueltig bis: <strong>${new Date(status.caExpiry).toLocaleDateString('de-DE')}</strong></p>`;
      html += `<div style="display:flex;gap:8px;margin-top:8px">`;
      html += `<button class="btn small" onclick="pkiDownload('ca.crt')">ca.crt herunterladen</button>`;
      html += `<button class="btn small primary" onclick="pkiGenerateCA()">CA neu generieren</button>`;
      html += `</div>`;
    } else {
      html += '<p style="margin:0;color:var(--text-soft)">Keine CA vorhanden.</p>';
      html += `<button class="btn small primary" style="margin-top:8px" onclick="pkiGenerateCA()">CA erstellen</button>`;
    }
    html += '</div>';

    html += '<div style="background:var(--surface);padding:12px;border-radius:var(--radius-sm)">';
    html += '<h4 style="margin:0 0 8px">Server-Zertifikat (frps)</h4>';
    if (status.serverCertExists) {
      html += `<p style="margin:0;color:var(--text-soft)">Gueltig bis: <strong>${new Date(status.serverCertExpiry).toLocaleDateString('de-DE')}</strong></p>`;
      html += `<div style="display:flex;gap:8px;margin-top:8px">`;
      html += `<button class="btn small" onclick="pkiDownload('frps.crt')">frps.crt</button>`;
      html += `<button class="btn small" onclick="pkiDownload('frps.key')">frps.key</button>`;
      if (status.caExists) {
        html += `<button class="btn small primary" onclick="pkiGenerateServerCert()">Neu generieren</button>`;
      }
      html += `</div>`;
    } else {
      html += '<p style="margin:0;color:var(--text-soft)">Kein Server-Zertifikat vorhanden.</p>';
      if (status.caExists) {
        html += `<button class="btn small" style="margin-top:8px" onclick="pkiGenerateServerCert()">Server-Cert generieren</button>`;
      }
    }
    html += '</div>';

    html += '<div style="background:var(--surface);padding:12px;border-radius:var(--radius-sm)">';
    html += '<h4 style="margin:0 0 8px">Client-Zertifikate</h4>';
    if (status.clientCerts.length > 0) {
      html += '<table class="data-table" style="margin:0"><thead><tr><th>Name</th><th>Ablauf</th><th></th></tr></thead><tbody>';
      status.clientCerts.forEach(c => {
        html += `<tr><td>${esc(c.name)}</td><td>${new Date(c.expiry).toLocaleDateString('de-DE')}</td>
          <td style="text-align:right;white-space:nowrap">
            <button class="btn small ghost" onclick="pkiDownloadBundle('${esc(c.name)}')" title="ZIP mit ca.crt + Client-Cert + Key">ZIP</button>
            <button class="btn small ghost" onclick="pkiDownload('${esc(c.name)}.crt')">crt</button>
            <button class="btn small ghost" onclick="pkiDownload('${esc(c.name)}.key')">key</button>
          </td></tr>`;
      });
      html += '</tbody></table>';
    } else {
      html += '<p style="margin:0;color:var(--text-soft)">Keine Client-Zertifikate vorhanden.</p>';
    }
    if (status.caExists) {
      html += `<div style="display:flex;gap:8px;margin-top:8px;align-items:center">
        <input id="pkiClientName" type="text" placeholder="Client-Name (z.B. k01-lnx1)" style="flex:1" />
        <button class="btn small" onclick="pkiGenerateClientCert()">Generieren</button>
      </div>`;
    }
    html += '</div></div>';

    _showHtmlPreview('PKI-Verwaltung', html);
  } catch (err) {
    toast(err.message, 'error');
  }
});

async function pkiGenerateCA() {
  if (!confirm('Neue CA generieren? Bestehende Zertifikate werden ungueltig!')) return;
  try {
    const result = await post('/api/frp/pki/ca');
    toast(`CA erstellt (gueltig bis ${new Date(result.expiry).toLocaleDateString('de-DE')})`);
    document.getElementById('pkiBtn').click();
  } catch (err) { toast(err.message, 'error'); }
}

async function pkiGenerateServerCert() {
  try {
    const addr = state.frpConfig?.serverAddr || 'localhost';
    const result = await post('/api/frp/pki/server-cert', { server_addr: addr });
    toast(`Server-Cert erstellt fuer ${result.commonName}`);
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
  if (!name) { toast('Bitte einen Client-Namen eingeben', 'error'); return; }
  try {
    const result = await post(`/api/frp/pki/client-cert/${encodeURIComponent(name)}`);
    toast(`Client-Cert erstellt fuer ${result.commonName}`);
    document.getElementById('pkiBtn').click();
  } catch (err) { toast(err.message, 'error'); }
}

// ── FRP Status Monitoring ──────────────────────────────────────────────────
document.getElementById('frpStatusBtn').addEventListener('click', async () => {
  try {
    const status = await get('/api/frp/status');
    let html = '';

    if (status.error) {
      html = `<p style="color:var(--danger)">frps nicht erreichbar: ${esc(status.error)}</p>`;
    } else {
      const proxies = status.proxies || [];
      if (proxies.length === 0) {
        html = '<p style="color:var(--text-soft)">Keine aktiven Proxies auf dem frps-Server.</p>';
      } else {
        html += '<table class="data-table" style="margin:0"><thead><tr><th></th><th>Name</th><th>Typ</th><th>Verbindungen</th><th>Traffic In</th><th>Traffic Out</th></tr></thead><tbody>';
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

    _showHtmlPreview('frps Tunnel-Status', html);
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
  document.getElementById('provisionModalTitle').textContent = `Provisioning: ${server?.name || serverId}`;
  document.getElementById('provisionOneLiner').classList.add('hidden');
  showModal('provisionModal');
  await _loadProvisionTokens(serverId);
}

document.getElementById('createProvisionTokenBtn').addEventListener('click', async () => {
  if (!_provisionServerId) return;
  try {
    const result = await post(`/api/frp/provision/${_provisionServerId}/token`);
    const srmUrl = window.location.origin;
    const cmd = `sudo srm-frpc-sync --init \\\n  --url ${srmUrl} \\\n  --token ${result.token} \\\n  --server-id ${_provisionServerId}`;
    document.getElementById('provisionCommand').textContent = cmd;
    document.getElementById('provisionOneLiner').classList.remove('hidden');
    toast('Provision-Token erstellt (24h gueltig)');
    await _loadProvisionTokens(_provisionServerId);
  } catch (err) {
    toast(err.message, 'error');
  }
});

function copyProvisionCommand() {
  const text = document.getElementById('provisionCommand').textContent;
  navigator.clipboard.writeText(text).then(() => toast('Befehl kopiert'));
}

async function _loadProvisionTokens(serverId) {
  const el = document.getElementById('provisionTokenListContent');
  try {
    const tokens = await get(`/api/frp/provision/${serverId}/tokens`);
    if (tokens.length === 0) {
      el.textContent = 'Keine Tokens vorhanden.';
      return;
    }
    let html = '<table class="data-table" style="margin:0;font-size:13px"><thead><tr><th>Erstellt</th><th>Ablauf</th><th>Status</th></tr></thead><tbody>';
    tokens.forEach(t => {
      const created = new Date(t.createdAt).toLocaleString('de-DE');
      const expires = new Date(t.expiresAt).toLocaleString('de-DE');
      let statusBadge;
      if (t.usedAt) {
        statusBadge = `<span style="color:#22c55e">Verwendet (${new Date(t.usedAt).toLocaleString('de-DE')})</span>`;
      } else if (t.isValid) {
        statusBadge = '<span style="color:var(--accent)">Aktiv</span>';
      } else {
        statusBadge = '<span style="color:#ef4444">Abgelaufen</span>';
      }
      html += `<tr><td>${created}</td><td>${expires}</td><td>${statusBadge}</td></tr>`;
    });
    html += '</tbody></table>';
    el.innerHTML = html;
  } catch (err) {
    el.textContent = 'Fehler beim Laden.';
  }
}

// ── Visitors ───────────────────────────────────────────────────────────────
document.getElementById('addVisitorBtn').addEventListener('click', () => openVisitorModal(null));

function openVisitorModal(visitor) {
  state.editingVisitorId = visitor ? visitor.id : null;
  document.getElementById('visitorModalTitle').textContent = visitor ? 'Visitor bearbeiten' : 'Neues Visitor-Profil';
  document.getElementById('vfName').value = visitor?.name || '';
  document.getElementById('vfName').disabled = !!visitor;
  document.getElementById('vfDisplayName').value = visitor?.displayName || '';
  document.getElementById('vfNotes').value = visitor?.notes || '';

  const selectedIds = new Set(visitor?.serverIds || []);
  const listEl = document.getElementById('vfServerList');
  listEl.innerHTML = state.servers.map(s => `
    <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
      <input type="checkbox" value="${esc(s.id)}" ${selectedIds.has(s.id) ? 'checked' : ''} />
      <span>${esc(s.name)}</span>
      <span style="color:var(--text-soft);font-size:11px">${esc(s.hostname)}</span>
    </label>
  `).join('');
  if (state.servers.length === 0) {
    listEl.innerHTML = '<span style="color:var(--text-soft)">Keine Server vorhanden.</span>';
  }

  showModal('visitorModal');
}

document.getElementById('visitorForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const serverCheckboxes = document.querySelectorAll('#vfServerList input[type="checkbox"]:checked');
  const data = {
    name: document.getElementById('vfName').value.trim().toLowerCase(),
    display_name: document.getElementById('vfDisplayName').value.trim() || null,
    notes: document.getElementById('vfNotes').value.trim() || null,
    server_ids: Array.from(serverCheckboxes).map(cb => cb.value),
  };
  try {
    if (state.editingVisitorId) {
      await put(`/api/frp/visitors/${state.editingVisitorId}`, data);
      toast('Visitor gespeichert');
    } else {
      await post('/api/frp/visitors', data);
      toast('Visitor erstellt');
    }
    closeModal('visitorModal');
    await loadFrp();
  } catch (err) {
    toast(err.message, 'error');
  }
});

function editVisitor(id) {
  const v = state.visitors.find(v => v.id === id);
  if (v) openVisitorModal(v);
}

async function deleteVisitor(id) {
  if (!confirm('Visitor-Profil wirklich loeschen?')) return;
  try {
    await del(`/api/frp/visitors/${id}`);
    toast('Visitor geloescht');
    await loadFrp();
  } catch (err) {
    toast(err.message, 'error');
  }
}
