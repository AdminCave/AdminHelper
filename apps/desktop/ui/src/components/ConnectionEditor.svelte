<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

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
  import { accelerateScroll, PANEL_FACTOR } from '$lib/utils/scrollAcceleration';
  import { t } from '$lib/i18n';

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
      reportError(result.message ?? $t('editor.validation.failed'));
      return;
    }
    try {
      await upsert(conn);
      showStatus($t('editor.status.saved'));
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
      showStatus($t('editor.status.deleted'));
      closeEditor();
    } catch (err) {
      reportError(err instanceof Error ? err.message : String(err));
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
    <div class="editor-panel" use:accelerateScroll={PANEL_FACTOR}>
      <div class="panel-header">
        <h2 class="panel-title">
          {isNew ? $t('editor.title.new') : form.name || $t('editor.title.fallback')}
        </h2>
        <button class="btn ghost small" onclick={onClose} aria-label={$t('editor.close')}>×</button>
      </div>

      <div class="form-grid">
        <label class="field">
          <span class="field-label">{$t('editor.field.name')}</span>
          <input
            type="text"
            bind:value={form.name}
            placeholder={$t('editor.field.name.placeholder')}
            required
          />
        </label>

        <label class="field">
          <span class="field-label">{$t('editor.field.kind')}</span>
          <select
            value={form.kind}
            onchange={(e) =>
              setKind((e.currentTarget as HTMLSelectElement).value as ConnectionKind)}
          >
            <option value="ssh">SSH</option>
            <option value="rdp">RDP</option>
            <option value="web">Web</option>
          </select>
        </label>

        {#if form.kind !== 'web'}
          <label class="field">
            <span class="field-label">{$t('editor.field.host')}</span>
            <input
              type="text"
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
              placeholder={form.kind === 'ssh' ? '22' : '3389'}
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

            <label class="field checkbox">
              <input type="checkbox" bind:checked={form.trustCert} />
              <span>{$t('editor.field.trustCert')}</span>
            </label>
          {/if}

          {#if form.kind === 'ssh'}
            <label class="field">
              <span class="field-label">{$t('editor.field.keyPath')}</span>
              <input
                type="text"
                bind:value={form.keyPath}
                placeholder={$t('editor.field.keyPath.placeholder')}
              />
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
          <div style="color: var(--text-muted);">
            {form.lastUsed ? new Date(form.lastUsed).toLocaleString() : '-'}
          </div>
        </div>
      </div>

      <div class="panel-actions">
        {#if !isNew}
          <button class="btn danger" onclick={onDelete}>{$t('action.delete')}</button>
        {/if}
        <div style="flex: 1;"></div>
        <button class="btn" onclick={onClose}>{$t('action.cancel')}</button>
        <button class="btn" onclick={onSave}>{$t('action.save')}</button>
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
