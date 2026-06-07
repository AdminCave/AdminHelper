<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '$lib/i18n';
  import { servers } from '$lib/stores/servers';
  import { connections } from '$lib/stores/connections';
  import { showToast } from '$lib/stores/notifications';
  import { extractAllTags } from '$lib/utils/tags';
  import { worstStatusForServer } from '$lib/utils/monitoring';
  import * as monApi from '$lib/api/monitoring';
  import Button from '$lib/components/ui/Button.svelte';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import { confirmDialog } from '$lib/components/ui/ConfirmDialog.svelte';
  import ServerModal from '$modals/ServerModal.svelte';
  import ServerProvisionModal from '$modals/ServerProvisionModal.svelte';
  import type { Server, Connection, MonCheckSummary } from '$lib/api/types';

  let search = $state('');
  let tagFilter = $state('');
  let expanded = $state<Set<string>>(new Set());
  let monitorChecks = $state<MonCheckSummary[]>([]);
  let modalOpen = $state(false);
  let editing = $state<Server | null>(null);
  let provisionOpen = $state(false);
  let provisionServer = $state<Server | null>(null);

  onMount(() => {
    load();
  });

  async function load() {
    try {
      await Promise.all([servers.refresh(), connections.refresh()]);
      try {
        monitorChecks = await monApi.listStatus();
      } catch {
        monitorChecks = [];
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
    }
  }

  const allTags = $derived(extractAllTags($servers));

  const filtered = $derived.by(() => {
    const q = search.toLowerCase();
    return $servers.filter((s) => {
      if (tagFilter && !(s.tags ?? []).includes(tagFilter)) return false;
      if (!q) return true;
      if (s.name.toLowerCase().includes(q)) return true;
      if (s.hostname.toLowerCase().includes(q)) return true;
      if ((s.tags ?? []).some((tag) => tag.toLowerCase().includes(q))) return true;
      if (
        (s.connections ?? []).some(
          (c) => c.name.toLowerCase().includes(q) || (c.host ?? '').toLowerCase().includes(q),
        )
      )
        return true;
      return false;
    });
  });

  const standalone = $derived.by(() => {
    // eslint-disable-next-line svelte/prefer-svelte-reactivity -- transient builder inside $derived.by, not reactive state
    const assigned = new Set<string>();
    $servers.forEach((s) => (s.connections ?? []).forEach((c) => assigned.add(c.id)));
    return $connections.filter((c) => !assigned.has(c.id) && !c.serverId);
  });

  function toggleCard(id: string) {
    expanded = new Set(
      expanded.has(id) ? [...expanded].filter((x) => x !== id) : [...expanded, id],
    );
  }

  function openCreate() {
    editing = null;
    modalOpen = true;
  }

  function openEdit(s: Server) {
    editing = s;
    modalOpen = true;
  }

  function openProvision(s: Server) {
    provisionServer = s;
    provisionOpen = true;
  }

  async function handleClose() {
    modalOpen = false;
    await load();
  }

  async function removeServer(s: Server) {
    if (!(await confirmDialog($t('confirm.server.delete'), { confirmLabel: $t('action.delete') })))
      return;
    try {
      await servers.remove(s.id);
      showToast($t('toast.server.deleted'));
      await load();
    } catch (err) {
      showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
    }
  }

  function hostDisplay(c: Connection): string {
    return c.kind === 'web' ? (c.url ?? '–') : (c.host ?? '–');
  }
</script>

<div class="page active">
  <div class="page-header">
    <div>
      <div class="page-title">{$t('page.servers.title')}</div>
      <div class="page-subtitle">{$t('page.servers.subtitle')}</div>
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
      <Button variant="primary" onclick={openCreate}>{$t('page.servers.add')}</Button>
    </div>
  </div>

  <div class="panel" style="display:flex;flex-direction:column;gap:12px">
    {#each filtered as s (s.id)}
      {@const status = worstStatusForServer(monitorChecks, s.id)}
      {@const open = expanded.has(s.id)}
      {@const conns = s.connections ?? []}
      <div class="server-card">
        <div
          class="server-card-header"
          role="button"
          tabindex="0"
          onclick={() => toggleCard(s.id)}
          onkeydown={(e) => e.key === 'Enter' && toggleCard(s.id)}
        >
          <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0">
            <span class="server-chevron" class:open>&#x25B6;</span>
            {#if status}
              <span class="monitor-dot monitor-{status}" title="Monitoring: {status}"></span>
            {/if}
            <div style="min-width:0">
              <strong>{s.name}</strong>
              <span style="color:var(--text-muted);font-size:13px;margin-left:8px">
                {s.hostname}{s.osType ? ` · ${s.osType}` : ''}
              </span>
            </div>
            <span style="color:var(--text-muted);font-size:12px;flex-shrink:0">
              {$t(conns.length !== 1 ? 'page.servers.connCountPlural' : 'page.servers.connCount', {
                count: conns.length,
              })}
            </span>
            {#if (s.tags ?? []).length}
              <div style="display:flex;gap:4px;flex-shrink:0">
                {#each s.tags ?? [] as tag (tag)}
                  <span class="tag">{tag}</span>
                {/each}
              </div>
            {/if}
          </div>
          <div
            style="display:flex;gap:6px;flex-shrink:0"
            role="toolbar"
            tabindex="-1"
            onclick={(e) => e.stopPropagation()}
            onkeydown={(e) => e.stopPropagation()}
          >
            <button class="btn small" onclick={() => openEdit(s)}>{$t('action.edit')}</button>
            <button class="btn small ghost" onclick={() => openProvision(s)}>Provision</button>
            <button class="btn small ghost" onclick={() => removeServer(s)}>
              {$t('action.delete')}
            </button>
          </div>
        </div>
        {#if open}
          <div class="server-card-body">
            {#if conns.length === 0}
              <div style="padding:12px;color:var(--text-muted);font-size:13px">
                {$t('page.servers.noConnections')}
              </div>
            {:else}
              <table class="data-table" style="margin:0">
                <thead>
                  <tr>
                    <th>{$t('table.type')}</th>
                    <th>{$t('table.name')}</th>
                    <th>{$t('table.hostUrl')}</th>
                    <th>{$t('table.port')}</th>
                    <th>{$t('table.user')}</th>
                  </tr>
                </thead>
                <tbody>
                  {#each conns as c (c.id)}
                    <tr>
                      <td><span class="badge badge-{c.kind}">{c.kind.toUpperCase()}</span></td>
                      <td><strong>{c.name}</strong></td>
                      <td
                        style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                      >
                        {hostDisplay(c)}
                      </td>
                      <td>{c.port ?? '–'}</td>
                      <td>{c.username ?? '–'}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            {/if}
          </div>
        {/if}
      </div>
    {/each}

    {#if standalone.length > 0}
      {@const open = expanded.has('__standalone')}
      <div class="server-card">
        <div
          class="server-card-header"
          role="button"
          tabindex="0"
          onclick={() => toggleCard('__standalone')}
          onkeydown={(e) => e.key === 'Enter' && toggleCard('__standalone')}
        >
          <div style="display:flex;align-items:center;gap:10px;flex:1">
            <span class="server-chevron" class:open>&#x25B6;</span>
            <strong style="color:var(--text-muted)">{$t('page.servers.noServer')}</strong>
            <span style="color:var(--text-muted);font-size:12px">
              {$t(
                standalone.length !== 1 ? 'page.servers.connCountPlural' : 'page.servers.connCount',
                { count: standalone.length },
              )}
            </span>
          </div>
        </div>
        {#if open}
          <div class="server-card-body">
            <table class="data-table" style="margin:0">
              <thead>
                <tr>
                  <th>{$t('table.type')}</th>
                  <th>{$t('table.name')}</th>
                  <th>{$t('table.hostUrl')}</th>
                  <th>{$t('table.port')}</th>
                  <th>{$t('table.user')}</th>
                </tr>
              </thead>
              <tbody>
                {#each standalone as c (c.id)}
                  <tr>
                    <td><span class="badge badge-{c.kind}">{c.kind.toUpperCase()}</span></td>
                    <td><strong>{c.name}</strong></td>
                    <td>{hostDisplay(c)}</td>
                    <td>{c.port ?? '–'}</td>
                    <td>{c.username ?? '–'}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>
    {/if}

    {#if filtered.length === 0 && standalone.length === 0}
      <EmptyState message={$t('page.servers.empty')} />
    {/if}
  </div>
</div>

<ServerModal open={modalOpen} {editing} onClose={handleClose} />
<ServerProvisionModal
  open={provisionOpen}
  server={provisionServer}
  onClose={() => (provisionOpen = false)}
/>
