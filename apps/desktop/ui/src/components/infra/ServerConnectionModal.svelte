<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Connection, ConnectionKind } from '$lib/api/types';
  import {
    CONNECTION_KINDS,
    emptyConnectionForm,
    connectionToForm,
    parseTags,
    formToPayload,
    validateConnectionForm,
    type ConnectionForm,
  } from '$lib/models/serverConnection';
  import { connectionsApi } from '$lib/api/connections';
  import { session } from '$lib/stores/session';
  import { reportError, showStatus } from '$lib/stores/statusBar';
  import { t } from '$lib/i18n';

  interface Props {
    open: boolean;
    target: Connection | null;
    serverId: string;
    onClose: () => void;
    onSaved: () => void;
  }
  let { open, target, serverId, onClose, onSaved }: Props = $props();

  // Seeded for real by the $effect below whenever the modal opens; the initial
  // value must not capture the reactive `serverId` prop (svelte warning).
  let form = $state<ConnectionForm>(emptyConnectionForm());
  let tagsInput = $state('');
  let confirmDelete = $state(false);
  let saving = $state(false);

  let isNew = $derived(target === null);

  const PORT_HINT: Record<string, string> = { ssh: '22', rdp: '3389', vnc: '5900' };

  $effect(() => {
    if (!open) return;
    form = target ? connectionToForm(target) : emptyConnectionForm(serverId);
    tagsInput = (form.tags ?? []).join(', ');
    confirmDelete = false;
  });

  function errMsg(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  async function onSave(): Promise<void> {
    const s = $session;
    if (!s) return;
    const next: ConnectionForm = { ...form, tags: parseTags(tagsInput) };
    const result = validateConnectionForm(next);
    if (!result.ok) {
      reportError(result.message ?? $t('infra.validation.failed'));
      return;
    }
    saving = true;
    try {
      const payload = formToPayload(next);
      if (next.id) {
        await connectionsApi.update(s, next.id, payload);
        showStatus($t('infra.conn.updated'));
      } else {
        await connectionsApi.create(s, payload);
        showStatus($t('infra.conn.created'));
      }
      onSaved();
      onClose();
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      saving = false;
    }
  }

  async function onDelete(): Promise<void> {
    const s = $session;
    if (!s || !form.id) return;
    if (!confirmDelete) {
      confirmDelete = true;
      return;
    }
    saving = true;
    try {
      await connectionsApi.remove(s, form.id);
      showStatus($t('infra.conn.deleted'));
      onSaved();
      onClose();
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      saving = false;
    }
  }
</script>

{#if open}
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
        <h2 class="panel-title">
          {isNew ? $t('infra.conn.new') : form.name || $t('infra.conn.edit')}
        </h2>
        <button class="btn ghost small" onclick={onClose} aria-label={$t('editor.close')}>×</button>
      </div>

      <div class="form-grid">
        <label class="field">
          <span class="field-label">{$t('infra.field.name')}</span>
          <input type="text" bind:value={form.name} required />
        </label>

        <label class="field">
          <span class="field-label">{$t('infra.conn.kind')}</span>
          <select
            value={form.kind}
            onchange={(e) =>
              (form = {
                ...form,
                kind: (e.currentTarget as HTMLSelectElement).value as ConnectionKind,
              })}
          >
            {#each CONNECTION_KINDS as kind (kind)}
              <option value={kind}>{kind.toUpperCase()}</option>
            {/each}
          </select>
        </label>

        {#if form.kind === 'web'}
          <label class="field" style="grid-column: span 2;">
            <span class="field-label">{$t('infra.conn.url')}</span>
            <input type="url" bind:value={form.url} placeholder="https://" required />
          </label>
          <label class="field checkbox">
            <input type="checkbox" bind:checked={form.trustCert} />
            <span>{$t('infra.conn.trustCert')}</span>
          </label>
        {:else}
          <label class="field">
            <span class="field-label">{$t('infra.conn.host')}</span>
            <input type="text" bind:value={form.host} />
          </label>

          <label class="field">
            <span class="field-label">{$t('infra.conn.port')}</span>
            <input
              type="number"
              value={form.port ?? ''}
              oninput={(e) => {
                const v = (e.currentTarget as HTMLInputElement).value;
                form = { ...form, port: v === '' ? null : Number(v) };
              }}
              placeholder={PORT_HINT[form.kind] ?? ''}
            />
          </label>

          <label class="field">
            <span class="field-label">{$t('infra.conn.username')}</span>
            <input type="text" bind:value={form.username} />
          </label>

          {#if form.kind === 'rdp'}
            <label class="field">
              <span class="field-label">{$t('infra.conn.domain')}</span>
              <input type="text" bind:value={form.domain} />
            </label>
          {/if}

          {#if form.kind === 'ssh'}
            <label class="field">
              <span class="field-label">{$t('infra.conn.keyPath')}</span>
              <input type="text" bind:value={form.keyPath} />
            </label>
          {/if}
        {/if}

        <label class="field" style="grid-column: span 2;">
          <span class="field-label">{$t('infra.field.tags')}</span>
          <input
            type="text"
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
        <button class="btn" onclick={onClose} disabled={saving}>{$t('action.cancel')}</button>
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
