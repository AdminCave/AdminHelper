<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errMsg } from '$lib/utils/errors';
  import type { Connection, ConnectionKind } from '$lib/bridge/types';
  import {
    DEFAULT_PORTS,
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
  import { accelerateScroll, PANEL_FACTOR } from '$lib/utils/scrollAcceleration';
  import { t } from '$lib/i18n';
  import { confirmDialog } from './ui/ConfirmDialog.svelte';
  import Segmented from './ui/Segmented.svelte';
  import Tabs from './ui/Tabs.svelte';
  import { get } from 'svelte/store';
  import { settings, session } from '$lib/stores/session';
  import { infraServers, loadServers } from '$lib/stores/infra';

  type EditorTab = 'general' | 'auth';

  let form = $state<Connection>(emptyConnection());
  let tagsInput = $state('');
  let isNew = $state(true);
  let tab = $state<EditorTab>('general');
  // Servers exist only behind a server session, and only an admin may list them (GET /api/servers)
  // or save a connection; anyone else would get a 403 on every opening.
  const assignServer = $derived($settings?.mode === 'server' && $session?.isAdmin === true);
  const tabs = $derived(
    form.kind === 'web'
      ? []
      : [
          { id: 'general', label: $t('editor.tab.general') },
          { id: 'auth', label: $t('editor.tab.auth') },
        ],
  );
  // An id the list does not know (not loaded, failed, or stale) stays selectable, or saving would drop it.
  const unknownServer = $derived(
    !!form.serverId && !$infraServers.some((s) => s.id === form.serverId),
  );
  // The delete question sits in App's layer, outside this overlay, but the focus stays on
  // "Delete" in here: its Escape reaches the overlay's handler before the dialog's own and
  // would close the editor under the question. A count, as in SettingsModal: a second click
  // replaces the open question, and the first one's end must not lift the second one's guard.
  let asking = 0;

  $effect(() => {
    const st = $editorState;
    if (!st.open) return;
    const base = st.target ? { ...st.target } : emptyConnection();
    form = base;
    tagsInput = (base.tags ?? []).join(', ');
    isNew = st.target === null;
    tab = 'general';
  });

  $effect(() => {
    // The servers load with the infrastructure page; an editor opened before needs them too.
    // Read untracked: loadServers writes the store the list derives from, and an empty answer
    // would start the effect again without end.
    if ($editorState.open && assignServer && get(infraServers).length === 0) void loadServers();
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
      reportError(result.message ?? $t('editor.validation.failed'));
      return;
    }
    try {
      await upsert(conn);
      showStatus($t('editor.status.saved'));
      // Close on save (matches the hub modal). In server mode the saved item
      // gets a server-assigned id on reload, so keeping the editor open with the
      // old client id would create a duplicate on a second save.
      closeEditor();
    } catch (err) {
      reportError(errMsg(err));
    }
  }

  async function onDelete(): Promise<void> {
    if (isNew) return;
    const target = form;
    asking += 1;
    const ok = await confirmDialog(
      $t('editor.deleteConfirm', { name: target.name || target.host }),
      { confirmLabel: $t('action.delete') },
    );
    asking -= 1;
    if (!ok) return;
    try {
      await remove(target.id);
      if (target.kind === 'rdp') {
        try {
          await bridge.deletePassword(target);
        } catch {
          // non-fatal
        }
      }
      showStatus($t('editor.status.deleted'));
      closeEditor();
    } catch (err) {
      reportError(errMsg(err));
    }
  }

  async function onConnect(): Promise<void> {
    const conn = collect();
    const result = validateConnection(conn);
    if (!result.ok) {
      reportError(result.message ?? $t('editor.validation.failed'));
      return;
    }
    await initiateConnect(conn, true);
  }

  function onClose(): void {
    closeEditor();
  }

  function setKind(k: ConnectionKind): void {
    form = { ...form, kind: k };
    tab = 'general';
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
    onkeydown={(e) => {
      if (e.key === 'Escape' && !asking) onClose();
    }}
    tabindex="-1"
  >
    <div class="editor-panel" use:accelerateScroll={PANEL_FACTOR}>
      <div class="panel-header">
        <h2 class="panel-title">
          {isNew ? $t('editor.title.new') : form.name || $t('editor.title.fallback')}
        </h2>
        <button class="btn ghost small" onclick={onClose} aria-label={$t('editor.close')}>×</button>
      </div>

      <div class="editor-head">
        <Segmented
          size="md"
          label={$t('editor.field.kind')}
          value={form.kind}
          onChange={(v) => setKind(v as ConnectionKind)}
          options={[
            { value: 'ssh', label: 'SSH' },
            { value: 'rdp', label: 'RDP' },
            { value: 'web', label: 'Web' },
          ]}
        />
        {#if tabs.length > 0}
          <Tabs
            {tabs}
            value={tab}
            label={$t('editor.tabs')}
            onChange={(id) => (tab = id as EditorTab)}
          />
        {/if}
      </div>

      {#if tab === 'general' || form.kind === 'web'}
        <div class="form-grid" role={tabs.length > 0 ? 'tabpanel' : undefined}>
          <label class="field">
            <span class="field-label">{$t('editor.field.name')}</span>
            <input
              type="text"
              name="name"
              bind:value={form.name}
              placeholder={$t('editor.field.name.placeholder')}
              required
            />
          </label>

          {#if assignServer}
            <label class="field">
              <span class="field-label">{$t('editor.field.server')}</span>
              <select
                name="serverId"
                value={form.serverId ?? ''}
                onchange={(e) => {
                  const v = (e.currentTarget as HTMLSelectElement).value;
                  form = { ...form, serverId: v === '' ? null : v };
                }}
              >
                <option value="">{$t('editor.field.server.none')}</option>
                {#each $infraServers as s (s.id)}
                  <option value={s.id}>{s.name}</option>
                {/each}
                {#if unknownServer}
                  <option value={form.serverId}>{$t('editor.field.server.unknown')}</option>
                {/if}
              </select>
              <span class="field-hint">{$t('editor.field.server.hint')}</span>
            </label>
          {:else}
            <div></div>
          {/if}

          {#if form.kind !== 'web'}
            <label class="field">
              <span class="field-label">{$t('editor.field.host')}</span>
              <input
                type="text"
                name="host"
                bind:value={form.host}
                placeholder={$t('editor.field.host.placeholder')}
              />
            </label>

            <label class="field">
              <span class="field-label">{$t('editor.field.port')}</span>
              <input
                type="number"
                value={form.port ?? ''}
                oninput={(e) => {
                  const v = (e.currentTarget as HTMLInputElement).value;
                  form = { ...form, port: v === '' ? null : Number(v) };
                }}
                placeholder={form.kind === 'ssh'
                  ? String(DEFAULT_PORTS.ssh)
                  : String(DEFAULT_PORTS.rdp)}
              />
            </label>

            <label class="field">
              <span class="field-label">{$t('editor.field.username')}</span>
              <input type="text" bind:value={form.username} />
            </label>

            {#if form.kind === 'rdp'}
              <label class="field">
                <span class="field-label">{$t('editor.field.domain')}</span>
                <input type="text" bind:value={form.domain} />
              </label>
            {/if}
          {:else}
            <label class="field" style="grid-column: span 2;">
              <span class="field-label">{$t('editor.field.url')}</span>
              <input
                type="url"
                bind:value={form.url}
                placeholder={$t('editor.field.url.placeholder')}
                required
              />
            </label>
          {/if}

          <label class="field" style="grid-column: span 2;">
            <span class="field-label">{$t('editor.field.tags')}</span>
            <input
              type="text"
              bind:value={tagsInput}
              placeholder={$t('editor.field.tags.placeholder')}
            />
          </label>

          <label class="field" style="grid-column: span 2;">
            <span class="field-label">{$t('editor.field.notes')}</span>
            <textarea rows="3" bind:value={form.notes}></textarea>
          </label>

          <div class="field" style="grid-column: span 2;">
            <span class="field-label">{$t('editor.field.lastUsed')}</span>
            <!-- A value inside .field, whose global rule styles labels: no caps, no spacing. -->
            <div
              data-testid="editor-last-used"
              style="color: var(--text-muted); text-transform: none; letter-spacing: normal;"
            >
              {form.lastUsed ? new Date(form.lastUsed).toLocaleString() : '-'}
            </div>
          </div>
        </div>
      {:else}
        <div class="form-grid" role="tabpanel">
          {#if form.kind === 'ssh'}
            <label class="field" style="grid-column: span 2;">
              <span class="field-label">{$t('editor.field.keyPath')}</span>
              <input
                type="text"
                bind:value={form.keyPath}
                placeholder={$t('editor.field.keyPath.placeholder')}
              />
            </label>
          {:else}
            <label class="field checkbox" style="grid-column: span 2;">
              <input type="checkbox" bind:checked={form.trustCert} />
              <span>{$t('editor.field.trustCert')}</span>
            </label>
          {/if}
        </div>
      {/if}

      <div class="panel-actions">
        {#if !isNew}
          <button class="btn danger" onclick={onDelete}>{$t('action.delete')}</button>
        {/if}
        <div style="flex: 1;"></div>
        <button class="btn" onclick={onClose}>{$t('action.cancel')}</button>
        <button class="btn save" onclick={onSave}>{$t('action.save')}</button>
        <button class="btn primary" onclick={onConnect}>{$t('action.connect')}</button>
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
  .editor-head {
    display: flex;
    flex-direction: column;
    gap: var(--sp-4);
    padding: var(--sp-4) var(--sp-5) 0;
  }
  .field-hint {
    font-size: 12px;
    color: var(--text-subtle, var(--text-muted));
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
