<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import {
    monitoringChecks,
    monitoringServers,
    selectedServerId,
    checkEditor,
    openCheckEditor,
    closeCheckEditor,
    loadMonitoring,
    loadMaintenanceWindows,
  } from '$lib/stores/monitoring';
  import { computeSummary, worstStatus } from '$lib/models/monitoring';
  import type { MonitorCheck, MonitorCheckType } from '$lib/api/types';
  import { Plus, Wrench } from '@lucide/svelte';
  import Button from '../ui/Button.svelte';
  import Dot from '../ui/Dot.svelte';
  import Pill from '../ui/Pill.svelte';
  import MaintenanceModal from './MaintenanceModal.svelte';
  import MonitorCheckModal from './MonitorCheckModal.svelte';
  import MonHeartbeatBar from './MonHeartbeatBar.svelte';
  import SecLive from './section/SecLive.svelte';
  import SecNetwork from './section/SecNetwork.svelte';
  import SecHeartbeat from './section/SecHeartbeat.svelte';
  import SecServices from './section/SecServices.svelte';
  import SecSystem from './section/SecSystem.svelte';
  import SecDocker from './section/SecDocker.svelte';
  import SecBackups from './section/SecBackups.svelte';
  import SecZfs from './section/SecZfs.svelte';
  import SecSmart from './section/SecSmart.svelte';
  import SecForecast from './section/SecForecast.svelte';
  import HistoryPanel from './HistoryPanel.svelte';
  import { t } from '$lib/i18n';

  let selected = $derived($selectedServerId);

  let serverName = $derived.by(() => {
    if (!selected) return '';
    if (selected === '__none') return $t('monitoring.server.noServer');
    const srv = $monitoringServers.find((s) => s.id === selected);
    if (srv) return srv.name || srv.hostname || selected;
    return selected;
  });

  let serverHost = $derived.by(() => {
    if (!selected || selected === '__none') return '';
    const srv = $monitoringServers.find((s) => s.id === selected);
    return srv ? srv.hostname || '' : '';
  });

  let serverChecks = $derived.by(() => {
    if (!selected) return [] as MonitorCheck[];
    return $monitoringChecks.filter((c) => (c.serverId || '__none') === selected);
  });

  let summary = $derived(computeSummary(serverChecks));
  let worst = $derived(worstStatus(serverChecks));
  let worstLabel = $derived(
    {
      ok: $t('monitoring.status.ok'),
      warning: $t('monitoring.status.warning'),
      critical: $t('monitoring.status.critical'),
      unknown: $t('monitoring.status.unknown'),
      pending: $t('monitoring.status.pending'),
    }[worst],
  );

  let maintOpen = $state(false);

  function pick(type: MonitorCheckType | MonitorCheckType[]): MonitorCheck[] {
    const types = Array.isArray(type) ? type : [type];
    return serverChecks.filter((c) => types.includes(c.checkType));
  }

  let liveChecks = $derived(pick('agent_resources'));
  let networkChecks = $derived(pick(['ping', 'tcp', 'http']));
  let heartbeatChecks = $derived(pick('agent_ping'));
  let serviceChecks = $derived(pick('service_process'));
  let systemChecks = $derived(pick('system_state'));
  let dockerChecks = $derived(pick('docker_health'));
  let backupChecks = $derived(pick('proxmox_backup'));
  let zfsChecks = $derived(pick('zfs_health'));
  let smartChecks = $derived(pick('smart_health'));
  let forecastChecks = $derived(pick('disk_forecast'));
</script>

