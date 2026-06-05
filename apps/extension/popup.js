// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

'use strict';

// ─── State ────────────────────────────────────────────────────────────────────
let allConnections = [];
let currentView = 'list'; // 'list' | 'tags'
let searchQuery = '';
let isLoading = false;

// ─── DOM refs ─────────────────────────────────────────────────────────────────
const setupView       = document.getElementById('setup-view');
const mainView        = document.getElementById('main-view');
const setupUrl        = document.getElementById('setup-url');
const setupKey        = document.getElementById('setup-key');
const setupSaveBtn    = document.getElementById('setup-save');
const setupError      = document.getElementById('setup-error');
const searchInput     = document.getElementById('search-input');
const btnListView     = document.getElementById('btn-list-view');
const btnTagView      = document.getElementById('btn-tag-view');
const btnRefresh      = document.getElementById('btn-refresh');
const btnOptions      = document.getElementById('btn-options');
const listViewEl      = document.getElementById('list-view');
const tagViewEl       = document.getElementById('tag-view');
const connList        = document.getElementById('conn-list');
const treeGroups      = document.getElementById('tree-groups');
const stateEmpty      = document.getElementById('state-empty');
const stateError      = document.getElementById('state-error');
const stateErrorMsg   = document.getElementById('state-error-msg');
const stateLoading    = document.getElementById('state-loading');
const footerCount     = document.getElementById('footer-count');
const footerTime      = document.getElementById('footer-time');
const stateErrorSettings = document.getElementById('state-error-settings');

// ─── Helpers ──────────────────────────────────────────────────────────────────
function parseTags(raw) {
  if (!raw) return [];
  return raw.split(',').map(t => t.trim()).filter(Boolean);
}

function formatRelTime(ts) {
  if (!ts) return '';
  const diff = Math.floor((Date.now() - ts) / 1000);
  if (diff < 5)   return 'gerade eben';
  if (diff < 60)  return `vor ${diff} Sek.`;
  if (diff < 3600) return `vor ${Math.floor(diff / 60)} Min.`;
  if (diff < 86400) return `vor ${Math.floor(diff / 3600)} Std.`;
  return `vor ${Math.floor(diff / 86400)} Tagen`;
}

function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function showState(which) {
  stateEmpty.classList.add('hidden');
  stateError.classList.add('hidden');
  stateLoading.classList.add('hidden');
  if (which) document.getElementById('state-' + which).classList.remove('hidden');
}

// ─── Filtering ────────────────────────────────────────────────────────────────
function filterConnections(conns, query) {
  if (!query) return conns;
  const q = query.toLowerCase();
  return conns.filter(c => {
    const tags = parseTags(c.tags).join(' ');
    return (
      (c.name  ?? '').toLowerCase().includes(q) ||
      (c.url   ?? '').toLowerCase().includes(q) ||
      (c.notes ?? '').toLowerCase().includes(q) ||
      tags.toLowerCase().includes(q)
    );
  });
}

// ─── Card rendering ───────────────────────────────────────────────────────────
function buildCard(conn) {
  const tags = parseTags(conn.tags);
  const tagsHtml = tags.map(t =>
    `<span class="tag">${escapeHtml(t)}</span>`
  ).join('');

  const el = document.createElement('div');
  el.className = 'card';
  el.dataset.url = conn.url ?? '';
  el.innerHTML = `
    <div class="card-main">
      <div class="card-title">${escapeHtml(conn.name)}</div>
      <div class="card-url">${escapeHtml(conn.url ?? '')}</div>
      ${tags.length ? `<div class="card-tags">${tagsHtml}</div>` : ''}
    </div>
    <span class="open-icon">↗</span>
  `;
  el.addEventListener('click', () => openUrl(conn.url));
  return el;
}

function openUrl(url) {
  if (!url) return;
  chrome.tabs.create({ url });
}

