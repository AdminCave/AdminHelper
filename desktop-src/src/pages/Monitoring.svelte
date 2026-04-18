<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import {
    monitoring,
    activateMonitoring,
    deactivateMonitoring,
    setTab,
  } from '$lib/stores/monitoring';
  import MonitoringOverview from '../components/monitoring/MonitoringOverview.svelte';
  import MonitoringAlerts from '../components/monitoring/MonitoringAlerts.svelte';
  import MonitoringLog from '../components/monitoring/MonitoringLog.svelte';

  onMount(() => {
    activateMonitoring();
  });

  onDestroy(() => {
    deactivateMonitoring();
  });

  let tab = $derived($monitoring.tab);
</script>

<div class="section-toolbar">
  <div class="mon-tabs">
    <button class="mon-tab" class:active={tab === 'overview'} onclick={() => setTab('overview')}>
      Uebersicht
    </button>
    <button class="mon-tab" class:active={tab === 'alerts'} onclick={() => setTab('alerts')}>
      Alerts
    </button>
    <button class="mon-tab" class:active={tab === 'log'} onclick={() => setTab('log')}>
      Log
    </button>
  </div>
</div>

<div class="mon-tab-content" data-tab="overview">
  {#if tab === 'overview'}<MonitoringOverview />{/if}
</div>
<div class="mon-tab-content" data-tab="alerts" class:hidden={tab !== 'alerts'}>
  {#if tab === 'alerts'}<MonitoringAlerts />{/if}
</div>
<div class="mon-tab-content" data-tab="log" class:hidden={tab !== 'log'}>
  {#if tab === 'log'}<MonitoringLog />{/if}
</div>
