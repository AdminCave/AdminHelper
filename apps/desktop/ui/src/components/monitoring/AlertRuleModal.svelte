<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type {
    AlertChannel,
    AlertChannelConfig,
    AlertRule,
    AlertRuleInput,
    MonitorSeverity,
    Server,
  } from '$lib/api/types';
  import { saveAlert, deleteAlert } from '$lib/stores/monitoring';
  import { reportError } from '$lib/stores/statusBar';
  import { t } from '$lib/i18n';

  interface Props {
    open: boolean;
    editing: AlertRule | null;
    servers: Server[];
    onClose: () => void;
  }
  let { open, editing, servers, onClose }: Props = $props();

  let name = $state('');
  let channel = $state<AlertChannel>('webhook');
  let matchSeverity = $state<'' | MonitorSeverity>('');
  let matchServerId = $state('');
  let cooldown = $state(30);
  let webhookUrl = $state('');
  let emailRecipients = $state('');
  let saving = $state(false);
  let confirmDelete = $state(false);

  let isNew = $derived(editing === null);

  $effect(() => {
    if (!open) return;
    name = editing?.name ?? '';
    channel = editing?.channel ?? 'webhook';
    matchSeverity = (editing?.matchSeverity ?? '') as '' | MonitorSeverity;
    matchServerId = editing?.matchServerId ?? '';
    cooldown = editing?.cooldownMinutes ?? 30;
    const cfg = editing?.channelConfig ?? {};
    webhookUrl = cfg.url ?? '';
    emailRecipients = Array.isArray(cfg.recipients) ? cfg.recipients.join(', ') : '';
    confirmDelete = false;
  });

  function buildChannelConfig(): AlertChannelConfig {
    if (channel === 'webhook') return { url: webhookUrl.trim() };
    return {
      recipients: emailRecipients
        .split(',')
        .map((r) => r.trim())
        .filter((r) => r.length > 0),
    };
  }

  async function onSave(): Promise<void> {
    if (!name.trim()) {
      reportError($t('infra.validation.failed'));
      return;
    }
    if (channel === 'webhook' && !webhookUrl.trim()) {
      reportError($t('monitoring.alertEdit.urlRequired'));
      return;
    }
    if (channel === 'email' && !emailRecipients.trim()) {
      reportError($t('monitoring.alertEdit.recipientsRequired'));
      return;
    }
    const input: AlertRuleInput = {
      name: name.trim(),
      channel,
      match_severity: matchSeverity || null,
      match_server_id: matchServerId || null,
      cooldown_minutes: cooldown || 30,
      channel_config: buildChannelConfig(),
    };
    saving = true;
    const ok = await saveAlert(input, editing?.id ?? null);
    saving = false;
    if (ok) onClose();
  }

  async function onDelete(): Promise<void> {
    if (isNew || !editing) return;
    if (!confirmDelete) {
      confirmDelete = true;
      return;
    }
    saving = true;
    const ok = await deleteAlert(editing.id);
    saving = false;
    if (ok) onClose();
  }
</script>

{#if open}
  <div
    class="editor-overlay"
    role="dialog"
    aria-modal="true"
    onclick={(e) => {
      if (e.target === e.currentTarget) onClose();
    }}
    onkeydown={(e) => e.key === 'Escape' && onClose()}
    tabindex="-1"
  >
    <div class="editor-panel">
      <div class="panel-header">
        <h2 class="panel-title">
          {isNew ? $t('monitoring.alertEdit.new') : name || $t('monitoring.alertEdit.edit')}
        </h2>
        <button class="btn ghost small" onclick={onClose} aria-label={$t('editor.close')}>×</button>
      </div>

      <div class="form-grid">
        <label class="field span2">
          <span class="field-label">{$t('infra.field.name')}</span>
          <input type="text" bind:value={name} required />
        </label>

        <label class="field">
          <span class="field-label">{$t('monitoring.alerts.channel')}</span>
          <select
            value={channel}
            onchange={(e) =>
              (channel = (e.currentTarget as HTMLSelectElement).value as AlertChannel)}
          >
            <option value="webhook">{$t('monitoring.alerts.channelWebhook')}</option>
            <option value="email">{$t('monitoring.alerts.channelEmail')}</option>
          </select>
        </label>

        <label class="field">
          <span class="field-label">{$t('monitoring.alerts.severity')}</span>
          <select
            value={matchSeverity}
            onchange={(e) =>
              (matchSeverity = (e.currentTarget as HTMLSelectElement).value as
                | ''
                | MonitorSeverity)}
          >
            <option value="">{$t('monitoring.alertEdit.allSeverities')}</option>
            <option value="critical">critical</option>
            <option value="warning">warning</option>
          </select>
        </label>

        <label class="field">
          <span class="field-label">{$t('monitoring.alerts.matchServer')}</span>
          <select
            value={matchServerId}
            onchange={(e) => (matchServerId = (e.currentTarget as HTMLSelectElement).value)}
          >
            <option value="">{$t('monitoring.alertEdit.allServers')}</option>
            {#each servers as s (s.id)}
              <option value={s.id}>{s.name}</option>
            {/each}
          </select>
        </label>

        <label class="field">
          <span class="field-label">{$t('monitoring.alerts.cooldown')} (min)</span>
          <input type="number" bind:value={cooldown} />
        </label>

        {#if channel === 'webhook'}
          <label class="field span2">
            <span class="field-label">{$t('monitoring.alerts.webhookUrl')}</span>
            <input
              type="url"
              bind:value={webhookUrl}
              placeholder="https://hooks.example.com/alert"
            />
          </label>
        {:else}
          <label class="field span2">
            <span class="field-label">{$t('monitoring.alertEdit.recipients')}</span>
            <input
              type="text"
              bind:value={emailRecipients}
              placeholder="admin@example.com, ops@example.com"
            />
          </label>
        {/if}
      </div>

      <div class="panel-actions">
        {#if !isNew}
          <button class="btn danger" onclick={onDelete} disabled={saving}>
            {confirmDelete ? $t('infra.server.confirmDelete') : $t('action.delete')}
          </button>
        {/if}
        <div style="flex: 1;"></div>
        <button class="btn" onclick={onClose} disabled={saving}>{$t('action.cancel')}</button>
        <button class="btn primary" onclick={onSave} disabled={saving}>{$t('action.save')}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .editor-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    padding: var(--sp-4);
  }
  .editor-panel {
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    width: 100%;
    max-width: 600px;
    max-height: 90vh;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }
  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--sp-4) var(--sp-5);
    border-bottom: 1px solid var(--border);
  }
  .panel-title {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
  .form-grid {
    padding: var(--sp-5);
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--sp-4);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .field.span2 {
    grid-column: span 2;
  }
  .field-label {
    font-size: 12px;
    color: var(--text-muted);
  }
  .field input,
  .field select {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-2) var(--sp-3);
    font-size: 13px;
    font-family: inherit;
  }
  .field input:focus,
  .field select:focus {
    outline: 1px solid var(--accent);
  }
  .panel-actions {
    display: flex;
    gap: var(--sp-2);
    padding: var(--sp-4) var(--sp-5);
    border-top: 1px solid var(--border);
    align-items: center;
  }
</style>
