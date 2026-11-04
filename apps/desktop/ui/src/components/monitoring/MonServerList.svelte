<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import {
    monitoringChecks,
    monitoringServers,
    selectedServerId,
    setSelectedServer,
    monitoringServerSearch,
  } from '$lib/stores/monitoring';
  import { groupChecksByServerWithSummary } from '$lib/models/monitoring';
  import MonServerListItem from './MonServerListItem.svelte';
  import { t } from '$lib/i18n';

  // The search field lives in the overview toolbar and filters list and grid alike.
  let groups = $derived(
    groupChecksByServerWithSummary($monitoringChecks, $monitoringServers, $monitoringServerSearch),
  );
  let selected = $derived($selectedServerId);
</script>

<div class="mon-srv-list">
  {#if groups.length === 0}
    <div class="mon-srv-empty">{$t('monitoring.serverList.empty')}</div>
  {:else}
    {#each groups as group (group.key)}
      <MonServerListItem {group} selected={selected === group.key} onSelect={setSelectedServer} />
    {/each}
  {/if}
</div>

<style>
  .mon-srv-list {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .mon-srv-empty {
    padding: var(--sp-4);
    color: var(--text-muted);
    font-size: var(--text-sm);
    text-align: center;
  }
</style>
