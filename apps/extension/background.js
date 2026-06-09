// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

'use strict';

const ALARM_NAME = 'refresh';
const REFRESH_INTERVAL_MINUTES = 5;

// ─── One-time migration: move credentials out of cloud-synced storage ─────────
// The API key + server URL used to live in chrome.storage.sync, which roams to
// every device on the browser account. Move them to chrome.storage.local (this
// device only) and remove the cloud copy. Best-effort, idempotent.
async function migrateCredsOutOfSync() {
  try {
    const synced = await chrome.storage.sync.get(['serverUrl', 'apiKey']);
    if (!synced.serverUrl && !synced.apiKey) return;
    const local = await chrome.storage.local.get(['serverUrl', 'apiKey']);
    const patch = {};
    if (!local.serverUrl && synced.serverUrl) patch.serverUrl = synced.serverUrl;
    if (!local.apiKey && synced.apiKey) patch.apiKey = synced.apiKey;
    if (Object.keys(patch).length) await chrome.storage.local.set(patch);
    await chrome.storage.sync.remove(['serverUrl', 'apiKey']);
  } catch (_) {
    /* best-effort */
  }
}

// ─── Setup alarm on install / startup ────────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  migrateCredsOutOfSync();
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: REFRESH_INTERVAL_MINUTES });
});

chrome.runtime.onStartup.addListener(() => {
  migrateCredsOutOfSync();
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: REFRESH_INTERVAL_MINUTES });
});

// ─── Alarm handler ────────────────────────────────────────────────────────────
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== ALARM_NAME) return;
  await fetchAndCache();
});

// ─── Fetch + Cache + Badge ────────────────────────────────────────────────────
async function fetchAndCache() {
  const syncData = await chrome.storage.local.get(['serverUrl', 'apiKey']);
  const { serverUrl, apiKey } = syncData;

  if (!serverUrl || !apiKey) return;

  try {
    const url = serverUrl.replace(/\/$/, '') + '/api/connections';
    const res = await fetch(url, { headers: { 'X-API-Key': apiKey } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    const conns = Array.isArray(data) ? data : (data.connections ?? []);
    const webConns = conns.filter(c => c.kind === 'web');

    await chrome.storage.local.set({
      cachedConnections: { connections: webConns, ts: Date.now() }
    });

    updateBadge(webConns.length);
  } catch {
    // Silently ignore background fetch errors
  }
}

function updateBadge(count) {
  chrome.action.setBadgeText({ text: count > 0 ? String(count) : '' });
  chrome.action.setBadgeBackgroundColor({ color: '#38bdf8' });
  chrome.action.setBadgeTextColor({ color: '#ffffff' });
}

// ─── Initial fetch on service worker activation ───────────────────────────────
fetchAndCache();
