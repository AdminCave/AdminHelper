<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
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

<div class="infra">
  <aside class="infra-master">
    <div class="infra-toolbar">
      <input
        type="search"
        class="infra-search"
        placeholder={$t('infra.search.placeholder')}
        value={$infraSearch}
        oninput={(e) => setInfraSearch((e.currentTarget as HTMLInputElement).value)}
      />
      <button class="btn primary small" onclick={() => openServerEditor(null)}>
        + {$t('infra.addServer')}
      </button>
    </div>

    <div class="infra-list">
      {#if servers.length === 0}
        <div class="infra-empty">{$t('infra.empty')}</div>
      {:else}
        {#each servers as server (server.id)}
          <button
            class="srv-item"
            class:active={$infraSelectedId === server.id}
            onclick={() => setSelectedServer(server.id)}
          >
            <span class="srv-item-name">{server.name}</span>
            <span class="srv-item-host">{server.hostname}</span>
            {#if (server.tags ?? []).length > 0}
              <span class="srv-item-tags">
                {#each server.tags ?? [] as tag (tag)}
                  <span class="srv-item-tag">{tag}</span>
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

<ServerModal />

<style>
  .infra {
    display: flex;
    gap: var(--sp-4);
    height: 100%;
    min-height: 0;
  }
  .infra-master {
    width: 300px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    min-height: 0;
    border-right: 1px solid var(--border);
    padding-right: var(--sp-4);
  }
  .infra-toolbar {
    display: flex;
    gap: var(--sp-2);
    margin-bottom: var(--sp-3);
  }
  .infra-search {
    flex: 1;
    min-width: 0;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-2) var(--sp-3);
    font-size: var(--text-sm);
    font-family: inherit;
  }
  .infra-search:focus {
    outline: 1px solid var(--accent);
  }
  .infra-list {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
    min-height: 0;
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
    gap: 2px;
    align-items: flex-start;
    text-align: left;
    background: none;
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    padding: var(--sp-2) var(--sp-3);
    cursor: pointer;
    font-family: inherit;
    color: var(--text);
  }
  .srv-item:hover {
    background: var(--bg-surface);
  }
  .srv-item.active {
    background: var(--accent-bg);
    border-color: var(--accent);
  }
  .srv-item-name {
    font-size: var(--text-sm);
    font-weight: 600;
  }
  .srv-item-host {
    font-size: var(--text-xs);
    color: var(--text-muted);
  }
  .srv-item-tags {
    display: inline-flex;
    flex-wrap: wrap;
    gap: var(--sp-1);
    margin-top: 2px;
  }
  .srv-item-tag {
    background: var(--bg-surface);
    color: var(--text-muted);
    border-radius: var(--radius-sm);
    padding: 0 var(--sp-2);
    font-size: var(--text-xs);
  }
  .infra-detail {
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }
</style>
