/* Simple Remote Manager – Hooks */
'use strict';

const HOOK_EVENTS = [
  { value: 'connection.created',   label: 'Verbindung erstellt' },
  { value: 'connection.updated',   label: 'Verbindung geändert' },
  { value: 'connection.deleted',   label: 'Verbindung gelöscht' },
  { value: 'connections.imported', label: 'Verbindungen importiert' },
  { value: 'user.created',         label: 'Benutzer erstellt' },
  { value: 'user.deleted',         label: 'Benutzer gelöscht' },
  { value: 'server.created',       label: 'Server erstellt' },
  { value: 'server.updated',       label: 'Server geändert' },
  { value: 'server.deleted',       label: 'Server gelöscht' },
  { value: 'server.startup',       label: 'App gestartet' },
  { value: 'frp.config.created',   label: 'FRP-Config erstellt' },
  { value: 'frp.config.updated',   label: 'FRP-Config geändert' },
  { value: 'frp.config.deleted',   label: 'FRP-Config gelöscht' },
  { value: 'frp.tunnel.created',   label: 'FRP-Tunnel erstellt' },
  { value: 'frp.tunnel.updated',   label: 'FRP-Tunnel geändert' },
  { value: 'frp.tunnel.deleted',   label: 'FRP-Tunnel gelöscht' },
];

const HOOK_SCRIPT_HELP = {
  webhook:  'Kontext: <code>payload</code>, <code>headers</code>, <code>params</code>',
  event:    'Kontext: <code>event_type</code>, <code>event_data</code>',
  schedule: 'Kontext: <code>triggered_at</code>, <code>last_run</code>',
};

const HOOK_TYPE_LABEL = { webhook: 'Webhook', event: 'Event', schedule: 'Schedule' };

// Event-Checkboxes einmalig aufbauen
(function () {
  const grid = document.getElementById('hkEventsGrid');
  HOOK_EVENTS.forEach(evt => {
    const lbl = document.createElement('label');
    lbl.className = 'checkbox-label';
    lbl.innerHTML =
      `<input type="checkbox" name="hkEvent" value="${esc(evt.value)}" /> ` +
      `${esc(evt.label)}<br/><span style="font-size:10px;color:var(--text-soft)">${esc(evt.value)}</span>`;
    grid.appendChild(lbl);
  });
}());

document.getElementById('hkType').addEventListener('change', _updateHookFormFields);
document.getElementById('hkInterval').addEventListener('change', () => {
  const custom = document.getElementById('hkInterval').value === 'custom';
  document.getElementById('hkCronField').classList.toggle('hidden', !custom);
});

function _updateHookFormFields() {
  const type = document.getElementById('hkType').value;
  document.getElementById('hkEventsField').classList.toggle('hidden', type !== 'event');
  document.getElementById('hkIntervalField').classList.toggle('hidden', type !== 'schedule');
  if (type !== 'schedule') document.getElementById('hkCronField').classList.add('hidden');
  const base = 'Verfügbar: <code>load_connections()</code>, <code>save_connections(list)</code>, <code>uuid4()</code>, <code>result</code>, <code>logs</code>, <code>log(msg)</code> – <code>import</code> erlaubt';
  document.getElementById('hkScriptHelp').innerHTML =
    (HOOK_SCRIPT_HELP[type] ? HOOK_SCRIPT_HELP[type] + ' · ' : '') + base;
}

async function loadHooks() {
  try {
    state.hooks = await get('/api/hooks');
    renderHooks();
  } catch (err) {
    toast(err.message, 'error');
  }
}

function renderHooks() {
  const tbody = document.getElementById('hookBody');
  const empty = document.getElementById('hookEmpty');
  tbody.innerHTML = '';
  if (state.hooks.length === 0) { empty.classList.remove('hidden'); return; }
  empty.classList.add('hidden');

  state.hooks.forEach(h => {
    const tr = document.createElement('tr');
    const lastRun = h.last_run ? new Date(h.last_run).toLocaleString('de-DE') : '–';

    let details = '–';
    if (h.hook_type === 'webhook') {
      details = `<code style="font-size:11px;color:var(--accent)">/api/hooks/trigger/…</code>`;
    } else if (h.hook_type === 'event') {
      details = (h.event_triggers || []).map(e => `<span class="tag">${esc(e)}</span>`).join(' ') || '–';
    } else if (h.hook_type === 'schedule') {
      details = `<strong>${esc(h.schedule_interval || '–')}</strong>`;
      if (h.next_run) {
        details += `<br/><span style="font-size:11px;color:var(--text-soft)">Nächster: ${esc(new Date(h.next_run).toLocaleString('de-DE'))}</span>`;
      }
    }

    const actions = [
      `<button class="btn small" onclick="editHook('${esc(h.id)}')">Bearbeiten</button>`,
      `<button class="btn small ghost" onclick="runHook('${esc(h.id)}','${esc(h.name)}')">Ausführen</button>`,
      h.hook_type === 'webhook'
        ? `<button class="btn small ghost" onclick="rotateHookToken('${esc(h.id)}','${esc(h.name)}')">Token rotieren</button>`
        : '',
      `<button class="btn small ghost" onclick="toggleHookEnabled('${esc(h.id)}')">${h.enabled ? 'Deaktivieren' : 'Aktivieren'}</button>`,
      `<button class="btn small ghost" onclick="deleteHook('${esc(h.id)}')">Löschen</button>`,
    ].filter(Boolean).join('');

    tr.innerHTML = `
      <td>
        <strong>${esc(h.name)}</strong>
        ${h.description ? `<br/><span style="font-size:11px;color:var(--text-soft)">${esc(h.description)}</span>` : ''}
      </td>
      <td><span class="badge badge-${esc(h.hook_type)}">${esc(HOOK_TYPE_LABEL[h.hook_type] || h.hook_type)}</span></td>
      <td>${details}</td>
      <td><span class="badge badge-${h.enabled ? 'active' : 'inactive'}">${h.enabled ? 'Aktiv' : 'Inaktiv'}</span></td>
      <td style="font-size:12px;color:var(--text-soft)">${esc(lastRun)}</td>
      <td><div style="display:flex;gap:6px;flex-wrap:wrap">${actions}</div></td>
    `;
    tbody.appendChild(tr);
  });
}

