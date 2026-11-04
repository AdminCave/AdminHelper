<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import {
    maintenanceActive,
    monitoringChecks,
    monitoringServers,
    monitoringServerSearch,
    setSelectedServer,
    setOverviewView,
  } from '$lib/stores/monitoring';
  import { serverInMaintenance } from '$lib/models/maintenance';
  import { groupChecksByServerWithSummary } from '$lib/models/monitoring';
  import { t } from '$lib/i18n';
  import Dot from '../ui/Dot.svelte';
  import Pill from '../ui/Pill.svelte';
  import MonHeartbeatBar from './MonHeartbeatBar.svelte';

  let groups = $derived(
    groupChecksByServerWithSummary($monitoringChecks, $monitoringServers, $monitoringServerSearch),
  );

  // Tile click drills down: select the server and jump into the list+detail
  // view — the grid is the fleet overview, the split view is the detail.
  function open(key: string): void {
    setSelectedServer(key);
    setOverviewView('list');
  }
</script>

<div class="mon-grid">
  {#if groups.length === 0}
    <div class="mon-grid-empty">{$t('monitoring.serverList.empty')}</div>
  {:else}
    {#each groups as g (g.key)}
      <!-- Own worst-* modifiers on the root: statusClass would drag the GLOBAL
           .mon-pending {opacity:.5} etc. onto the whole tile. -->
      <button class="mon-tile worst-{g.worst}" type="button" onclick={() => open(g.key)}>
        <span class="mon-tile-head">
          <Dot st={g.worst} ring />
          <span class="mon-tile-name">{g.serverName}</span>
          {#if serverInMaintenance($maintenanceActive, g.serverId)}
            <span class="maint-badge">{$t('monitoring.maint.badge')}</span>
          {/if}
        </span>
        <span class="mon-tile-counts">
          {#if g.summary.critical > 0}
            <Pill tone="crit">{g.summary.critical}</Pill>
          {/if}
          {#if g.summary.warning > 0}
            <Pill tone="warn">{g.summary.warning}</Pill>
          {/if}
          {#if g.summary.ok > 0}
            <Pill tone="ok">{g.summary.ok}</Pill>
          {/if}
          {#if g.summary.unknown + g.summary.pending > 0}
            <Pill>{g.summary.unknown + g.summary.pending}</Pill>
          {/if}
        </span>
        {#each g.checks.filter((c) => c.checkType === 'agent_ping').slice(0, 1) as hb (hb.id)}
          <MonHeartbeatBar checkId={hb.id} />
        {/each}
        <span class="mon-tile-total">{g.checks.length} {$t('monitoring.grid.checks')}</span>
      </button>
    {/each}
  {/if}
</div>

<style>
  .mon-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
    gap: 14px;
  }
  .mon-tile {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
    color: var(--text);
    font-family: inherit;
    text-align: left;
    cursor: pointer;
  }
  .mon-tile:hover {
    border-color: var(--border-strong);
    background: var(--surface-hover);
  }
  .mon-tile:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  .mon-tile.worst-critical {
    border-color: var(--danger-border);
  }
  .mon-tile.worst-warning {
    border-color: var(--warning-border);
  }
  .mon-tile-head {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  .mon-tile-name {
    overflow: hidden;
    color: var(--text-strong);
    font-size: 14px;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .maint-badge {
    flex-shrink: 0;
    margin-left: auto;
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 10px;
  }
  .mon-tile-counts {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
  }
  .mon-tile-total {
    padding-top: 10px;
    border-top: 1px solid var(--border-faint);
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 11px;
  }
  .mon-grid-empty {
    grid-column: 1 / -1;
    padding: var(--sp-4);
    color: var(--text-muted);
    font-size: 13px;
  }
</style>
