<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import {
    monitoringChecks,
    monitoringServers,
    monitoringServerSearch,
    setSelectedServer,
    setOverviewView,
  } from '$lib/stores/monitoring';
  import { groupChecksByServerWithSummary, statusClass } from '$lib/models/monitoring';
  import { t } from '$lib/i18n';

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
          <span class="mon-dot {statusClass(g.worst)}"></span>
          <span class="mon-tile-name">{g.serverName}</span>
        </span>
        <span class="mon-tile-counts">
          {#if g.summary.critical > 0}
            <span class="mon-pill pill-crit">{g.summary.critical}</span>
          {/if}
          {#if g.summary.warning > 0}
            <span class="mon-pill pill-warn">{g.summary.warning}</span>
          {/if}
          {#if g.summary.ok > 0}
            <span class="mon-pill pill-ok">{g.summary.ok}</span>
          {/if}
          {#if g.summary.unknown + g.summary.pending > 0}
            <span class="mon-pill pill-muted">{g.summary.unknown + g.summary.pending}</span>
          {/if}
        </span>
        <span class="mon-tile-total">{g.checks.length} {$t('monitoring.grid.checks')}</span>
      </button>
    {/each}
  {/if}
</div>

<style>
  .mon-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: var(--sp-4);
  }
  .mon-tile {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
    padding: var(--sp-4);
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-left: 3px solid var(--border);
    border-radius: var(--radius-md);
    cursor: pointer;
    text-align: left;
    color: var(--text);
    font-family: inherit;
  }
  .mon-tile:hover {
    border-color: var(--accent);
  }
  /* Worst-state accent on the tile's left edge. */
  .mon-tile.worst-ok {
    border-left-color: var(--success);
  }
  .mon-tile.worst-warning {
    border-left-color: var(--warning);
  }
  .mon-tile.worst-critical {
    border-left-color: var(--danger);
  }
  .mon-grid-empty {
    grid-column: 1 / -1;
    color: var(--text-muted);
    font-size: 13px;
    padding: var(--sp-4);
  }
  .mon-tile-head {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    min-width: 0;
  }
  .mon-tile-name {
    font-size: 14px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mon-tile-counts {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-2);
  }
  .mon-tile-total {
    font-size: 12px;
    color: var(--text-muted);
  }
</style>
