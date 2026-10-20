<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import type { SyncMode, WorkspaceInfo } from '$lib/bridge/types';
  import { list, listError, open, refresh, remove } from '$lib/stores/workspace';
  import { errMsg } from '$lib/utils/errors';
  import { t } from '$lib/i18n';
  import { confirmDialog } from './ui/ConfirmDialog.svelte';
  import WorkspaceEditor from './WorkspaceEditor.svelte';

  const KINDS: Record<SyncMode, { label: string; icon: string }> = {
    server: { label: 'settings.mode.server', icon: 'M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01' },
    sync: {
      label: 'settings.mode.sync',
      icon: 'M20 12a8 8 0 0 0-14.3-4.9M4 12a8 8 0 0 0 14.3 4.9M5 3v4h4M19 21v-4h-4',
    },
    local: { label: 'settings.mode.local', icon: 'M3 4h18v12H3zM8 20h8M12 16v4' },
  };
  const DELETE_CONFIRM: Record<SyncMode, string> = {
    server: 'workspace.picker.delete.confirm.server',
    sync: 'workspace.picker.delete.confirm.sync',
    local: 'workspace.picker.delete.confirm.local',
  };

  // Rust gives the note on the migration in the first listing only (launcher.rs list): a
  // listing after a save or a delete must not take it away.
  let migrated = $state(false);
  let chosenId = $state<string | null>(null);
  let opening = $state(false);
  // The name of the workspace being deleted; a server workspace revokes its device first.
  let deleting = $state<string | null>(null);
  let deleted = $state<{ name: string; localOnly: boolean } | null>(null);
  let actionError = $state('');
  let editorOpen = $state(false);
  let editing = $state<WorkspaceInfo | null>(null);
  let listEl = $state<HTMLElement>();

  let workspaces = $derived($list?.workspaces ?? []);
  // The one the user chose; before that, or once it is gone, the one used last, else the first.
  let selected = $derived(
    workspaces.find((ws) => ws.id === chosenId) ??
      workspaces.find((ws) => ws.id === $list?.lastUsed) ??
      workspaces[0] ??
      null,
  );
  let closed = $derived(selected !== null && !selected.open);
  // A delete must not race an open: the launcher ends once a workspace runs.
  let busy = $derived(opening || deleting !== null);

  $effect(() => {
    if ($list?.migratedNotice) migrated = true;
  });

  // The list takes the focus as soon as it is there, so Enter opens the one selected.
  $effect(() => {
    listEl?.focus();
  });

  onMount(() => {
    void refresh();
  });

  const optionId = (id: string) => `workspace-${id}`;

  function move(step: number): void {
    if (!selected) return;
    const at = workspaces.findIndex((ws) => ws.id === selected?.id);
    const next = workspaces[Math.min(workspaces.length - 1, Math.max(0, at + step))];
    chosenId = next.id;
    document.getElementById(optionId(next.id))?.scrollIntoView?.({ block: 'nearest' });
  }

  // One handler on the list for the clicks on its options, as for the keys.
  function onListClick(e: MouseEvent): void {
    const id = (e.target as Element).closest<HTMLElement>('[role="option"]')?.dataset.id;
    if (id) chosenId = id;
  }

  function onKeydown(e: KeyboardEvent): void {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      move(e.key === 'ArrowDown' ? 1 : -1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      void openSelected();
    }
  }

  async function openSelected(): Promise<void> {
    const ws = selected;
    // An open workspace is not opened again: its hint says why.
    if (!ws || ws.open || busy) return;
    opening = true;
    actionError = '';
    deleted = null;
    try {
      await open(ws.id);
      // Stays opening: the launcher ends now, and a second open_workspace of the same id
      // would start a process that ends at once on its lock (exit 3).
    } catch (err) {
      opening = false;
      actionError = errMsg(err);
      void refresh();
    }
  }

  async function deleteSelected(): Promise<void> {
    const ws = selected;
    if (!ws || ws.open || busy) return;
    const ok = await confirmDialog($t(DELETE_CONFIRM[ws.kind], { name: ws.name }), {
      confirmLabel: $t('action.delete'),
    });
    // The question waited for the user; an open may have started meanwhile.
    if (!ok || busy) return;
    deleting = ws.name;
    actionError = '';
    deleted = null;
    try {
      const outcome = await remove(ws.id);
      deleted = { name: ws.name, localOnly: outcome === 'localOnly' };
    } catch (err) {
      actionError = errMsg(err);
    } finally {
      deleting = null;
    }
  }

  function edit(ws: WorkspaceInfo | null): void {
    editing = ws;
    editorOpen = true;
  }

  function closeEditor(): void {
    editorOpen = false;
    listEl?.focus();
  }
</script>

<!-- A workspace window closed meanwhile is no longer open: list anew when the launcher comes back. -->
<svelte:window onfocus={() => void refresh()} />

