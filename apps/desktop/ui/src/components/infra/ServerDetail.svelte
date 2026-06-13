<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Server } from '$lib/api/types';
  import { openServerEditor } from '$lib/stores/infra';
  import { t } from '$lib/i18n';
  import ConnectionsTab from './tabs/ConnectionsTab.svelte';
  import ProvisioningTab from './tabs/ProvisioningTab.svelte';

  interface Props {
    server: Server;
  }
  let { server }: Props = $props();

  type Tab = 'overview' | 'connections' | 'tunnels' | 'monitoring' | 'provisioning';
  const tabs: { id: Tab; labelKey: string }[] = [
    { id: 'overview', labelKey: 'infra.tab.overview' },
    { id: 'connections', labelKey: 'infra.tab.connections' },
    { id: 'tunnels', labelKey: 'infra.tab.tunnels' },
    { id: 'monitoring', labelKey: 'infra.tab.monitoring' },
    { id: 'provisioning', labelKey: 'infra.tab.provisioning' },
  ];
  let active = $state<Tab>('overview');
</script>

<div class="srv-detail">
  <header class="srv-head">
    <div class="srv-head-main">
      <h2 class="srv-name">{server.name}</h2>
      <div class="srv-sub">{server.hostname}</div>
    </div>
    <button class="btn small" onclick={() => openServerEditor(server)}>
      {$t('action.edit')}
    </button>
  </header>

  <nav class="srv-tabs">
    {#each tabs as tab (tab.id)}
      <button class="srv-tab" class:active={active === tab.id} onclick={() => (active = tab.id)}>
        {$t(tab.labelKey)}
      </button>
    {/each}
  </nav>

  <div class="srv-tab-body">
    {#if active === 'overview'}
      <dl class="meta-list">
        <dt>{$t('infra.field.hostname')}</dt>
        <dd>{server.hostname}</dd>
        <dt>{$t('infra.field.osType')}</dt>
        <dd>{server.osType || '—'}</dd>
        <dt>{$t('infra.field.tags')}</dt>
        <dd>
          {#if (server.tags ?? []).length > 0}
            <span class="tag-row">
              {#each server.tags ?? [] as tag (tag)}
                <span class="tag">{tag}</span>
              {/each}
            </span>
          {:else}
            —
          {/if}
        </dd>
        <dt>{$t('infra.field.notes')}</dt>
        <dd class="notes">{server.notes || '—'}</dd>
      </dl>
    {:else if active === 'connections'}
      <ConnectionsTab {server} />
    {:else if active === 'provisioning'}
      <ProvisioningTab {server} />
    {:else}
      <div class="tab-placeholder">{$t('infra.tab.placeholder')}</div>
    {/if}
  </div>
</div>

<style>
  .srv-detail {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
  }
  .srv-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--sp-3);
    padding-bottom: var(--sp-4);
    border-bottom: 1px solid var(--border);
  }
  .srv-head-main {
    min-width: 0;
  }
  .srv-name {
    margin: 0;
    font-size: var(--text-xl);
    font-weight: 600;
  }
  .srv-sub {
    color: var(--text-muted);
    font-size: var(--text-sm);
    margin-top: var(--sp-1);
  }
  .srv-tabs {
    display: flex;
    gap: var(--sp-1);
    border-bottom: 1px solid var(--border);
    margin-top: var(--sp-3);
  }
  .srv-tab {
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--text-muted);
    padding: var(--sp-2) var(--sp-3);
    font-size: var(--text-sm);
    font-family: inherit;
    cursor: pointer;
  }
  .srv-tab:hover {
    color: var(--text);
  }
  .srv-tab.active {
    color: var(--text);
    border-bottom-color: var(--accent);
  }
  .srv-tab-body {
    padding-top: var(--sp-4);
    overflow-y: auto;
    min-height: 0;
  }
  .meta-list {
    display: grid;
    grid-template-columns: 160px 1fr;
    gap: var(--sp-2) var(--sp-4);
    margin: 0;
  }
  .meta-list dt {
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .meta-list dd {
    margin: 0;
    font-size: var(--text-sm);
  }
  .meta-list dd.notes {
    white-space: pre-wrap;
  }
  .tag-row {
    display: inline-flex;
    flex-wrap: wrap;
    gap: var(--sp-1);
  }
  .tag {
    background: var(--accent-bg);
    color: var(--accent);
    border-radius: var(--radius-sm);
    padding: 1px var(--sp-2);
    font-size: var(--text-xs);
  }
  .tab-placeholder {
    color: var(--text-muted);
    font-size: var(--text-sm);
    padding: var(--sp-6) 0;
    text-align: center;
  }
</style>
