<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import {
    monitoring,
    monitoringAlerts,
    monitoringTemplates,
    activateMonitoring,
    deactivateMonitoring,
    setTab,
    type MonitoringTab,
  } from '$lib/stores/monitoring';
  import MonitoringOverview from '../components/monitoring/MonitoringOverview.svelte';
  import CompareView from '../components/monitoring/CompareView.svelte';
  import MonitoringAlerts from '../components/monitoring/MonitoringAlerts.svelte';
  import MonitoringTemplates from '../components/monitoring/MonitoringTemplates.svelte';
  import MonitoringLog from '../components/monitoring/MonitoringLog.svelte';
  import Tabs from '../components/ui/Tabs.svelte';
  import { t } from '$lib/i18n';

  onMount(() => {
    activateMonitoring();
  });

  onDestroy(() => {
    deactivateMonitoring();
  });

  let tab = $derived($monitoring.tab);

  // Alerts and templates load lazily on their tab, so an empty list can also mean "not loaded
  // yet": only a non-empty list earns a counter, never a misleading 0.
  const count = (n: number) => (n > 0 ? n : undefined);
  const tabs = $derived([
    { id: 'overview', label: $t('monitoring.tab.overview') },
    { id: 'history', label: $t('monitoring.tab.history') },
    { id: 'alerts', label: $t('monitoring.tab.alerts'), count: count($monitoringAlerts.length) },
    {
      id: 'templates',
      label: $t('monitoring.tab.templates'),
      count: count($monitoringTemplates.length),
    },
    { id: 'log', label: $t('monitoring.tab.log') },
  ]);
</script>

<div class="mon-tabs">
  <Tabs
    {tabs}
    value={tab}
    label={$t('nav.monitoring')}
    onChange={(id) => setTab(id as MonitoringTab)}
  />
</div>

<div class="mon-tab-content" data-tab="overview">
  {#if tab === 'overview'}<MonitoringOverview />{/if}
</div>
<div class="mon-tab-content" data-tab="history">
  {#if tab === 'history'}<CompareView />{/if}
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

<style>
  .mon-tabs {
    margin-bottom: 18px;
  }
</style>
