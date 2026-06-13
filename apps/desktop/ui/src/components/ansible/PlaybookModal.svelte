<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Playbook } from '$lib/api/types';
  import {
    emptyPlaybookForm,
    playbookToForm,
    parseTags,
    formToInput,
    validatePlaybookForm,
    type PlaybookForm,
  } from '$lib/models/playbook';
  import { ansibleApi } from '$lib/api/ansible';
  import { session } from '$lib/stores/session';
  import { reportError, showStatus } from '$lib/stores/statusBar';
  import { t } from '$lib/i18n';

  interface Props {
    open: boolean;
    target: Playbook | null;
    onClose: () => void;
    onSaved: () => void;
  }
  let { open, target, onClose, onSaved }: Props = $props();

  let form = $state<PlaybookForm>(emptyPlaybookForm());
  let tagsInput = $state('');
  let confirmDelete = $state(false);
  let saving = $state(false);

  let isNew = $derived(target === null);

  $effect(() => {
    if (!open) return;
    const pb = target;
    confirmDelete = false;
    if (pb) {
      form = playbookToForm(pb, '');
      tagsInput = (pb.tags ?? []).join(', ');
      const s = $session;
      if (s) {
        ansibleApi
          .fetchContent(s, pb.id)
          .then((data) => {
            form = { ...form, content: data.content };
          })
          .catch((err) => reportError(errMsg(err)));
      }
    } else {
      form = emptyPlaybookForm();
      tagsInput = '';
    }
  });

  function errMsg(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  async function onSave(): Promise<void> {
    const s = $session;
    if (!s) return;
    const next: PlaybookForm = { ...form, tags: parseTags(tagsInput) };
    const result = validatePlaybookForm(next);
    if (!result.ok) {
      reportError(result.message ?? $t('infra.validation.failed'));
      return;
    }
    saving = true;
    try {
      const input = formToInput(next);
      if (next.id) {
        await ansibleApi.updatePlaybook(s, next.id, input);
        showStatus($t('ansible.edit.updated'));
      } else {
        await ansibleApi.createPlaybook(s, input);
        showStatus($t('ansible.edit.created'));
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
      await ansibleApi.removePlaybook(s, form.id);
      showStatus($t('ansible.edit.deleted'));
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
          {isNew ? $t('ansible.edit.new') : form.name || $t('ansible.edit.edit')}
        </h2>
        <button class="btn ghost small" onclick={onClose} aria-label={$t('editor.close')}>×</button>
      </div>

      <div class="form-grid">
        <label class="field">
          <span class="field-label">{$t('ansible.edit.name')}</span>
          <input type="text" bind:value={form.name} required />
        </label>

        <label class="field">
          <span class="field-label">{$t('ansible.edit.filename')}</span>
          <input type="text" bind:value={form.filename} placeholder="deploy.yml" required />
        </label>

        <label class="field" style="grid-column: span 2;">
          <span class="field-label">{$t('ansible.edit.description')}</span>
          <input type="text" bind:value={form.description} />
        </label>

        <label class="field" style="grid-column: span 2;">
          <span class="field-label">{$t('infra.field.tags')}</span>
          <input
            type="text"
            bind:value={tagsInput}
            placeholder={$t('infra.field.tags.placeholder')}
          />
        </label>

        <label class="field" style="grid-column: span 2;">
          <span class="field-label">{$t('ansible.edit.content')}</span>
          <textarea class="yaml" rows="14" spellcheck="false" bind:value={form.content}></textarea>
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
    max-width: 760px;
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
  .field textarea.yaml {
    font-family: var(--font-mono, monospace);
    resize: vertical;
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
