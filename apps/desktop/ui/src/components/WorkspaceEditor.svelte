<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { untrack } from 'svelte';
  import type { SyncMode, WorkspaceDraft, WorkspaceInfo } from '$lib/bridge/types';
  import {
    WORKSPACE_NAME_MAX,
    WORKSPACE_PALETTE,
    hostOf,
    validateDraft,
  } from '$lib/models/workspace';
  import { save } from '$lib/stores/workspace';
  import { errMsg } from '$lib/utils/errors';
  import { t } from '$lib/i18n';
  import Modal from './ui/Modal.svelte';

  interface Props {
    open: boolean;
    /** The closed workspace to edit; null makes a new one. */
    workspace: WorkspaceInfo | null;
    onClose: () => void;
  }
  let { open, workspace, onClose }: Props = $props();

  const KINDS: { kind: SyncMode; label: string }[] = [
    { kind: 'server', label: 'settings.mode.server' },
    { kind: 'sync', label: 'settings.mode.sync' },
    { kind: 'local', label: 'settings.mode.local' },
  ];

  let original = $state<WorkspaceInfo | null>(null);
  let kind = $state<SyncMode>('server');
  let url = $state('');
  // Null until the user types a name; until then a new workspace is named after its host.
  let typedName = $state<string | null>(null);
  let color = $state<string>(WORKSPACE_PALETTE[0]);
  let touched = $state(false);
  let saving = $state(false);
  let saveError = $state('');

  $effect(() => {
    if (!open) return;
    // Seeded as the editor opens: a picker that lists anew meanwhile does not reset the form.
    untrack(() => seed(workspace));
  });

  function seed(ws: WorkspaceInfo | null): void {
    original = ws;
    kind = ws?.kind ?? 'server';
    url = ws?.url ?? '';
    typedName = ws ? ws.name : null;
    color = ws?.color ?? WORKSPACE_PALETTE[0];
    touched = false;
    saving = false;
    saveError = '';
  }

  let isNew = $derived(original === null);
  // The URL as WorkspaceInfo gave it: a user and a password masked as one `***@`, the query
  // values and the fragment masked.
  // Sent back as it came, Rust keeps the stored one (launcher.rs edit).
  let originalUrl = $derived(original?.url?.trim() || null);
  let typedUrl = $derived(kind === 'local' ? null : url.trim() || null);
  // A host is ASCII (the URL parser gives an IDN as punycode): slice counts its characters,
  // and a long one must not block saving.
  let name = $derived(typedName ?? (hostOf(typedUrl) ?? '').slice(0, WORKSPACE_NAME_MAX));
  let urlChanged = $derived(!isNew && typedUrl !== originalUrl);
  let draft = $derived<WorkspaceDraft>({
    ...(original ? { id: original.id } : {}),
    kind,
    name,
    color,
    url: typedUrl,
  });
  // A workspace that has no URL (a migrated server workspace) is renamed without one.
  let check = $derived(validateDraft(draft, { urlRequired: isNew || originalUrl !== null }));
  let showCheck = $derived(!check.ok && (touched || !isNew));
  let identityWarning = $derived(urlChanged && originalUrl !== null);
  // A changed URL replaces the stored one as it stands, `***` included.
  let maskedHint = $derived(
    urlChanged && !!originalUrl?.includes('***') && !!typedUrl?.includes('***'),
  );

  function setKind(next: SyncMode): void {
    kind = next;
    // Rust refuses a local workspace with a URL: what was typed for another kind goes.
    if (next === 'local') url = '';
  }

  async function onSave(): Promise<void> {
    if (!check.ok || saving) return;
    saving = true;
    saveError = '';
    try {
      await save(draft);
      onClose();
    } catch (err) {
      saveError = errMsg(err);
    } finally {
      saving = false;
    }
  }
</script>

<Modal
  {open}
  title={isNew ? $t('workspace.editor.title.new') : $t('workspace.editor.title.edit')}
  {onClose}
>
  <div class="ws-form">
    <label class="field">
      <span class="field-label">{$t('workspace.editor.kind')}</span>
      <select
        value={kind}
        disabled={!isNew}
        onchange={(e) => setKind(e.currentTarget.value as SyncMode)}
      >
        {#each KINDS as option (option.kind)}
          <option value={option.kind}>{$t(option.label)}</option>
        {/each}
      </select>
    </label>

    {#if kind !== 'local'}
      <label class="field">
        <span class="field-label"
          >{kind === 'server' ? $t('settings.serverUrl') : $t('settings.syncUrl')}</span
        >
        <input
          type="url"
          name="url"
          value={url}
          placeholder={kind === 'server'
            ? $t('settings.serverUrl.placeholder')
            : $t('settings.syncUrl.placeholder')}
          oninput={(e) => {
            url = e.currentTarget.value;
            touched = true;
          }}
        />
      </label>
    {/if}

    <label class="field">
      <span class="field-label">{$t('editor.field.name')}</span>
      <input
        type="text"
        name="name"
        value={name}
        oninput={(e) => {
          typedName = e.currentTarget.value;
          touched = true;
        }}
      />
    </label>

    <div class="field">
      <span class="field-label">{$t('workspace.editor.color')}</span>
      <div class="ws-swatches" role="radiogroup" aria-label={$t('workspace.editor.color')}>
        {#each WORKSPACE_PALETTE as swatch (swatch)}
          <button
            type="button"
            role="radio"
            class="ws-swatch"
            class:selected={color === swatch}
            aria-checked={color === swatch}
            aria-label={swatch}
            style:background={swatch}
            onclick={() => (color = swatch)}
          ></button>
        {/each}
      </div>
    </div>

    {#if identityWarning}
      <p class="ws-note ws-warning">{$t('workspace.editor.urlChanged')}</p>
    {/if}
    {#if maskedHint}
      <p class="ws-note ws-warning">{$t('workspace.editor.maskedValues')}</p>
    {/if}
    {#if showCheck}
      <p class="ws-note ws-error">{check.error}</p>
    {/if}
    {#if saveError}
      <p class="ws-note ws-error" role="alert">{saveError}</p>
    {/if}
  </div>

  {#snippet footer()}
    <button class="btn" onclick={onClose} disabled={saving}>{$t('action.cancel')}</button>
    <button class="btn primary" onclick={onSave} disabled={!check.ok || saving}
      >{$t('action.save')}</button
    >
  {/snippet}
</Modal>

<style>
  .ws-form {
    display: flex;
    flex-direction: column;
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
  .field select {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-2) var(--sp-3);
    font-size: 13px;
    font-family: inherit;
  }
  .field input:focus,
  .field select:focus {
    outline: 1px solid var(--accent);
  }
  .ws-swatches {
    display: flex;
    gap: var(--sp-2);
    flex-wrap: wrap;
  }
  .ws-swatch {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: 2px solid transparent;
    padding: 0;
    cursor: pointer;
  }
  .ws-swatch.selected {
    border-color: var(--text);
    box-shadow: 0 0 0 2px var(--bg-panel) inset;
  }
  .ws-note {
    margin: 0;
    font-size: 13px;
  }
  .ws-warning {
    color: var(--warning);
  }
  .ws-error {
    color: var(--danger);
  }
</style>
