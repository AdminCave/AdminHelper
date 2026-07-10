<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

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
  import MonitoringTemplates from '../components/monitoring/MonitoringTemplates.svelte';
  import MonitoringLog from '../components/monitoring/MonitoringLog.svelte';
  import { t } from '$lib/i18n';

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
    <button
      class="mon-tab"
      class:active={tab === 'overview'}
      data-tab="overview"
      onclick={() => setTab('overview')}
    >
      {$t('monitoring.tab.overview')}
    </button>
    <button
      class="mon-tab"
      class:active={tab === 'alerts'}
      data-tab="alerts"
      onclick={() => setTab('alerts')}
    >
      {$t('monitoring.tab.alerts')}
    </button>
    <button
      class="mon-tab"
      class:active={tab === 'templates'}
      data-tab="templates"
      onclick={() => setTab('templates')}
    >
      {$t('monitoring.tab.templates')}
    </button>
    <button class="mon-tab" class:active={tab === 'log'} data-tab="log" onclick={() => setTab('log')}>
      {$t('monitoring.tab.log')}
    </button>
  </div>
</div>

<div class="mon-tab-content" data-tab="overview">
  {#if tab === 'overview'}<MonitoringOverview />{/if}
</div>
<div class="mon-tab-content" data-tab="alerts">
  {#if tab === 'alerts'}<MonitoringAlerts />{/if}
</div>
<div class="mon-tab-content" data-tab="templates">
  {#if tab === 'templates'}<MonitoringTemplates />{/if}
</div>
<div class="mon-tab-content" data-tab="log">
  {#if tab === 'log'}<MonitoringLog />{/if}
</div>
