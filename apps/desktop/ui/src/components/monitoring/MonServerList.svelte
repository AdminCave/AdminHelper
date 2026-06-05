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
    setServerSearch,
  } from '$lib/stores/monitoring';
  import { groupChecksByServerWithSummary } from '$lib/models/monitoring';
  import MonServerListItem from './MonServerListItem.svelte';
  import { t } from '$lib/i18n';

  let groups = $derived(
    groupChecksByServerWithSummary($monitoringChecks, $monitoringServers, $monitoringServerSearch),
  );
  let selected = $derived($selectedServerId);
</script>

<div class="mon-srv-list">
  <div class="mon-srv-search">
    <input
      type="search"
      class="mon-filter-search"
      placeholder={$t('monitoring.serverList.search')}
      value={$monitoringServerSearch}
      oninput={(e) => setServerSearch((e.currentTarget as HTMLInputElement).value)}
    />
  </div>

  <div class="mon-srv-items">
    {#if groups.length === 0}
      <div class="mon-srv-empty">{$t('monitoring.serverList.empty')}</div>
    {:else}
      {#each groups as group (group.key)}
        <MonServerListItem {group} selected={selected === group.key} onSelect={setSelectedServer} />
      {/each}
    {/if}
  </div>
</div>
