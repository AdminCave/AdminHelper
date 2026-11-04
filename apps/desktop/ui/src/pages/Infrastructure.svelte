<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { Plus } from '@lucide/svelte';
  import {
    infraServers,
    infraSearch,
    infraSelectedId,
    infraSelectedServer,
    setInfraSearch,
    setSelectedServer,
    openServerEditor,
    activateInfra,
  } from '$lib/stores/infra';
  import { filterServers } from '$lib/models/infra';
  import { t } from '$lib/i18n';
  import Button from '../components/ui/Button.svelte';
  import SearchField from '../components/ui/SearchField.svelte';
  import Tag from '../components/ui/Tag.svelte';
  import ServerDetail from '../components/infra/ServerDetail.svelte';
  import ServerModal from '../components/infra/ServerModal.svelte';

  let servers = $derived(filterServers($infraServers, $infraSearch));

  // Auto-select the first server once the list is loaded and nothing is chosen,
  // so the detail pane isn't empty on first open. Selecting flips the guard, so
  // this doesn't loop.
  $effect(() => {
    if (!$infraSelectedId && servers.length > 0) {
      setSelectedServer(servers[0].id);
    }
  });

  onMount(() => {
    activateInfra();
  });
</script>

<div class="infra-page">
  <div class="infra">
    <aside class="infra-rail">
      <div class="infra-toolbar">
        <SearchField
          value={$infraSearch}
          placeholder={$t('infra.search.placeholder')}
          label={$t('infra.search.placeholder')}
          size="sm"
          oninput={(e) => setInfraSearch((e.currentTarget as HTMLInputElement).value)}
          onClear={() => setInfraSearch('')}
        />
        <Button
          size="sm"
          variant="primary"
          iconLeft={Plus}
          data-action="server-new"
          onclick={() => openServerEditor(null)}>{$t('infra.addServer')}</Button
        >
      </div>

      <div class="infra-list">
        {#if servers.length === 0}
          <div class="infra-empty">{$t('infra.empty')}</div>
        {:else}
          {#each servers as server (server.id)}
            <button
              type="button"
              class="srv-item"
              class:active={$infraSelectedId === server.id}
              aria-current={$infraSelectedId === server.id ? 'true' : undefined}
              onclick={() => setSelectedServer(server.id)}
            >
              <span class="srv-item-name">{server.name}</span>
              <span class="srv-item-host">{server.hostname}</span>
              {#if (server.tags ?? []).length > 0}
                <span class="srv-item-tags">
                  {#each server.tags ?? [] as tag (tag)}
                    <Tag size="sm" tone="neutral">{tag}</Tag>
                  {/each}
                </span>
              {/if}
            </button>
          {/each}
        {/if}
      </div>
    </aside>

    <section class="infra-detail">
      {#if $infraSelectedServer}
        {#key $infraSelectedServer.id}
          <ServerDetail server={$infraSelectedServer} />
        {/key}
      {:else}
        <div class="infra-prompt">{$t('infra.selectPrompt')}</div>
      {/if}
    </section>
  </div>
</div>

<ServerModal />

<style>
  .infra-page {
    container-type: inline-size;
    height: 100%;
    min-height: 0;
  }
  .infra {
    display: flex;
    height: 100%;
    min-height: 0;
  }
  .infra-rail {
    flex: 0 0 240px;
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    border-right: 1px solid var(--border);
  }
  .infra-toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 14px;
    border-bottom: 1px solid var(--border);
  }
  .infra-list {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 8px;
  }
  .infra-empty,
  .infra-prompt {
    color: var(--text-muted);
    font-size: var(--text-sm);
    padding: var(--sp-5) var(--sp-3);
    text-align: center;
  }
  .srv-item {
    display: flex;
    flex-direction: column;
    gap: 5px;
    width: 100%;
    padding: 10px 12px;
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .srv-item:hover {
    background: var(--surface-hover);
  }
  .srv-item.active {
    border-color: var(--border-strong);
    background: var(--surface-raised);
  }
  .srv-item-name {
    max-width: 100%;
    overflow: hidden;
    color: var(--text-strong);
    font-size: var(--text-sm);
    font-weight: 500;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .srv-item.active .srv-item-name {
    font-weight: 600;
  }
  .srv-item-host {
    max-width: 100%;
    overflow: hidden;
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 11.5px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .srv-item-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .infra-detail {
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }
  @container (min-width: 1000px) {
    .infra-rail {
      flex-basis: 300px;
    }
  }
</style>
