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
  import { Pencil, Plus } from '@lucide/svelte';
  import ServerConnectionModal from '../ServerConnectionModal.svelte';
  import Button from '../../ui/Button.svelte';
  import Panel from '../../ui/Panel.svelte';
  import Pill from '../../ui/Pill.svelte';
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

{#snippet toolbar()}
  <div class="conn-toolbar">
    <Button size="sm" iconLeft={Plus} data-action="conn-new" onclick={openNew}
      >{$t('infra.conn.add')}</Button
    >
  </div>
{/snippet}

<Panel title={$t('infra.tab.connections')} action={toolbar} pad={6}>
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
          <Pill>{c.kind.toUpperCase()}</Pill>
          <Button size="sm" variant="ghost" iconLeft={Pencil} onclick={() => openEdit(c)}
            >{$t('action.edit')}</Button
          >
        </div>
      {/each}
    </div>
  {/if}
</Panel>

<ServerConnectionModal
  open={modalOpen}
  target={editing}
  {server}
  onClose={() => (modalOpen = false)}
  {onSaved}
/>

<style>
  .conn-toolbar {
    display: flex;
  }
  .muted {
    margin: 0;
    padding: 10px;
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .conn-list {
    display: flex;
    flex-direction: column;
  }
  .conn-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px;
  }
  .conn-row + .conn-row {
    border-top: 1px solid var(--border);
  }
  .conn-info {
    flex: 1;
    min-width: 0;
  }
  .conn-name {
    overflow: hidden;
    color: var(--text-strong);
    font-size: var(--text-sm);
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .conn-meta {
    overflow: hidden;
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 11.5px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
