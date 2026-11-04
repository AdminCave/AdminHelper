<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { monitoringLog } from '$lib/stores/monitoring';
  import { formatCheckTime } from '$lib/models/monitoring';
  import { ScrollText } from '@lucide/svelte';
  import Dot from '../ui/Dot.svelte';
  import Panel from '../ui/Panel.svelte';
  import { t } from '$lib/i18n';
</script>

<Panel title={$t('monitoring.log.title')} icon={ScrollText} pad={0}>
  <div class="mon-alert-log" id="monAlertLog">
    {#if $monitoringLog.length === 0}
      <div class="mon-empty">{$t('monitoring.log.empty')}</div>
    {:else}
      {#each $monitoringLog as entry (entry.id)}
        <div class="mon-log-entry">
          <span class="mon-log-time">{formatCheckTime(entry.sentAt)}</span>
          <Dot st={entry.newStatus} size={7} />
          <span class="mon-log-transition">{entry.oldStatus} → {entry.newStatus}</span>
          <span class="mon-log-result" class:failed={!entry.success}>
            {entry.success ? '✓' : '✗'}
          </span>
          <span class="mon-log-error">{entry.error || ''}</span>
        </div>
      {/each}
    {/if}
  </div>
</Panel>

<style>
  .mon-log-entry {
    display: grid;
    grid-template-columns: auto 12px minmax(130px, auto) auto 1fr;
    align-items: center;
    gap: 12px;
    padding: 11px 16px;
    border-top: 1px solid var(--border-faint);
    font-size: 13px;
  }
  .mon-log-entry:first-child {
    border-top: none;
  }
  .mon-log-time {
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 12px;
    white-space: nowrap;
  }
  .mon-log-transition {
    color: var(--text-strong);
    font-weight: 600;
  }
  .mon-log-result {
    color: var(--success);
    font-weight: 700;
  }
  .mon-log-result.failed {
    color: var(--danger);
  }
  .mon-log-error {
    overflow: hidden;
    color: var(--text-muted);
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