// ─── List View ────────────────────────────────────────────────────────────────
function renderList(conns) {
  connList.innerHTML = '';
  if (!conns.length) {
    showState('empty');
    return;
  }
  showState(null);
  const frag = document.createDocumentFragment();
  conns.forEach(c => frag.appendChild(buildCard(c)));
  connList.appendChild(frag);
}

// ─── Tag Group View ───────────────────────────────────────────────────────────
function renderTags(conns) {
  treeGroups.innerHTML = '';
  if (!conns.length) {
    showState('empty');
    return;
  }
  showState(null);

  // Group by tags; connections with no tags go under "(keine Tags)"
  const groups = new Map();
  conns.forEach(c => {
    const tags = parseTags(c.tags);
    if (!tags.length) {
      if (!groups.has('')) groups.set('', []);
      groups.get('').push(c);
    } else {
      tags.forEach(t => {
        if (!groups.has(t)) groups.set(t, []);
        groups.get(t).push(c);
      });
    }
  });

  const frag = document.createDocumentFragment();
  groups.forEach((groupConns, tagName) => {
    const label = tagName || '(keine Tags)';
    const storageKey = 'group_open_' + tagName;
    const isOpen = sessionStorage.getItem(storageKey) !== 'false';

    const group = document.createElement('div');
    group.className = 'tree-group' + (isOpen ? ' open' : '');

    const header = document.createElement('div');
    header.className = 'tree-header';
    header.innerHTML = `
      <span class="tree-chevron">▸</span>
      <span class="tree-tag-label">${escapeHtml(label)}</span>
      <span class="tree-count">${groupConns.length}</span>
    `;
    header.addEventListener('click', () => {
      group.classList.toggle('open');
      sessionStorage.setItem(storageKey, group.classList.contains('open') ? 'true' : 'false');
    });

    const body = document.createElement('div');
    body.className = 'tree-body';

    const list = document.createElement('div');
    list.className = 'tree-list';

    groupConns.forEach(c => {
      const node = document.createElement('div');
      node.className = 'tree-node';
      node.appendChild(buildCard(c));
      list.appendChild(node);
    });

    body.appendChild(list);
    group.appendChild(header);
    group.appendChild(body);
    frag.appendChild(group);
  });

  treeGroups.appendChild(frag);
}

// ─── Render dispatch ──────────────────────────────────────────────────────────
function render() {
  const filtered = filterConnections(allConnections, searchQuery);

  if (currentView === 'list') {
    listViewEl.classList.remove('hidden');
    tagViewEl.classList.add('hidden');
    renderList(filtered);
  } else {
    listViewEl.classList.add('hidden');
    tagViewEl.classList.remove('hidden');
    renderTags(filtered);
  }

  const n = filtered.length;
  const total = allConnections.length;
  footerCount.textContent = n === total
    ? `${n} Verbindung${n !== 1 ? 'en' : ''}`
    : `${n} von ${total} Verbindungen`;
}

// ─── Loading from cache + server ──────────────────────────────────────────────
async function loadFromServer(serverUrl, apiKey) {
  const url = serverUrl.replace(/\/$/, '') + '/api/connections?api_key=' + encodeURIComponent(apiKey);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  const conns = Array.isArray(data) ? data : (data.connections ?? []);
  return conns.filter(c => c.kind === 'web');
}

async function refresh(serverUrl, apiKey, silent = false) {
  if (!silent) {
    btnRefresh.classList.add('spinning');
  }
  try {
    const webConns = await loadFromServer(serverUrl, apiKey);
    allConnections = webConns;

    // Cache
    const cacheEntry = { connections: webConns, ts: Date.now() };
    await chrome.storage.local.set({ cachedConnections: cacheEntry });

    // Badge
    updateBadge(webConns.length);

    render();
    footerTime.textContent = formatRelTime(Date.now());
    showState(null);
  } catch (err) {
    if (!silent) {
      stateErrorMsg.textContent = 'Fehler: ' + err.message;
      showState('error');
    }
  } finally {
    btnRefresh.classList.remove('spinning');
  }
}

