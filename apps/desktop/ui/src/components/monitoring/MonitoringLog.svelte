<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { monitoringLog } from '$lib/stores/monitoring';
  import { statusClass, formatCheckTime } from '$lib/models/monitoring';
  import { t } from '$lib/i18n';
</script>

<div class="mon-alert-log" id="monAlertLog">
  {#if $monitoringLog.length === 0}
    <div class="mon-empty">{$t('monitoring.log.empty')}</div>
  {:else}
    {#each $monitoringLog as entry (entry.id)}
      <div class="mon-log-entry">
        <span class="mon-log-time">{formatCheckTime(entry.sentAt)}</span>
        <span class="mon-log-transition">
          <span class="mon-dot-sm {statusClass(entry.oldStatus)}"></span>
          <span> → </span>
          <span class="mon-dot-sm {statusClass(entry.newStatus)}"></span>
          <span> {entry.oldStatus} → {entry.newStatus}</span>
        </span>
        <span class="mon-log-result {entry.success ? 'mon-ok' : 'mon-critical'}">
          {entry.success ? '✓' : '✗'}
        </span>
        <span class="mon-log-error">{entry.error || ''}</span>
      </div>
    {/each}
  {/if}
</div>
