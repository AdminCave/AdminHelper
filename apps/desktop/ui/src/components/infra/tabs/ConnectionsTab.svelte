<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errMsg } from '$lib/utils/errors';
  import { onMount } from 'svelte';
  import type { Connection, Server } from '$lib/api/types';
  import { connectionsApi } from '$lib/api/connections';
  import { session } from '$lib/stores/session';
  import { refreshFromServer } from '$lib/stores/connections';
  import { reportError } from '$lib/stores/statusBar';
  import ServerConnectionModal from '../ServerConnectionModal.svelte';
  import { t } from '$lib/i18n';

  interface Props {
    server: Server;
  }
  let { server }: Props = $props();

  let items = $state<Connection[]>([]);
  let loading = $state(false);
  let modalOpen = $state(false);
  let editing = $state<Connection | null>(null);

  async function load(): Promise<void> {
    const s = $session;
    if (!s) return;
    loading = true;
    try {
      const all = await connectionsApi.list(s);
      items = (Array.isArray(all) ? all : [])
        .filter((c) => c.serverId === server.id)
        .sort((a, b) => a.name.localeCompare(b.name));
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      loading = false;
    }
  }

  function openNew(): void {
    editing = null;
    modalOpen = true;
  }
  function openEdit(c: Connection): void {
    editing = c;
    modalOpen = true;
  }

  // After a hub write, refresh this tab's list and the launcher's cached list so
  // both stay in sync (the launcher caches server connections locally).
  async function onSaved(): Promise<void> {
    await load();
    await refreshFromServer();
  }

  function meta(c: Connection): string {
    if (c.kind === 'web') return c.url || '—';
    const host = c.host || '—';
    const user = c.username ? `${c.username}@` : '';
    return c.port ? `${user}${host}:${c.port}` : `${user}${host}`;
  }

  onMount(load);
</script>

<div class="conn-tab">
  <div class="conn-toolbar">
    <button class="btn primary small" onclick={openNew}>+ {$t('infra.conn.add')}</button>
  </div>

  {#if loading}
    <p class="muted">{$t('loading.generic')}</p>
  {:else if items.length === 0}
    <p class="muted">{$t('infra.conn.empty')}</p>
  {:else}
    <div class="conn-list">
      {#each items as c (c.id)}
        <div class="conn-row">
          <div class="conn-info">
            <div class="conn-name">{c.name}</div>
            <div class="conn-meta">{meta(c)}</div>
          </div>
          <span class="conn-kind">{c.kind.toUpperCase()}</span>
          <button class="btn small" onclick={() => openEdit(c)}>{$t('action.edit')}</button>
        </div>
      {/each}
    </div>
  {/if}
</div>

<ServerConnectionModal
  open={modalOpen}
  target={editing}
  serverId={server.id}
  onClose={() => (modalOpen = false)}
  {onSaved}
/>

<style>
  .conn-tab {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .conn-toolbar {
    display: flex;
    justify-content: flex-end;
  }
  .muted {
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .conn-list {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
  }
  .conn-row {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-2) var(--sp-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
  }
  .conn-info {
    flex: 1;
    min-width: 0;
  }
  .conn-name {
    font-size: var(--text-sm);
    font-weight: 600;
  }
  .conn-meta {
    font-size: var(--text-xs);
    color: var(--text-muted);
  }
  .conn-kind {
    font-size: var(--text-xs);
    color: var(--text-muted);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 0 var(--sp-2);
  }
</style>
