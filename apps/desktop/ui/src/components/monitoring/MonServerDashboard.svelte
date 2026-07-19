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
  } from '$lib/stores/monitoring';
  import { computeSummary, statusClass, worstStatus } from '$lib/models/monitoring';
  import type { MonitorCheck, MonitorCheckType } from '$lib/api/types';
  import MonitorCheckModal from './MonitorCheckModal.svelte';
  import MonHeartbeatBar from './MonHeartbeatBar.svelte';
  import SecLive from './section/SecLive.svelte';
  import SecNetwork from './section/SecNetwork.svelte';
  import SecHeartbeat from './section/SecHeartbeat.svelte';
  import SecServices from './section/SecServices.svelte';
  import SecDocker from './section/SecDocker.svelte';
  import SecBackups from './section/SecBackups.svelte';
  import SecZfs from './section/SecZfs.svelte';
  import SecSmart from './section/SecSmart.svelte';
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

  function pick(type: MonitorCheckType | MonitorCheckType[]): MonitorCheck[] {
    const types = Array.isArray(type) ? type : [type];
    return serverChecks.filter((c) => types.includes(c.checkType));
  }

  let liveChecks = $derived(pick('agent_resources'));
  let networkChecks = $derived(pick(['ping', 'tcp', 'http']));
  let heartbeatChecks = $derived(pick('agent_ping'));
  let serviceChecks = $derived(pick('service_process'));
  let dockerChecks = $derived(pick('docker_health'));
  let backupChecks = $derived(pick('proxmox_backup'));
  let zfsChecks = $derived(pick('zfs_health'));
  let smartChecks = $derived(pick('smart_health'));
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
        <span class="mon-dot {statusClass(worst)} mon-dashboard-dot"></span>
        <div class="mon-dashboard-titles">
          <h2 class="mon-dashboard-name">{serverName}</h2>
          {#if serverHost && serverHost !== serverName}
            <span class="mon-dashboard-host">{serverHost}</span>
          {/if}
        </div>
        <div class="mon-dashboard-stats">
          {#if summary.critical > 0}
            <span class="mon-pill pill-crit"
              >{summary.critical} {$t('monitoring.status.critical')}</span
            >
          {/if}
          {#if summary.warning > 0}
            <span class="mon-pill pill-warn"
              >{summary.warning} {$t('monitoring.status.warning')}</span
            >
          {/if}
          <span class="mon-pill pill-ok">{summary.ok} {$t('monitoring.status.ok')}</span>
          {#if summary.unknown > 0}
            <span class="mon-pill pill-muted"
              >{summary.unknown} {$t('monitoring.status.unknown')}</span
            >
          {/if}
          {#if summary.pending > 0}
            <span class="mon-pill pill-muted"
              >{summary.pending} {$t('monitoring.status.pending')}</span
            >
          {/if}
        </div>
        {#if selected !== '__none'}
          <button
            class="btn primary small mon-dashboard-add"
            onclick={() => openCheckEditor(null, selected ?? '')}
          >
            + {$t('monitoring.checkEdit.add')}
          </button>
        {/if}
      </div>
      {#if heartbeatChecks.length > 0}
        <div class="mon-dashboard-heartbeat">
          <MonHeartbeatBar checkId={heartbeatChecks[0].id} />
        </div>
      {/if}
    </header>

    {#if serverChecks.length === 0}
      <div class="mon-panel-empty-inline">{$t('monitoring.panel.noChecks')}</div>
    {:else}
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
