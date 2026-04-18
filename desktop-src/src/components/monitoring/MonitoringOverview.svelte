<script lang="ts">
  import { filteredChecks, monitoringServers, monitoringViewMode, toggleViewMode } from '$lib/stores/monitoring';
  import { groupChecksByServer } from '$lib/models/monitoring';
  import MonSummaryCards from './MonSummaryCards.svelte';
  import MonFilterBar from './MonFilterBar.svelte';
  import MonServerGroup from './MonServerGroup.svelte';
  import { t } from '$lib/i18n';

  let groups = $derived(groupChecksByServer($filteredChecks, $monitoringServers));
  let mode = $derived($monitoringViewMode);
</script>

<MonSummaryCards />

<div class="mon-toolbar-row">
  <MonFilterBar />
  <div class="mon-view-switch" role="group" aria-label={$t('monitoring.view.label')}>
    <button
      class="mon-view-btn"
      class:active={mode === 'cards'}
      onclick={() => mode !== 'cards' && toggleViewMode()}
      title={$t('monitoring.view.cards')}
    >
      <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
        <rect x="1" y="1" width="6" height="6" rx="1" />
        <rect x="9" y="1" width="6" height="6" rx="1" />
        <rect x="1" y="9" width="6" height="6" rx="1" />
        <rect x="9" y="9" width="6" height="6" rx="1" />
      </svg>
      <span>{$t('monitoring.view.cards')}</span>
    </button>
    <button
      class="mon-view-btn"
      class:active={mode === 'compact'}
      onclick={() => mode !== 'compact' && toggleViewMode()}
      title={$t('monitoring.view.compact')}
    >
      <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
        <rect x="1" y="2" width="14" height="2" rx="1" />
        <rect x="1" y="7" width="14" height="2" rx="1" />
        <rect x="1" y="12" width="14" height="2" rx="1" />
      </svg>
      <span>{$t('monitoring.view.compact')}</span>
    </button>
  </div>
</div>

<div class="mon-check-list" id="monCheckList">
  {#if groups.length === 0}
    <div class="mon-empty">{$t('monitoring.overview.empty')}</div>
  {:else}
    {#each groups as group (group.serverId ?? '__none')}
      <MonServerGroup {group} />
    {/each}
  {/if}
</div>