<div class="mon-dashboard">
  {#if !selected}
    <div class="mon-panel-empty">
      <span class="mon-panel-empty-icon" aria-hidden="true">⇦</span>
      <span>{$t('monitoring.panel.selectServer')}</span>
    </div>
  {:else}
    <header class="mon-dashboard-head">
      <div class="mon-dashboard-title">
        <Dot st={worst} size={11} ring label={worstLabel} />
        <div class="mon-dashboard-titles">
          <h2 class="mon-dashboard-name">{serverName}</h2>
          {#if serverHost && serverHost !== serverName}
            <span class="mon-dashboard-host">{serverHost}</span>
          {/if}
        </div>
        <div class="mon-dashboard-stats">
          {#if summary.critical > 0}
            <Pill tone="crit">{summary.critical} {$t('monitoring.status.critical')}</Pill>
          {/if}
          {#if summary.warning > 0}
            <Pill tone="warn">{summary.warning} {$t('monitoring.status.warning')}</Pill>
          {/if}
          <Pill tone="ok">{summary.ok} {$t('monitoring.status.ok')}</Pill>
          {#if summary.unknown > 0}
            <Pill>{summary.unknown} {$t('monitoring.status.unknown')}</Pill>
          {/if}
          {#if summary.pending > 0}
            <Pill>{summary.pending} {$t('monitoring.status.pending')}</Pill>
          {/if}
        </div>
        {#if selected !== '__none'}
          <div class="mon-dashboard-actions">
            <Button
              variant="ghost"
              size="sm"
              iconLeft={Wrench}
              data-action="maintenance-new"
              onclick={() => (maintOpen = true)}>{$t('monitoring.maint.title')}</Button
            >
            <Button
              size="sm"
              iconLeft={Plus}
              data-action="check-new"
              onclick={() => openCheckEditor(null, selected ?? '')}
              >{$t('monitoring.checkEdit.add')}</Button
            >
          </div>
        {/if}
      </div>
      {#if heartbeatChecks.length > 0}
        <MonHeartbeatBar checkId={heartbeatChecks[0].id} />
      {/if}
    </header>

    {#if serverChecks.length === 0}
      <div class="mon-panel-empty-inline">{$t('monitoring.panel.noChecks')}</div>
    {:else}
      {#if liveChecks.length > 0 && selected !== '__none'}
        <HistoryPanel serverId={selected} {serverName} latencyChecks={networkChecks} />
      {/if}
      {#if heartbeatChecks.length > 0}
        <SecHeartbeat checks={heartbeatChecks} />
      {/if}
      {#if liveChecks.length > 0}
        <SecLive checks={liveChecks} />
      {/if}
      {#if networkChecks.length > 0}
        <SecNetwork checks={networkChecks} />
      {/if}
      {#if serviceChecks.length > 0}
        <SecServices checks={serviceChecks} />
      {/if}
      {#if systemChecks.length > 0}
        <SecSystem checks={systemChecks} />
      {/if}
      {#if dockerChecks.length > 0}
        <SecDocker checks={dockerChecks} />
      {/if}
      {#if backupChecks.length > 0}
        <SecBackups checks={backupChecks} />
      {/if}
      {#if zfsChecks.length > 0}
        <SecZfs checks={zfsChecks} />
      {/if}
      {#if smartChecks.length > 0}
        <SecSmart checks={smartChecks} />
      {/if}
      {#if forecastChecks.length > 0}
        <SecForecast checks={forecastChecks} />
      {/if}
    {/if}
  {/if}
</div>

<MonitorCheckModal
  open={$checkEditor.open}
  target={$checkEditor.target}
  serverId={$checkEditor.serverId}
  onClose={closeCheckEditor}
  onSaved={() => void loadMonitoring()}
/>

{#if selected && selected !== '__none'}
  <MaintenanceModal
    open={maintOpen}
    editing={null}
    serverId={selected}
    onClose={() => (maintOpen = false)}
    onSaved={() => void loadMaintenanceWindows()}
  />
{/if}

<style>
  .mon-dashboard {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .mon-dashboard-head {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 18px;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
  }
  .mon-dashboard-title {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px;
    min-width: 0;
  }
  .mon-dashboard-titles {
    display: flex;
    flex: 1 1 160px;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  .mon-dashboard-name {
    overflow: hidden;
    margin: 0;
    color: var(--text-strong);
    font-size: 18px;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mon-dashboard-host {
    overflow: hidden;
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 11.5px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mon-dashboard-stats,
  .mon-dashboard-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .mon-panel-empty,
  .mon-panel-empty-inline {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    padding: 28px 16px;
    border: 1px dashed var(--border);
    border-radius: var(--radius-lg);
    color: var(--text-muted);
    font-size: 13px;
    text-align: center;
  }
  .mon-panel-empty-icon {
    font-size: 24px;
    opacity: 0.5;
  }
</style>
