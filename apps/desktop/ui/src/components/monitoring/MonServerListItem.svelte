<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { ServerGroupSummary } from '$lib/models/monitoring';
  import { statusClass } from '$lib/models/monitoring';
  import { serverInMaintenance } from '$lib/models/maintenance';
  import { maintenanceActive } from '$lib/stores/monitoring';
  import { t } from '$lib/i18n';

  interface Props {
    group: ServerGroupSummary;
    selected: boolean;
    onSelect: (key: string) => void;
  }
  let { group, selected, onSelect }: Props = $props();
</script>

<button type="button" class="mon-srv-item" class:selected onclick={() => onSelect(group.key)}>
  <span class="mon-srv-stripe {statusClass(group.worst)}"></span>
  <span class="mon-srv-info">
    <span class="mon-srv-name">
      {group.serverName}
      {#if serverInMaintenance($maintenanceActive, group.serverId)}
        <span class="maint-badge">{$t('monitoring.maint.badge')}</span>
      {/if}
    </span>
    <span class="mon-srv-meta">
      <span class="mon-srv-count">{group.summary.total} Checks</span>
    </span>
  </span>
  <span class="mon-srv-pills">
    {#if group.summary.critical > 0}
      <span class="mon-pill pill-crit">{group.summary.critical}</span>
    {/if}
    {#if group.summary.warning > 0}
      <span class="mon-pill pill-warn">{group.summary.warning}</span>
    {/if}
    {#if group.summary.ok > 0}
      <span class="mon-pill pill-ok">{group.summary.ok}</span>
    {/if}
    {#if group.summary.unknown + group.summary.pending > 0}
      <span class="mon-pill pill-muted">{group.summary.unknown + group.summary.pending}</span>
    {/if}
  </span>
</button>

<style>
  .maint-badge {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 0 var(--sp-2);
    font-size: 10px;
    color: var(--text-muted);
    margin-left: var(--sp-2);
  }
</style>
