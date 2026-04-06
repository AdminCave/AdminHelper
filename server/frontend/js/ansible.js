/* Simple Remote Manager – Ansible Playbooks */
'use strict';

// ── State ─────────────────────────────────────────────────────────────────
state.ansiblePlaybooks = [];
state.editingPlaybookId = null;
state.ansibleTagFilter = '';

// ── Load ──────────────────────────────────────────────────────────────────
async function loadAnsible() {
  try {
    state.ansiblePlaybooks = await get('/api/ansible/playbooks');
    renderTagFilter('ansibleTagSelect', state.ansiblePlaybooks, 'ansibleTagFilter');
    renderAnsible();
  } catch (err) {
    toast(err.message, 'error');
  }
}

document.getElementById('ansibleTagSelect').addEventListener('change', function () {
  state.ansibleTagFilter = this.value;
  renderAnsible();
});

const ansibleSearch = document.getElementById('ansibleSearch');
ansibleSearch.addEventListener('input', renderAnsible);

// ── Render ────────────────────────────────────────────────────────────────
function renderAnsible() {
  const q = ansibleSearch.value.toLowerCase();
  const container = document.getElementById('ansibleList');
  const empty = document.getElementById('ansibleEmpty');
  container.innerHTML = '';

  let filtered = state.ansiblePlaybooks.filter(p =>
    !q ||
    p.name.toLowerCase().includes(q) ||
    p.filename.toLowerCase().includes(q) ||
    (p.description || '').toLowerCase().includes(q) ||
    (p.tags || []).some(t => t.toLowerCase().includes(q))
  );

  if (state.ansibleTagFilter) {
    filtered = filtered.filter(p => (p.tags || []).includes(state.ansibleTagFilter));
  }

  if (filtered.length === 0) {
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  filtered.forEach(p => {
    const card = document.createElement('div');
    card.className = 'server-card';
    const tags = (p.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join(' ');
    const desc = p.description ? `<span style="color:var(--text-soft);font-size:13px;margin-left:8px">${esc(p.description)}</span>` : '';
    const updated = p.updatedAt ? new Date(p.updatedAt).toLocaleDateString('de-DE') : '';
    const created = p.createdAt ? new Date(p.createdAt).toLocaleDateString('de-DE') : '';
    const dateLabel = updated || created;

    card.innerHTML = `
      <div class="server-card-header" onclick="togglePlaybookCard(this)">
        <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0">
          <span class="server-chevron">&#x25B6;</span>
          <div style="min-width:0">
            <strong>${esc(p.name)}</strong>
            ${desc}
          </div>
          <span style="color:var(--text-soft);font-size:12px;flex-shrink:0">${esc(p.filename)}</span>
          ${dateLabel ? `<span style="color:var(--text-soft);font-size:11px;flex-shrink:0">${dateLabel}</span>` : ''}
          ${tags ? `<div style="display:flex;gap:4px;flex-shrink:0">${tags}</div>` : ''}
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0" onclick="event.stopPropagation()">
          <button class="btn small" onclick="editPlaybook('${esc(p.id)}')">Bearbeiten</button>
          <button class="btn small ghost" onclick="deletePlaybook('${esc(p.id)}')">L\u00f6schen</button>
        </div>
      </div>
      <div class="server-card-body hidden">
        <pre style="margin:0;padding:12px;font-size:13px;overflow-x:auto;background:var(--bg-card);border-radius:6px" id="pbPreview_${esc(p.id)}"><span style="color:var(--text-soft)">Inhalt wird geladen...</span></pre>
      </div>
    `;
    container.appendChild(card);
  });
}

function togglePlaybookCard(headerEl) {
  const body = headerEl.nextElementSibling;
  const chevron = headerEl.querySelector('.server-chevron');
  const wasHidden = body.classList.contains('hidden');
  body.classList.toggle('hidden');
  chevron.classList.toggle('open');

  // Inhalt beim ersten Aufklappen laden
  if (wasHidden) {
    const pre = body.querySelector('pre');
    if (pre && pre.dataset.loaded !== 'true') {
      const id = pre.id.replace('pbPreview_', '');
      loadPlaybookPreview(id, pre);
    }
  }
}

async function loadPlaybookPreview(id, preEl) {
  try {
    const data = await get(`/api/ansible/playbooks/${id}/content`);
    preEl.textContent = data.content;
    preEl.dataset.loaded = 'true';
  } catch {
    preEl.textContent = 'Fehler beim Laden des Inhalts.';
  }
}

// ── Modal ─────────────────────────────────────────────────────────────────
document.getElementById('addPlaybookBtn').addEventListener('click', () => openPlaybookModal(null));

async function openPlaybookModal(playbook) {
  state.editingPlaybookId = playbook ? playbook.id : null;
  document.getElementById('playbookModalTitle').textContent = playbook ? 'Playbook bearbeiten' : 'Neues Playbook';
  document.getElementById('pbName').value = playbook?.name || '';
  document.getElementById('pbFilename').value = playbook?.filename || '';
  document.getElementById('pbDescription').value = playbook?.description || '';
  document.getElementById('pbTags').value = (playbook?.tags || []).join(', ');

  if (playbook) {
    try {
      const data = await get(`/api/ansible/playbooks/${playbook.id}/content`);
      document.getElementById('pbContent').value = data.content;
    } catch {
      document.getElementById('pbContent').value = '';
    }
  } else {
    document.getElementById('pbContent').value = '';
  }

  showModal('playbookModal');
}

document.getElementById('playbookForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = {
    name: document.getElementById('pbName').value.trim(),
    filename: document.getElementById('pbFilename').value.trim(),
    description: document.getElementById('pbDescription').value.trim(),
    tags: parseTags(document.getElementById('pbTags').value),
    content: document.getElementById('pbContent').value,
  };
  try {
    if (state.editingPlaybookId) {
      await put(`/api/ansible/playbooks/${state.editingPlaybookId}`, data);
      toast('Playbook gespeichert');
    } else {
      await post('/api/ansible/playbooks', data);
      toast('Playbook erstellt');
    }
    closeModal('playbookModal');
    await loadAnsible();
  } catch (err) {
    toast(err.message, 'error');
  }
});

function editPlaybook(id) {
  const p = state.ansiblePlaybooks.find(p => p.id === id);
  if (p) openPlaybookModal(p);
}

async function deletePlaybook(id) {
  if (!confirm('Playbook wirklich l\u00f6schen?')) return;
  try {
    await del(`/api/ansible/playbooks/${id}`);
    toast('Playbook gel\u00f6scht');
    await loadAnsible();
  } catch (err) {
    toast(err.message, 'error');
  }
}