document.getElementById('addHookBtn').addEventListener('click', () => openHookModal(null));

function openHookModal(hook) {
  state.editingHookId = hook ? hook.id : null;
  document.getElementById('hookModalTitle').textContent = hook ? 'Hook bearbeiten' : 'Neuer Hook';
  document.getElementById('hkName').value   = hook?.name        || '';
  document.getElementById('hkDesc').value   = hook?.description || '';
  document.getElementById('hkScript').value = hook?.script      || '';

  const typeSelect = document.getElementById('hkType');
  typeSelect.value    = hook?.hook_type || 'webhook';
  typeSelect.disabled = !!hook;

  document.querySelectorAll('input[name="hkEvent"]').forEach(cb => {
    cb.checked = (hook?.event_triggers || []).includes(cb.value);
  });

  const VALID = ['5m', '15m', '30m', '1h', '6h', '12h', '24h'];
  const iv = hook?.schedule_interval || '1h';
  if (VALID.includes(iv)) {
    document.getElementById('hkInterval').value = iv;
    document.getElementById('hkCronField').classList.add('hidden');
  } else {
    document.getElementById('hkInterval').value = 'custom';
    document.getElementById('hkCron').value = iv;
    document.getElementById('hkCronField').classList.remove('hidden');
  }

  _updateHookFormFields();
  showModal('hookModal');
}

document.getElementById('hookForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const type = document.getElementById('hkType').value;
  const data = {
    name:        document.getElementById('hkName').value.trim(),
    description: document.getElementById('hkDesc').value.trim() || null,
    hook_type:   type,
    script:      document.getElementById('hkScript').value,
  };

  if (type === 'event') {
    data.event_triggers = [...document.querySelectorAll('input[name="hkEvent"]:checked')].map(cb => cb.value);
    if (!data.event_triggers.length) { toast('Bitte mindestens ein Event auswählen', 'error'); return; }
  }
  if (type === 'schedule') {
    const iv = document.getElementById('hkInterval').value;
    data.schedule_interval = iv === 'custom' ? document.getElementById('hkCron').value.trim() : iv;
    if (!data.schedule_interval) { toast('Bitte ein Intervall angeben', 'error'); return; }
  }

  try {
    if (state.editingHookId) {
      await put(`/api/hooks/${state.editingHookId}`, data);
      toast('Hook gespeichert');
      closeModal('hookModal');
      await loadHooks();
    } else {
      const result = await post('/api/hooks', data);
      closeModal('hookModal');
      if (type === 'webhook' && result.token) {
        showHookToken(result.token, 'Hook erstellt');
      } else {
        toast('Hook erstellt');
      }
      await loadHooks();
    }
  } catch (err) {
    toast(err.message, 'error');
  }
});

async function editHook(id) {
  try {
    const hook = await get(`/api/hooks/${id}`);
    openHookModal(hook);
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function deleteHook(id) {
  if (!confirm('Hook wirklich löschen?')) return;
  try {
    await del(`/api/hooks/${id}`);
    toast('Hook gelöscht');
    await loadHooks();
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function toggleHookEnabled(id) {
  try {
    await post(`/api/hooks/${id}/toggle`);
    await loadHooks();
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function rotateHookToken(id, name) {
  if (!confirm(`Token für „${name}" wirklich neu generieren? Der alte Token wird ungültig.`)) return;
  try {
    const result = await post(`/api/hooks/${id}/rotate`);
    showHookToken(result.token, 'Neuer Token generiert');
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function runHook(id, name) {
  try {
    toast('Hook wird ausgeführt…');
    const result = await post(`/api/hooks/${id}/run`);
    document.getElementById('hookRunTitle').textContent = `Ergebnis: ${name}`;
    document.getElementById('hookRunResult').textContent = JSON.stringify(result, null, 2);
    showModal('hookRunModal');
  } catch (err) {
    toast(err.message, 'error');
  }
}

function showHookToken(token, title) {
  document.getElementById('webhookTokenTitle').textContent = title;
  document.getElementById('webhookTokenValue').textContent = token;
  document.getElementById('webhookTriggerUrl').textContent = `${location.origin}/api/hooks/trigger/${token}`;
  showModal('webhookTokenModal');
}

document.getElementById('copyWebhookTokenBtn').addEventListener('click', () => {
  navigator.clipboard.writeText(document.getElementById('webhookTokenValue').textContent)
    .then(() => toast('Token kopiert'));
});
