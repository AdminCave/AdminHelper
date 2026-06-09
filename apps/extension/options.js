// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

'use strict';

const serverUrlInput = document.getElementById('server-url');
const apiKeyInput    = document.getElementById('api-key');
const toggleKeyBtn   = document.getElementById('toggle-key');
const saveBtn        = document.getElementById('btn-save');
const testBtn        = document.getElementById('btn-test');
const statusSave     = document.getElementById('status-save');
const statusTest     = document.getElementById('status-test');

// ─── Load saved settings ──────────────────────────────────────────────────────
async function loadSettings() {
  const data = await chrome.storage.local.get(['serverUrl', 'apiKey']);
  if (data.serverUrl) serverUrlInput.value = data.serverUrl;
  if (data.apiKey)    apiKeyInput.value    = data.apiKey;
}

// ─── Show status message ──────────────────────────────────────────────────────
function showStatus(el, type, msg) {
  el.className = 'status show ' + type;
  el.textContent = msg;
  if (type === 'success') {
    setTimeout(() => el.classList.remove('show'), 4000);
  }
}

function hideStatus(el) {
  el.classList.remove('show');
}

// ─── Save ─────────────────────────────────────────────────────────────────────
saveBtn.addEventListener('click', async () => {
  const url = serverUrlInput.value.trim();
  const key = apiKeyInput.value.trim();

  hideStatus(statusSave);

  if (!url || !key) {
    showStatus(statusSave, 'error', 'Bitte beide Felder ausfüllen.');
    return;
  }

  try {
    new URL(url);
  } catch {
    showStatus(statusSave, 'error', 'Ungültige URL.');
    return;
  }

  await chrome.storage.local.set({ serverUrl: url, apiKey: key });
  showStatus(statusSave, 'success', '✓ Einstellungen gespeichert.');
});

// ─── Test connection ──────────────────────────────────────────────────────────
testBtn.addEventListener('click', async () => {
  const url = serverUrlInput.value.trim();
  const key = apiKeyInput.value.trim();

  hideStatus(statusTest);

  if (!url || !key) {
    showStatus(statusTest, 'error', 'Bitte URL und API-Key eingeben.');
    return;
  }

  try {
    new URL(url);
  } catch {
    showStatus(statusTest, 'error', 'Ungültige URL.');
    return;
  }

  testBtn.disabled = true;
  testBtn.textContent = 'Teste...';
  showStatus(statusTest, 'info', 'Verbinde...');

  try {
    const fetchUrl = url.replace(/\/$/, '') + '/api/connections';
    const res = await fetch(fetchUrl, { headers: { 'X-API-Key': key } });

    if (!res.ok) {
      throw new Error(`HTTP ${res.status} – ${res.statusText}`);
    }

    const data = await res.json();
    const conns = Array.isArray(data) ? data : (data.connections ?? []);
    const webConns = conns.filter(c => c.kind === 'web');
    const total = conns.length;

    showStatus(statusTest, 'success',
      `✓ Verbindung erfolgreich – ${total} Verbindung${total !== 1 ? 'en' : ''} gesamt, davon ${webConns.length} Web-Verbindung${webConns.length !== 1 ? 'en' : ''}.`
    );
  } catch (err) {
    showStatus(statusTest, 'error', 'Fehler: ' + err.message);
  } finally {
    testBtn.disabled = false;
    testBtn.textContent = 'Verbindung testen';
  }
});

// ─── API-Key visibility toggle ────────────────────────────────────────────────
toggleKeyBtn.addEventListener('click', () => {
  if (apiKeyInput.type === 'password') {
    apiKeyInput.type = 'text';
    toggleKeyBtn.textContent = '🙈';
  } else {
    apiKeyInput.type = 'password';
    toggleKeyBtn.textContent = '👁';
  }
});

// ─── Init ─────────────────────────────────────────────────────────────────────
loadSettings();
