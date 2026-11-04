<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { ServerGroupSummary } from '$lib/models/monitoring';
  import { serverInMaintenance } from '$lib/models/maintenance';
  import { maintenanceActive } from '$lib/stores/monitoring';
  import { t } from '$lib/i18n';
  import Dot from '../ui/Dot.svelte';
  import Pill from '../ui/Pill.svelte';

  interface Props {
    group: ServerGroupSummary;
    selected: boolean;
    onSelect: (key: string) => void;
  }
  let { group, selected, onSelect }: Props = $props();

  const worstLabel = $derived(
    {
      ok: $t('monitoring.status.ok'),
      warning: $t('monitoring.status.warning'),
      critical: $t('monitoring.status.critical'),
      unknown: $t('monitoring.status.unknown'),
      pending: $t('monitoring.status.pending'),
    }[group.worst],
  );
</script>

<button
  type="button"
  class="mon-srv-item"
  class:selected
  aria-current={selected ? 'true' : undefined}
  onclick={() => onSelect(group.key)}
>
  <Dot st={group.worst} label={worstLabel} />
  <span class="mon-srv-info">
    <span class="mon-srv-name">
      {group.serverName}
      {#if serverInMaintenance($maintenanceActive, group.serverId)}
        <span class="maint-badge">{$t('monitoring.maint.badge')}</span>
      {/if}
    </span>
    <span class="mon-srv-count">{group.summary.total} {$t('monitoring.grid.checks')}</span>
  </span>
  <span class="mon-srv-pills">
    {#if group.summary.critical > 0}
      <Pill tone="crit">{group.summary.critical}</Pill>
    {/if}
    {#if group.summary.warning > 0}
      <Pill tone="warn">{group.summary.warning}</Pill>
    {/if}
    {#if group.summary.ok > 0}
      <Pill tone="ok">{group.summary.ok}</Pill>
    {/if}
    {#if group.summary.unknown + group.summary.pending > 0}
      <Pill>{group.summary.unknown + group.summary.pending}</Pill>
    {/if}
  </span>
</button>

<style>
  .mon-srv-item {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 10px 12px;
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .mon-srv-item:hover {
    background: var(--surface-hover);
  }
  .mon-srv-item:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }
  .mon-srv-item.selected {
    border-color: var(--border-strong);
    background: var(--surface-raised);
  }
  .mon-srv-info {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .mon-srv-name {
    overflow: hidden;
    color: var(--text-strong);
    font-size: 13.5px;
    font-weight: 500;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mon-srv-item.selected .mon-srv-name {
    font-weight: 600;
  }
  .mon-srv-count {
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 11px;
  }
  .mon-srv-pills {
    display: inline-flex;
    flex-shrink: 0;
    gap: 5px;
  }
  .maint-badge {
    margin-left: 6px;
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 10px;
    font-weight: 400;
  }
</style>
