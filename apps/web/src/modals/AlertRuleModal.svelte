<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { alertRules } from '$lib/stores/monitoring';
  import { servers as serversStore } from '$lib/stores/servers';
  import { showToast } from '$lib/stores/notifications';
  import { parseCsv } from '$lib/utils/monitoring';
  import type {
    AlertChannel,
    AlertChannelConfig,
    AlertRule,
    AlertRuleInput,
    MonitorSeverity,
  } from '$lib/api/types';

  interface Props {
    open: boolean;
    editing: AlertRule | null;
    onClose: () => void;
  }

  let { open, editing, onClose }: Props = $props();

  let name = $state('');
  let channel = $state<AlertChannel>('webhook');
  let matchSeverity = $state<'' | MonitorSeverity>('');
  let matchServerId = $state('');
  let cooldown = $state(30);
  let webhookUrl = $state('');
  let emailRecipients = $state('');
  let submitting = $state(false);

  $effect(() => {
    if (open) {
      name = editing?.name ?? '';
      channel = editing?.channel ?? 'webhook';
      matchSeverity = (editing?.matchSeverity ?? '') as '' | MonitorSeverity;
      matchServerId = editing?.matchServerId ?? '';
      cooldown = editing?.cooldownMinutes ?? 30;
      const cfg = editing?.channelConfig ?? {};
      webhookUrl = cfg.url ?? '';
      emailRecipients = Array.isArray(cfg.recipients) ? cfg.recipients.join(', ') : '';
    }
  });

  function buildChannelConfig(): AlertChannelConfig {
    if (channel === 'webhook') return { url: webhookUrl.trim() };
    return { recipients: parseCsv(emailRecipients) };
  }

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    submitting = true;
    try {
      const data: AlertRuleInput = {
        name: name.trim(),
        channel,
        match_severity: matchSeverity || null,
        match_server_id: matchServerId || null,
        cooldown_minutes: cooldown || 30,
        channel_config: buildChannelConfig(),
      };
      if (editing) {
        await alertRules.update(editing.id, data);
        showToast($t('toast.alert.saved'));
      } else {
        await alertRules.create(data);
        showToast($t('toast.alert.created'));
      }
      onClose();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    } finally {
      submitting = false;
    }
  }
</script>

<Modal
  {open}
  title={editing ? $t('modal.alert.title') : $t('modal.alert.titleNew')}
  width="640px"
  {onClose}
>
  <form class="modal-form" onsubmit={onSubmit} id="alert-rule-form">
    <div class="field full">
      <label for="arName">{$t('label.name')} *</label>
      <input id="arName" required bind:value={name} />
    </div>
    <div class="field">
      <label for="arChannel">{$t('modal.alert.channel')} *</label>
      <select id="arChannel" bind:value={channel}>
        <option value="webhook">Webhook</option>
        <option value="email">E-Mail</option>
      </select>
    </div>
    <div class="field">
      <label for="arSeverity">Severity</label>
      <select id="arSeverity" bind:value={matchSeverity}>
        <option value="">{$t('label.all')}</option>
        <option value="critical">critical</option>
        <option value="warning">warning</option>
      </select>
    </div>
    <div class="field">
      <label for="arServer">Server</label>
      <select id="arServer" bind:value={matchServerId}>
        <option value="">{$t('modal.alert.allServers')}</option>
        {#each $serversStore as s (s.id)}
          <option value={s.id}>{s.name}</option>
        {/each}
      </select>
    </div>
    <div class="field">
      <label for="arCooldown">Cooldown (min)</label>
      <input id="arCooldown" type="number" bind:value={cooldown} />
    </div>
    {#if channel === 'webhook'}
      <div class="field full">
        <label for="arWebhook">Webhook URL *</label>
        <input
          id="arWebhook"
          required
          placeholder="https://hooks.example.com/alert"
          bind:value={webhookUrl}
        />
      </div>
    {:else}
      <div class="field full">
        <label for="arRecipients">{$t('modal.alert.recipients')} *</label>
        <input
          id="arRecipients"
          required
          placeholder="admin@example.com, ops@example.com"
          bind:value={emailRecipients}
        />
      </div>
    {/if}
  </form>
  {#snippet footer()}
    <Button variant="ghost" onclick={onClose}>{$t('action.cancel')}</Button>
    <Button
      variant="primary"
      type="submit"
      disabled={submitting}
      onclick={() =>
        (document.getElementById('alert-rule-form') as HTMLFormElement)?.requestSubmit()}
    >
      {$t('action.save')}
    </Button>
  {/snippet}
</Modal>