<div class="picker">
  <h1 class="picker-title">{$t('workspace.picker.title')}</h1>

  {#if migrated}
    <p class="picker-note" role="status" data-msg="migrated">{$t('workspace.picker.migrated')}</p>
  {/if}
  {#if $listError}
    <div class="picker-note picker-failed" role="alert" data-msg="list-failed">
      <span>{$t('workspace.picker.listFailed', { error: $listError })}</span>
      <button class="btn small" onclick={() => void refresh()}>{$t('action.retry')}</button>
    </div>
  {/if}

  {#if $list === null}
    {#if !$listError}<p class="picker-muted">{$t('loading.generic')}</p>{/if}
  {:else if workspaces.length === 0}
    <p class="picker-muted">{$t('workspace.picker.empty')}</p>
  {:else}
    <ul
      class="picker-list"
      role="listbox"
      tabindex="0"
      aria-label={$t('workspace.picker.list')}
      aria-activedescendant={selected ? optionId(selected.id) : undefined}
      bind:this={listEl}
      onkeydown={onKeydown}
      onclick={onListClick}
    >
      {#each workspaces as ws (ws.id)}
        <li
          id={optionId(ws.id)}
          class="picker-item"
          class:selected={ws.id === selected?.id}
          role="option"
          aria-selected={ws.id === selected?.id}
          data-id={ws.id}
        >
          <span class="picker-dot" style:background={ws.color}></span>
          <svg
            class="picker-kind"
            viewBox="0 0 24 24"
            role="img"
            aria-label={$t(KINDS[ws.kind].label)}
          >
            <path d={KINDS[ws.kind].icon} />
          </svg>
          <span class="picker-name">{ws.name}</span>
          <span class="picker-host"
            >{ws.kind === 'local' ? $t('settings.mode.local') : (ws.host ?? '')}</span
          >
          {#if ws.open}<span class="picker-open">{$t('workspace.picker.isOpen')}</span>{/if}
        </li>
      {/each}
    </ul>
  {/if}

  {#if selected?.open}
    <p class="picker-hint" data-msg="is-open">
      {$t('workspace.picker.openHint', { name: selected.name })}
    </p>
  {/if}
  {#if deleting !== null}
    <p class="picker-hint" role="status">{$t('workspace.picker.deleting', { name: deleting })}</p>
  {/if}
  {#if deleted}
    <p class="picker-hint" role="status" data-msg="deleted">
      {$t('workspace.picker.deleted', { name: deleted.name })}
      {#if deleted.localOnly}<span data-msg="deleted-local-only"
          >{$t('workspace.picker.deleted.localOnly')}</span
        >{/if}
    </p>
  {/if}
  {#if actionError}
    <p class="picker-hint picker-error" role="alert" data-msg="action-failed">{actionError}</p>
  {/if}

  <div class="picker-actions">
    <button class="btn" onclick={() => edit(null)} disabled={busy}
      >{$t('workspace.picker.new')}</button
    >
    <button class="btn" onclick={() => edit(selected)} disabled={!closed || busy}
      >{$t('action.edit')}</button
    >
    <button class="btn danger" onclick={deleteSelected} disabled={!closed || busy}
      >{$t('action.delete')}</button
    >
    <span class="picker-spacer"></span>
    <button class="btn primary" onclick={openSelected} disabled={!closed || busy}
      >{opening ? $t('workspace.picker.opening') : $t('workspace.picker.open')}</button
    >
  </div>

  <WorkspaceEditor open={editorOpen} workspace={editing} onClose={closeEditor} />
</div>

<style>
  .picker {
    box-sizing: border-box;
    min-height: 100vh;
    max-width: 640px;
    margin: 0 auto;
    padding: var(--sp-6) var(--sp-5);
    display: flex;
    flex-direction: column;
    gap: var(--sp-4);
  }
  .picker-title {
    margin: 0;
    font-size: var(--text-xl);
    font-weight: 600;
  }
  .picker-note {
    margin: 0;
    padding: var(--sp-3) var(--sp-4);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--accent-bg);
    font-size: var(--text-sm);
  }
  .picker-failed {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    justify-content: space-between;
    background: transparent;
    border-color: var(--danger);
    color: var(--danger);
  }
  .picker-muted {
    margin: 0;
    color: var(--text-muted);
  }
  .picker-list {
    list-style: none;
    margin: 0;
    padding: var(--sp-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    max-height: 60vh;
    overflow-y: auto;
  }
  .picker-list:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }
  .picker-item {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-2) var(--sp-3);
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .picker-item:hover {
    background: var(--hover);
  }
  .picker-item.selected {
    background: var(--accent-bg);
    border-color: var(--accent);
  }
  .picker-dot {
    flex: none;
    width: 12px;
    height: 12px;
    border-radius: 50%;
  }
  .picker-kind {
    flex: none;
    width: 16px;
    height: 16px;
    fill: none;
    stroke: var(--text-muted);
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .picker-name {
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .picker-host {
    margin-left: auto;
    color: var(--text-muted);
    font-size: var(--text-sm);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .picker-open {
    flex: none;
    font-size: var(--text-xs);
    padding: 2px 8px;
    border-radius: var(--radius-pill);
    background: var(--accent-bg);
    color: var(--accent);
  }
  .picker-hint {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .picker-error {
    color: var(--danger);
  }
  .picker-actions {
    display: flex;
    gap: var(--sp-2);
    align-items: center;
  }
  .picker-spacer {
    flex: 1;
  }
</style>
