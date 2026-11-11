<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import {
    monitoring,
    monitoringAlerts,
    monitoringChecks,
    monitoringFindings,
    monitoringFindingsError,
    monitoringServers,
    monitoringTemplates,
    activateMonitoring,
    deactivateMonitoring,
    openServerPage,
    setTab,
    type MonitoringTab,
  } from '$lib/stores/monitoring';
  import { monitoringSilentMinutes } from '$lib/stores/monitoringPulse';
  import { TriangleAlert } from '@lucide/svelte';
  import MonitoringOverview from '../components/monitoring/MonitoringOverview.svelte';
  import CompareView from '../components/monitoring/CompareView.svelte';
  import MonitoringAlerts from '../components/monitoring/MonitoringAlerts.svelte';
  import MonitoringTemplates from '../components/monitoring/MonitoringTemplates.svelte';
  import MonitoringLog from '../components/monitoring/MonitoringLog.svelte';
  import CertsView from '../components/monitoring/cross/CertsView.svelte';
  import BackupsView from '../components/monitoring/cross/BackupsView.svelte';
  import UpdatesView from '../components/monitoring/cross/UpdatesView.svelte';
  import FindingsView from '../components/monitoring/cross/FindingsView.svelte';
  import Callout from '../components/ui/Callout.svelte';
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
  // yet": only a non-empty list earns a counter, never a misleading 0. The findings load
  // with every refresh, but a failed load keeps the old list: the same rule.
  const count = (n: number) => (n > 0 ? n : undefined);
  const tabs = $derived([
    { id: 'overview', label: $t('monitoring.tab.overview') },
    { id: 'history', label: $t('monitoring.tab.history') },
    { id: 'certs', label: $t('monitoring.tab.certs') },
    { id: 'backups', label: $t('monitoring.tab.backups') },
    { id: 'updates', label: $t('monitoring.tab.updates') },
    {
      id: 'findings',
      label: $t('monitoring.tab.findings'),
      count: count($monitoringFindings.length),
    },
    { id: 'alerts', label: $t('monitoring.tab.alerts'), count: count($monitoringAlerts.length) },
    {
      id: 'templates',
      label: $t('monitoring.tab.templates'),
      count: count($monitoringTemplates.length),
    },
    { id: 'log', label: $t('monitoring.tab.log') },
  ]);
</script>

{#if $monitoringSilentMinutes !== null}
  <div class="mon-silent" role="status">
    <Callout
      tone="warning"
      icon={TriangleAlert}
      title={$t('monitoring.silent.title', { minutes: $monitoringSilentMinutes })}
    >
      {$t('monitoring.silent.body')}
    </Callout>
  </div>
{/if}

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
<div class="mon-tab-content" data-tab="certs">
  {#if tab === 'certs'}
    <CertsView checks={$monitoringChecks} servers={$monitoringServers} onOpen={openServerPage} />
  {/if}
</div>
<div class="mon-tab-content" data-tab="backups">
  {#if tab === 'backups'}
    <BackupsView checks={$monitoringChecks} servers={$monitoringServers} onOpen={openServerPage} />
  {/if}
</div>
<div class="mon-tab-content" data-tab="updates">
  {#if tab === 'updates'}
    <UpdatesView checks={$monitoringChecks} servers={$monitoringServers} onOpen={openServerPage} />
  {/if}
</div>
<div class="mon-tab-content" data-tab="findings">
  {#if tab === 'findings'}
    <FindingsView
      findings={$monitoringFindings}
      error={$monitoringFindingsError}
      servers={$monitoringServers}
      onOpen={openServerPage}
    />
  {/if}
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
  .mon-silent,
  .mon-tabs {
    margin-bottom: 18px;
  }
</style>