function updateBadge(count) {
  chrome.action.setBadgeText({ text: count > 0 ? String(count) : '' });
  chrome.action.setBadgeBackgroundColor({ color: '#38bdf8' });
}

// ─── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  // Load view preference
  const localData = await chrome.storage.local.get(['viewMode', 'cachedConnections']);
  if (localData.viewMode) {
    currentView = localData.viewMode;
  }

  // Load config
  const syncData = await chrome.storage.sync.get(['serverUrl', 'apiKey']);
  const serverUrl = syncData.serverUrl;
  const apiKey    = syncData.apiKey;

  if (!serverUrl || !apiKey) {
    // Show setup
    setupView.classList.remove('hidden');
    mainView.classList.add('hidden');
    return;
  }

  // Show main
  setupView.classList.add('hidden');
  mainView.classList.remove('hidden');
  mainView.style.display = 'flex';

  // Set toggle state
  if (currentView === 'tags') {
    btnTagView.classList.add('active');
    btnListView.classList.remove('active');
  }

  // Load from cache first
  if (localData.cachedConnections) {
    const cache = localData.cachedConnections;
    allConnections = cache.connections ?? [];
    showState(null);
    render();
    footerTime.textContent = formatRelTime(cache.ts);
  } else {
    showState('loading');
  }

  // Then fetch fresh data
  await refresh(serverUrl, apiKey, /*silent=*/ allConnections.length > 0);
}

// ─── Event listeners ──────────────────────────────────────────────────────────
searchInput.addEventListener('input', () => {
  searchQuery = searchInput.value;
  render();
});

btnListView.addEventListener('click', () => {
  currentView = 'list';
  btnListView.classList.add('active');
  btnTagView.classList.remove('active');
  chrome.storage.local.set({ viewMode: 'list' });
  render();
});

btnTagView.addEventListener('click', () => {
  currentView = 'tags';
  btnTagView.classList.add('active');
  btnListView.classList.remove('active');
  chrome.storage.local.set({ viewMode: 'tags' });
  render();
});

btnRefresh.addEventListener('click', async () => {
  const syncData = await chrome.storage.sync.get(['serverUrl', 'apiKey']);
  if (syncData.serverUrl && syncData.apiKey) {
    await refresh(syncData.serverUrl, syncData.apiKey);
  }
});

btnOptions.addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
});

stateErrorSettings.addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
});

// Setup form
setupSaveBtn.addEventListener('click', async () => {
  const url = setupUrl.value.trim();
  const key = setupKey.value.trim();

  if (!url || !key) {
    setupError.textContent = 'Bitte beide Felder ausfüllen.';
    setupError.classList.add('show');
    return;
  }

  // Validate URL
  try { new URL(url); } catch {
    setupError.textContent = 'Ungültige URL.';
    setupError.classList.add('show');
    return;
  }

  setupError.classList.remove('show');
  setupSaveBtn.disabled = true;
  setupSaveBtn.textContent = 'Verbinde...';

  try {
    const webConns = await loadFromServer(url, key);
    await chrome.storage.sync.set({ serverUrl: url, apiKey: key });
    allConnections = webConns;
    await chrome.storage.local.set({ cachedConnections: { connections: webConns, ts: Date.now() } });
    updateBadge(webConns.length);

    // Switch to main view
    setupView.classList.add('hidden');
    mainView.classList.remove('hidden');
    mainView.style.display = 'flex';
    showState(null);
    render();
    footerTime.textContent = formatRelTime(Date.now());
  } catch (err) {
    setupError.textContent = 'Fehler: ' + err.message;
    setupError.classList.add('show');
  } finally {
    setupSaveBtn.disabled = false;
    setupSaveBtn.textContent = 'Speichern & Laden';
  }
});

// Listen for storage changes (e.g. saved from options page)
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'sync' && (changes.serverUrl || changes.apiKey)) {
    init();
  }
});

// ─── Start ────────────────────────────────────────────────────────────────────
init();
