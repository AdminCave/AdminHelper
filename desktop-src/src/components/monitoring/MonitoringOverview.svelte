<script lang="ts">
  import { filteredChecks, monitoringServers } from '$lib/stores/monitoring';
  import { groupChecksByServer } from '$lib/models/monitoring';
  import MonSummaryCards from './MonSummaryCards.svelte';
  import MonFilterBar from './MonFilterBar.svelte';
  import MonServerGroup from './MonServerGroup.svelte';

  let groups = $derived(groupChecksByServer($filteredChecks, $monitoringServers));
</script>

<MonSummaryCards />
<MonFilterBar />

<div class="mon-check-list" id="monCheckList">
  {#if groups.length === 0}
    <div class="mon-empty">Keine Checks gefunden</div>
  {:else}
    {#each groups as group (group.serverId ?? '__none')}
      <MonServerGroup {group} />
    {/each}
  {/if}
</div>
