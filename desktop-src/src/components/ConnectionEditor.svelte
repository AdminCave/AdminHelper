<script lang="ts">
  import type { Connection, ConnectionKind } from '$lib/bridge/types';
  import {
    emptyConnection,
    normalizeConnection,
    parseTags,
    validateConnection,
  } from '$lib/models/connection';
  import { editorState, closeEditor } from '$lib/stores/editor';
  import { upsert, remove } from '$lib/stores/connections';
  import { reportError, showStatus } from '$lib/stores/statusBar';
  import { initiateConnect } from '$lib/stores/connectFlow';
  import * as bridge from '$lib/bridge';

  let form = $state<Connection>(emptyConnection());
  let tagsInput = $state('');
  let isNew = $state(true);

  $effect(() => {
    const st = $editorState;
    if (!st.open) return;
    const base = st.target ? { ...st.target } : emptyConnection();
    form = base;
    tagsInput = (base.tags ?? []).join(', ');
    isNew = st.target === null;
  });

  function collect(): Connection {
    return normalizeConnection({
      ...form,
      tags: parseTags(tagsInput),
      id: form.id,
    });
  }

  async function onSave(): Promise<void> {
    const conn = collect();
    const result = validateConnection(conn);
    if (!result.ok) {
      reportError(result.message ?? 'Validierung fehlgeschlagen');
      return;
    }
    try {
      await upsert(conn);
      showStatus('Gespeichert');
      isNew = false;
      form = conn;
    } catch (err) {
      reportError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onDelete(): Promise<void> {
    if (isNew) return;
    const target = form;
    try {
      await remove(target.id);
      if (target.kind === 'rdp') {
        try {
          await bridge.deletePassword(target);
        } catch {
          // non-fatal
        }
      }
      showStatus('Geloescht');
      closeEditor();
    } catch (err) {
      reportError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onConnect(): Promise<void> {
    const conn = collect();
    const result = validateConnection(conn);
    if (!result.ok) {
      reportError(result.message ?? 'Validierung fehlgeschlagen');
      return;
    }
    await initiateConnect(conn, true);
  }

  function onClose(): void {
    closeEditor();
  }

  function setKind(k: ConnectionKind): void {
    form = { ...form, kind: k };
  }
</script>

{#if $editorState.open}
  <div
    class="editor-overlay"
    role="dialog"
    aria-modal="true"
    onclick={(e) => {
      if (e.target === e.currentTarget) onClose();
    }}
    onkeydown={(e) => e.key === 'Escape' && onClose()}
    tabindex="-1"
  >
    <div class="editor-panel">
      <div class="panel-header">
        <h2 class="panel-title">{isNew ? 'Neue Verbindung' : form.name || 'Verbindung'}</h2>
        <button class="btn ghost small" onclick={onClose} aria-label="Schliessen">×</button>
      </div>

      <div class="form-grid">
        <label class="field">
          <span class="field-label">Name</span>
          <input
            type="text"
            bind:value={form.name}
            placeholder="z.B. Prod-Gateway"
            required
          />
        </label>

        <label class="field">
          <span class="field-label">Typ</span>
          <select value={form.kind} onchange={(e) => setKind((e.currentTarget as HTMLSelectElement).value as ConnectionKind)}>
            <option value="ssh">SSH</option>
            <option value="rdp">RDP</option>
            <option value="web">Web</option>
          </select>
        </label>

        {#if form.kind !== 'web'}
          <label class="field">
            <span class="field-label">Host</span>
            <input type="text" bind:value={form.host} placeholder="host.example.com" />
          </label>

          <label class="field">
            <span class="field-label">Port</span>
            <input
              type="number"
              value={form.port ?? ''}
              oninput={(e) => {
                const v = (e.currentTarget as HTMLInputElement).value;
                form = { ...form, port: v === '' ? null : Number(v) };
              }}
              placeholder={form.kind === 'ssh' ? '22' : '3389'}
            />
          </label>

          <label class="field">
            <span class="field-label">Benutzername</span>
            <input type="text" bind:value={form.username} />
          </label>

          {#if form.kind === 'rdp'}
            <label class="field">
              <span class="field-label">Domain</span>
              <input type="text" bind:value={form.domain} />
            </label>
          {/if}

          {#if form.kind === 'ssh'}
            <label class="field">
              <span class="field-label">Key-Pfad</span>
              <input type="text" bind:value={form.keyPath} placeholder="~/.ssh/id_ed25519" />
            </label>
          {/if}
        {:else}
          <label class="field" style="grid-column: span 2;">
            <span class="field-label">URL</span>
            <input type="url" bind:value={form.url} placeholder="https://..." required />
          </label>

          <label class="field checkbox">
            <input type="checkbox" bind:checked={form.trustCert} />
            <span>Zertifikat vertrauen (Self-Signed)</span>
          </label>
        {/if}

        <label class="field" style="grid-column: span 2;">
          <span class="field-label">Tags (Komma-getrennt)</span>
          <input type="text" bind:value={tagsInput} placeholder="prod, db" />
        </label>

        <label class="field" style="grid-column: span 2;">
          <span class="field-label">Notizen</span>
          <textarea rows="3" bind:value={form.notes}></textarea>
        </label>

        <div class="field" style="grid-column: span 2;">
          <span class="field-label">Zuletzt verwendet</span>
          <div style="color: var(--text-muted);">
            {form.lastUsed ? new Date(form.lastUsed).toLocaleString() : '-'}
          </div>
        </div>
      </div>

      <div class="panel-actions">
        {#if !isNew}
          <button class="btn danger" onclick={onDelete}>Loeschen</button>
        {/if}
        <div style="flex: 1;"></div>
        <button class="btn" onclick={onClose}>Abbrechen</button>
        <button class="btn" onclick={onSave}>Speichern</button>
        <button class="btn primary" onclick={onConnect}>Verbinden</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .editor-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    padding: var(--sp-4);
  }
  .editor-panel {
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    width: 100%;
    max-width: 720px;
    max-height: 90vh;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }
  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--sp-4) var(--sp-5);
    border-bottom: 1px solid var(--border);
  }
  .panel-title {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
  .form-grid {
    padding: var(--sp-5);
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--sp-4);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .field.checkbox {
    flex-direction: row;
    align-items: center;
    gap: var(--sp-2);
  }
  .field-label {
    font-size: 12px;
    color: var(--text-muted);
  }
  .field input,
  .field select,
  .field textarea {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-2) var(--sp-3);
    font-size: 13px;
    font-family: inherit;
  }
  .field input:focus,
  .field select:focus,
  .field textarea:focus {
    outline: 1px solid var(--accent);
  }
  .panel-actions {
    display: flex;
    gap: var(--sp-2);
    padding: var(--sp-4) var(--sp-5);
    border-top: 1px solid var(--border);
    align-items: center;
  }
</style>
