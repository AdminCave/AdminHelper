<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { monitoringAlerts, toggleAlert } from '$lib/stores/monitoring';
  import { t } from '$lib/i18n';
</script>

<div class="mon-alert-list" id="monAlertList">
  {#if $monitoringAlerts.length === 0}
    <div class="mon-empty">{$t('monitoring.alerts.empty')}</div>
  {:else}
    {#each $monitoringAlerts as rule (rule.id)}
      <div class="mon-alert-card">
        <div class="mon-alert-info">
          <div class="mon-alert-name">{rule.name}</div>
          <div class="mon-alert-meta">
            {$t('monitoring.alerts.channel')}: {rule.channel}
            {#if rule.matchSeverity}· {$t('monitoring.alerts.severity')}: {rule.matchSeverity}{/if}
            · {$t('monitoring.alerts.cooldown')}: {rule.cooldownMinutes}m
          </div>
        </div>
        <div class="mon-alert-actions">
          <span class="mon-dot {rule.enabled ? 'mon-ok' : 'mon-unknown'}"></span>
          <button
            class="btn small {rule.enabled ? 'ghost' : 'primary'}"
            onclick={() => void toggleAlert(rule.id)}
          >
            {rule.enabled ? $t('monitoring.alerts.disable') : $t('monitoring.alerts.enable')}
          </button>
        </div>
      </div>
    {/each}
  {/if}
</div>
