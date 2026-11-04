<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { Info, Monitor, Pencil, Server as ServerIcon } from '@lucide/svelte';
  import type { Server } from '$lib/api/types';
  import { openServerEditor } from '$lib/stores/infra';
  import { t } from '$lib/i18n';
  import Button from '../ui/Button.svelte';
  import MetaList from '../ui/MetaList.svelte';
  import Panel from '../ui/Panel.svelte';
  import Tabs from '../ui/Tabs.svelte';
  import ConnectionsTab from './tabs/ConnectionsTab.svelte';
  import TunnelsTab from './tabs/TunnelsTab.svelte';
  import MonitoringTab from './tabs/MonitoringTab.svelte';
  import ProvisioningTab from './tabs/ProvisioningTab.svelte';

  interface Props {
    server: Server;
  }
  let { server }: Props = $props();

  const tabs = $derived([
    { id: 'overview', label: $t('infra.tab.overview') },
    { id: 'connections', label: $t('infra.tab.connections') },
    { id: 'tunnels', label: $t('infra.tab.tunnels') },
    { id: 'monitoring', label: $t('infra.tab.monitoring') },
    { id: 'provisioning', label: $t('infra.tab.provisioning') },
  ]);
  let active = $state('overview');

  const windows = $derived((server.osType ?? '').toLowerCase().includes('windows'));
  const rows = $derived([
    { key: $t('infra.field.hostname'), value: server.hostname },
    { key: $t('infra.field.osType'), value: server.osType || '—', mono: false },
    { key: $t('infra.field.tags'), value: (server.tags ?? []).join(', ') || '—' },
    { key: $t('infra.field.notes'), value: server.notes || '—', mono: false },
  ]);
</script>

<div class="srv-detail">
  <header class="srv-head">
    <span class="srv-tile" aria-hidden="true">
      {#if windows}<Monitor size={22} />{:else}<ServerIcon size={22} />{/if}
    </span>
    <div class="srv-head-main">
      <h2 class="srv-name">{server.name}</h2>
      <div class="srv-sub">{server.hostname}</div>
    </div>
    <Button
      size="sm"
      variant="ghost"
      iconLeft={Pencil}
      data-action="server-edit"
      onclick={() => openServerEditor(server)}>{$t('action.edit')}</Button
    >
  </header>

  <Tabs {tabs} bind:value={active} label={server.name} />

  <!-- Re-key on server.id so the data-fetching tabs remount on a server switch;
       this guards against an in-flight load() of the old server overwriting the
       new server's state once it resolves out of order. -->
  <div class="srv-tab-body">
    {#key server.id}
      {#if active === 'overview'}
        <div class="srv-overview">
          <Panel title={$t('infra.overview.title')} icon={Info}>
            <MetaList {rows} />
          </Panel>
        </div>
      {:else if active === 'connections'}
        <ConnectionsTab {server} />
      {:else if active === 'tunnels'}
        <TunnelsTab {server} />
      {:else if active === 'monitoring'}
        <MonitoringTab {server} />
      {:else if active === 'provisioning'}
        <ProvisioningTab {server} />
      {/if}
    {/key}
  </div>
</div>

<style>
  .srv-detail {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    padding: 20px 28px 0;
  }
  .srv-head {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    gap: 14px;
    padding-bottom: 16px;
  }
  .srv-tile {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    width: 48px;
    height: 48px;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface-inset);
    color: var(--text-strong);
  }
  .srv-head-main {
    flex: 1 1 220px;
    min-width: 0;
  }
  .srv-name {
    margin: 0;
    overflow: hidden;
    color: var(--text-strong);
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.02em;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .srv-sub {
    margin-top: 4px;
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 12px;
  }
  .srv-tab-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 20px 0 28px;
  }
  .srv-overview {
    max-width: 640px;
  }
  .srv-overview :global(dd) {
    white-space: pre-wrap;
  }
</style>
