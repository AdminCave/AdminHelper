<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '$lib/i18n';
  import { connections } from '$lib/stores/connections';
  import { servers } from '$lib/stores/servers';
  import { isAdmin } from '$lib/stores/auth';
  import { showToast } from '$lib/stores/notifications';
  import { extractAllTags } from '$lib/utils/tags';
  import * as connApi from '$lib/api/connections';
  import Button from '$lib/components/ui/Button.svelte';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import { confirmDialog } from '$lib/components/ui/ConfirmDialog.svelte';
  import ConnectionModal from '$modals/ConnectionModal.svelte';
  import ImportModal from '$modals/ImportModal.svelte';
  import type { Connection } from '$lib/api/types';

  let search = $state('');
  let tagFilter = $state('');
  let modalOpen = $state(false);
  let editing = $state<Connection | null>(null);
  let importOpen = $state(false);

  onMount(() => {
    load();
  });

  async function load() {
    try {
      await Promise.all([connections.refresh(), servers.refresh()]);
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  const allTags = $derived(extractAllTags($connections));

  const filtered = $derived.by(() => {
    const q = search.toLowerCase();
    return $connections.filter((c) => {
      if (tagFilter && !(c.tags ?? []).includes(tagFilter)) return false;
      if (!q) return true;
      const fields = [
        c.name,
        c.host ?? '',
        c.url ?? '',
        c.kind ?? '',
        c.username ?? '',
        (c.tags ?? []).join(' '),
      ];
      return fields.some((f) => f.toLowerCase().includes(q));
    });
  });

  function hostDisplay(c: Connection): string {
    return c.kind === 'web' ? (c.url ?? '–') : (c.host ?? '–');
  }

  function openCreate() {
    editing = null;
    modalOpen = true;
  }

  function openEdit(c: Connection) {
    editing = c;
    modalOpen = true;
  }

  async function handleClose() {
    modalOpen = false;
    await load();
  }

  async function removeConnection(c: Connection) {
    if (
      !(await confirmDialog($t('confirm.connection.delete'), { confirmLabel: $t('action.delete') }))
    )
      return;
    try {
      await connections.remove(c.id);
      showToast($t('toast.connection.deleted'));
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  async function exportAll() {
    try {
      const blob = await connApi.exportConnections();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'connections.json';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }
</script>

<div class="page active">
  <div class="page-header">
    <div>
      <div class="page-title">{$t('page.connections.title')}</div>
      <div class="page-subtitle">
        {#if filtered.length === 0}
          {$t('page.connections.none')}
        {:else}
          {$t(
            $connections.length !== 1 ? 'page.connections.countPlural' : 'page.connections.count',
            {
              count: $connections.length,
            },
          )}
        {/if}
      </div>
    </div>
    <div style="display:flex;gap:10px;align-items:center">
      <select class="filter-select" bind:value={tagFilter}>
        <option value="">{$t('label.allTags')}</option>
        {#each allTags as tag (tag)}
          <option value={tag}>{tag}</option>
        {/each}
      </select>
      <input
        type="search"
        class="search-input"
        placeholder={$t('action.searchDots')}
        bind:value={search}
      />
      {#if $isAdmin}
        <button class="btn ghost" onclick={exportAll}>{$t('action.export')}</button>
        <button class="btn ghost" onclick={() => (importOpen = true)}>{$t('action.import')}</button>
        <Button variant="primary" onclick={openCreate}>{$t('page.connections.add')}</Button>
      {/if}
    </div>
  </div>

  <div class="panel">
    {#if filtered.length === 0}
      <EmptyState message={$t('page.connections.empty')} />
    {:else}
      <table class="data-table">
        <thead>
          <tr>
            <th>{$t('table.name')}</th>
            <th>{$t('table.type')}</th>
            <th>{$t('page.connections.hostUrl')}</th>
            <th>{$t('table.port')}</th>
            <th>{$t('table.user')}</th>
            <th>{$t('label.tags')}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {#each filtered as c (c.id)}
            <tr>
              <td><strong>{c.name}</strong></td>
              <td><span class="badge badge-{c.kind}">{c.kind.toUpperCase()}</span></td>
              <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                {hostDisplay(c)}
              </td>
              <td>{c.port ?? '–'}</td>
              <td>{c.username ?? '–'}</td>
              <td>
                {#if (c.tags ?? []).length}
                  <div style="display:flex;gap:4px;flex-wrap:wrap">
                    {#each c.tags ?? [] as tag (tag)}
                      <span class="tag">{tag}</span>
                    {/each}
                  </div>
                {/if}
              </td>
              <td>
                {#if $isAdmin}
                  <div style="display:flex;gap:6px">
                    <button class="btn small" onclick={() => openEdit(c)}>
                      {$t('action.edit')}
                    </button>
                    <button class="btn small ghost" onclick={() => removeConnection(c)}>
                      {$t('action.delete')}
                    </button>
                  </div>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</div>

<ConnectionModal open={modalOpen} {editing} onClose={handleClose} />
<ImportModal open={importOpen} onClose={() => (importOpen = false)} onImported={load} />
