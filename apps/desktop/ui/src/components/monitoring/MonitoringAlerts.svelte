<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { monitoringAlerts, monitoringServers, toggleAlert } from '$lib/stores/monitoring';
  import type { AlertRule } from '$lib/api/types';
  import { Bell, BellRing, Pencil, Plus } from '@lucide/svelte';
  import Button from '../ui/Button.svelte';
  import IconButton from '../ui/IconButton.svelte';
  import Panel from '../ui/Panel.svelte';
  import Switch from '../ui/Switch.svelte';
  import AlertRuleModal from './AlertRuleModal.svelte';
  import { t } from '$lib/i18n';

  let modalOpen = $state(false);
  let editing = $state<AlertRule | null>(null);

  function openNew(): void {
    editing = null;
    modalOpen = true;
  }
  function openEdit(rule: AlertRule): void {
    editing = rule;
    modalOpen = true;
  }
</script>

{#snippet newAction()}
  <Button size="sm" iconLeft={Plus} data-action="alert-new" onclick={openNew}
    >{$t('monitoring.alertEdit.add')}</Button
  >
{/snippet}

<Panel title={$t('monitoring.alerts.title')} icon={BellRing} pad={0} action={newAction}>
  <div class="mon-alert-list" id="monAlertList">
    {#if $monitoringAlerts.length === 0}
      <div class="mon-empty">{$t('monitoring.alerts.empty')}</div>
    {:else}
      {#each $monitoringAlerts as rule (rule.id)}
        <div class="mon-alert-row" class:inactive={!rule.enabled}>
          <span class="mon-alert-icon" aria-hidden="true"><Bell size={16} /></span>
          <div class="mon-alert-info">
            <div class="mon-alert-name">{rule.name}</div>
            <div class="mon-alert-meta">
              {$t('monitoring.alerts.channel')}: {rule.channel}
              {#if rule.matchSeverity}· {$t('monitoring.alerts.severity')}: {rule.matchSeverity}{/if}
              · {$t('monitoring.alerts.cooldown')}: {rule.cooldownMinutes}m
            </div>
          </div>
          <Switch
            size="sm"
            checked={!!rule.enabled}
            label={$t('monitoring.alerts.active')}
            onChange={() => void toggleAlert(rule.id)}
          />
          <IconButton
            size="sm"
            variant="ghost"
            icon={Pencil}
            label={$t('action.edit')}
            onclick={() => openEdit(rule)}
          />
        </div>
      {/each}
    {/if}
  </div>
</Panel>

<AlertRuleModal
  open={modalOpen}
  {editing}
  servers={$monitoringServers}
  onClose={() => (modalOpen = false)}
/>

<style>
  .mon-alert-row {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px 16px;
    border-top: 1px solid var(--border-faint);
  }
  .mon-alert-row:first-child {
    border-top: none;
  }
  .mon-alert-icon {
    display: inline-flex;
    flex-shrink: 0;
    color: var(--text-strong);
  }
  .mon-alert-row.inactive .mon-alert-icon {
    color: var(--text-subtle);
  }
  .mon-alert-info {
    flex: 1;
    min-width: 0;
  }
  .mon-alert-name {
    overflow: hidden;
    color: var(--text-strong);
    font-size: 13.5px;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mon-alert-meta {
    margin-top: 2px;
    color: var(--text-subtle);
    font-size: 12px;
  }
</style>
