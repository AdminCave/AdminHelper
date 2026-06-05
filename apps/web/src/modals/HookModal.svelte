<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { showToast } from '$lib/stores/notifications';
  import * as api from '$lib/api/hooks';
  import { HOOK_EVENTS, HOOK_INTERVAL_PRESETS } from '$lib/utils/hooks';
  import type { HookCreate, HookDetail, HookType, HookUpdate } from '$lib/api/types';

  interface Props {
    open: boolean;
    editing: HookDetail | null;
    onClose: (created?: { token?: string | null }) => void;
  }

  let { open, editing, onClose }: Props = $props();

  let name = $state('');
  let description = $state('');
  let hookType = $state<HookType>('webhook');
  let script = $state('');
  let events = $state<Set<string>>(new Set());
  let interval = $state<string>('1h');
  let cron = $state('');
  let submitting = $state(false);

  $effect(() => {
    if (open) {
      name = editing?.name ?? '';
      description = editing?.description ?? '';
      hookType = editing?.hook_type ?? 'webhook';
      script = editing?.script ?? '';
      events = new Set(editing?.event_triggers ?? []);
      const iv = editing?.schedule_interval ?? '1h';
      if (HOOK_INTERVAL_PRESETS.includes(iv as (typeof HOOK_INTERVAL_PRESETS)[number])) {
        interval = iv;
        cron = '';
      } else {
        interval = 'custom';
        cron = iv;
      }
    }
  });

  const isEvent = $derived(hookType === 'event');
  const isSchedule = $derived(hookType === 'schedule');
  const isCustomInterval = $derived(isSchedule && interval === 'custom');

  const scriptHelp = $derived.by(() => {
    const parts: string[] = [];
    if (hookType === 'webhook') parts.push($t('hook.scriptHelp.webhook'));
    else if (hookType === 'event') parts.push($t('hook.scriptHelp.event'));
    else if (hookType === 'schedule') parts.push($t('hook.scriptHelp.schedule'));
    parts.push($t('hook.scriptHelp.base'));
    return parts.join(' · ');
  });

  function toggleEvent(evt: string) {
    const next = new Set(events);
    if (next.has(evt)) next.delete(evt);
    else next.add(evt);
    events = next;
  }

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (isEvent && events.size === 0) {
      showToast($t('modal.hook.selectEvent'), 'error');
      return;
    }
    const intervalValue = isSchedule ? (interval === 'custom' ? cron.trim() : interval) : '';
    if (isSchedule && !intervalValue) {
      showToast($t('modal.hook.selectInterval'), 'error');
      return;
    }
    submitting = true;
    try {
      if (editing) {
        const payload: HookUpdate = {
          name: name.trim(),
          description: description.trim() || null,
          script,
        };
        if (isEvent) payload.event_triggers = [...events];
        if (isSchedule) payload.schedule_interval = intervalValue;
        await api.update(editing.id, payload);
        showToast($t('toast.hook.saved'));
        onClose();
      } else {
        const payload: HookCreate = {
          name: name.trim(),
          description: description.trim() || null,
          hook_type: hookType,
          script,
        };
        if (isEvent) payload.event_triggers = [...events];
        if (isSchedule) payload.schedule_interval = intervalValue;
        const created = await api.create(payload);
        if (hookType === 'webhook' && created.token) {
          onClose({ token: created.token });
        } else {
          showToast($t('toast.hook.created'));
          onClose();
        }
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    } finally {
      submitting = false;
    }
  }
</script>

<Modal
  {open}
  title={editing ? $t('modal.hook.title') : $t('modal.hook.titleNew')}
  width="720px"
  onClose={() => onClose()}
>
  <form class="modal-form" onsubmit={onSubmit} id="hook-form">
    <div class="field">
      <label for="hkName">{$t('label.name')} *</label>
      <input id="hkName" required bind:value={name} />
    </div>
    <div class="field">
      <label for="hkDesc">{$t('modal.hook.description')}</label>
      <input id="hkDesc" placeholder={$t('modal.hook.descPlaceholder')} bind:value={description} />
    </div>
    <div class="field">
      <label for="hkType">{$t('modal.hook.type')}</label>
      <select id="hkType" disabled={!!editing} bind:value={hookType}>
        <option value="webhook">{$t('modal.hook.typeWebhook')}</option>
        <option value="event">{$t('modal.hook.typeEvent')}</option>
        <option value="schedule">{$t('modal.hook.typeSchedule')}</option>
      </select>
    </div>
    {#if isEvent}
      <div class="field full">
        <span style="display:block;font-size:13px;color:var(--text-muted);margin-bottom:6px">
          {$t('modal.hook.events')}
        </span>
        <div
          style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:6px;max-height:220px;overflow-y:auto;padding:8px;border:1px solid var(--border);border-radius:6px"
        >
          {#each HOOK_EVENTS as evt (evt)}
            <label class="checkbox-label">
              <input type="checkbox" checked={events.has(evt)} onchange={() => toggleEvent(evt)} />
              {$t(`hook.event.${evt}`)}
              <br />
              <span style="font-size:10px;color:var(--text-muted)">{evt}</span>
            </label>
          {/each}
        </div>
      </div>
    {/if}
    {#if isSchedule}
      <div class="field">
        <label for="hkInterval">{$t('modal.hook.interval')}</label>
        <select id="hkInterval" bind:value={interval}>
          <option value="5m">{$t('modal.hook.interval5m')}</option>
          <option value="15m">{$t('modal.hook.interval15m')}</option>
          <option value="30m">{$t('modal.hook.interval30m')}</option>
          <option value="1h">{$t('modal.hook.interval1h')}</option>
          <option value="6h">{$t('modal.hook.interval6h')}</option>
          <option value="12h">{$t('modal.hook.interval12h')}</option>
          <option value="24h">{$t('modal.hook.interval24h')}</option>
          <option value="custom">{$t('modal.hook.intervalCustom')}</option>
        </select>
      </div>
      {#if isCustomInterval}
        <div class="field">
          <label for="hkCron">{$t('modal.hook.cron')}</label>
          <input id="hkCron" placeholder="*/10 * * * *" bind:value={cron} />
          <small style="color:var(--text-muted)">{$t('modal.hook.cronFormat')}</small>
        </div>
      {/if}
    {/if}
    <div class="field full">
      <label for="hkScript">{$t('modal.hook.script')}</label>
      <textarea
        id="hkScript"
        placeholder={$t('modal.hook.scriptPlaceholder')}
        required
        style="min-height:220px;font-family:monospace;font-size:13px"
        bind:value={script}
      ></textarea>
      <small style="color:var(--text-muted)">{@html scriptHelp}</small>
    </div>
  </form>
  {#snippet footer()}
    <Button variant="ghost" onclick={() => onClose()}>{$t('action.cancel')}</Button>
    <Button
      variant="primary"
      type="submit"
      disabled={submitting}
      onclick={() => (document.getElementById('hook-form') as HTMLFormElement)?.requestSubmit()}
    >
      {$t('action.save')}
    </Button>
  {/snippet}
</Modal>
