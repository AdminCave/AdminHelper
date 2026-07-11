<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { ServerInput } from '$lib/api/types';
  import {
    emptyServerInput,
    serverToInput,
    parseTags,
    normalizeServerInput,
    validateServerInput,
  } from '$lib/models/infra';
  import { serverEditor, closeServerEditor, saveServer, deleteServer } from '$lib/stores/infra';
  import { reportError } from '$lib/stores/statusBar';
  import { t } from '$lib/i18n';

  let form = $state<ServerInput>(emptyServerInput());
  let tagsInput = $state('');
  let editingId = $state<string | null>(null);
  let isNew = $state(true);
  let confirmDelete = $state(false);
  let saving = $state(false);

  $effect(() => {
    const st = $serverEditor;
    if (!st.open) return;
    if (st.target) {
      form = serverToInput(st.target);
      tagsInput = (st.target.tags ?? []).join(', ');
      editingId = st.target.id;
      isNew = false;
    } else {
      form = emptyServerInput();
      tagsInput = '';
      editingId = null;
      isNew = true;
    }
    confirmDelete = false;
  });

  async function onSave(): Promise<void> {
    const input = normalizeServerInput({ ...form, tags: parseTags(tagsInput) });
    const result = validateServerInput(input);
    if (!result.ok) {
      reportError(result.message ?? $t('infra.validation.failed'));
      return;
    }
    saving = true;
    const ok = await saveServer(input, editingId);
    saving = false;
    if (ok) closeServerEditor();
  }

  async function onDelete(): Promise<void> {
    if (isNew || !editingId) return;
    if (!confirmDelete) {
      confirmDelete = true;
      return;
    }
    saving = true;
    const ok = await deleteServer(editingId);
    saving = false;
    if (ok) closeServerEditor();
  }
</script>

{#if $serverEditor.open}
  <div
    class="editor-overlay"
    role="dialog"
    aria-modal="true"
    onclick={(e) => {
      if (e.target === e.currentTarget) closeServerEditor();
    }}
    onkeydown={(e) => e.key === 'Escape' && closeServerEditor()}
    tabindex="-1"
  >
    <div class="editor-panel">
      <div class="panel-header">
        <h2 class="panel-title">
          {isNew ? $t('infra.server.new') : form.name || $t('infra.server.edit')}
        </h2>
        <button class="btn ghost small" onclick={closeServerEditor} aria-label={$t('editor.close')}
          >×</button
        >
      </div>

      <div class="form-grid">
        <label class="field">
          <span class="field-label">{$t('infra.field.name')}</span>
          <input
            type="text"
            name="name"
            bind:value={form.name}
            placeholder={$t('infra.field.name.placeholder')}
            required
          />
        </label>

        <label class="field">
          <span class="field-label">{$t('infra.field.hostname')}</span>
          <input
            type="text"
            name="hostname"
            bind:value={form.hostname}
            placeholder={$t('infra.field.hostname.placeholder')}
            required
          />
        </label>

        <label class="field">
          <span class="field-label">{$t('infra.field.osType')}</span>
          <input
            type="text"
            name="osType"
            value={form.os_type ?? ''}
            oninput={(e) => {
              const v = (e.currentTarget as HTMLInputElement).value;
              form = { ...form, os_type: v === '' ? null : v };
            }}
            placeholder={$t('infra.field.osType.placeholder')}
          />
        </label>

        <label class="field">
          <span class="field-label">{$t('infra.field.tags')}</span>
          <input
            type="text"
            name="tags"
            bind:value={tagsInput}
            placeholder={$t('infra.field.tags.placeholder')}
          />
        </label>

        <label class="field" style="grid-column: span 2;">
          <span class="field-label">{$t('infra.field.notes')}</span>
          <textarea rows="3" bind:value={form.notes}></textarea>
        </label>
      </div>

      <div class="panel-actions">
        {#if !isNew}
          <button class="btn danger" onclick={onDelete} disabled={saving}>
            {confirmDelete ? $t('infra.server.confirmDelete') : $t('action.delete')}
          </button>
        {/if}
        <div style="flex: 1;"></div>
        <button class="btn" onclick={closeServerEditor} disabled={saving}
          >{$t('action.cancel')}</button
        >
        <button class="btn primary" onclick={onSave} disabled={saving}>{$t('action.save')}</button>
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
    max-width: 640px;
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
  .field-label {
    font-size: 12px;
    color: var(--text-muted);
  }
  .field input,
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
