<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import Checkbox from '$lib/components/ui/Checkbox.svelte';
  import FormField from '$lib/components/ui/FormField.svelte';
  import Input from '$lib/components/ui/Input.svelte';
  import Select from '$lib/components/ui/Select.svelte';
  import { t } from '$lib/i18n';
  import { showToast, showError } from '$lib/stores/notifications';
  import { hooks } from '$lib/stores/hooks';
  import { HOOK_EVENTS } from '$lib/utils/hooks';
  import {
    hookCreatePayload,
    hookFormFrom,
    hookUpdatePayload,
    validateHookForm,
    type HookForm,
  } from '$lib/utils/hookForm';
  import type { HookDetail, HookType } from '$lib/api/types';

  interface Props {
    open: boolean;
    editing: HookDetail | null;
    onClose: (created?: { token?: string | null }) => void;
  }

  let { open, editing, onClose }: Props = $props();

  let name = $state('');
  let description = $state('');
  // Select binds a string; its three options are exactly the HookType values.
  let hookType = $state<string>('webhook');
  let script = $state('');
  let events = $state<Set<string>>(new Set());
  let interval = $state<string>('1h');
  let cron = $state('');
  let submitting = $state(false);

  $effect(() => {
    if (open) {
      const form = hookFormFrom(editing);
      name = form.name;
      description = form.description;
      hookType = form.hookType;
      script = form.script;
      events = new Set(form.events);
      interval = form.interval;
      cron = form.cron;
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
    // eslint-disable-next-line svelte/prefer-svelte-reactivity -- transient copy; reactivity comes from the reassignment to $state below
    const next = new Set(events);
    if (next.has(evt)) next.delete(evt);
    else next.add(evt);
    events = next;
  }

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    const form: HookForm = {
      name,
      description,
      hookType: hookType as HookType,
      script,
      events: [...events],
      interval,
      cron,
    };
    const missing = validateHookForm(form);
    if (missing) {
      showToast($t(missing), 'error');
      return;
    }
    submitting = true;
    try {
      if (editing) {
        await hooks.update(editing.id, hookUpdatePayload(form));
        showToast($t('toast.hook.saved'));
        onClose();
      } else {
        const created = await hooks.create(hookCreatePayload(form));
        if (hookType === 'webhook' && created.token) {
          onClose({ token: created.token });
        } else {
          showToast($t('toast.hook.created'));
          onClose();
        }
      }
    } catch (err) {
      showError(err);
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
  <form class="form" onsubmit={onSubmit} id="hook-form">
    <FormField label={$t('label.name')} id="hkName" required>
      <Input required bind:value={name} />
    </FormField>
    <FormField label={$t('modal.hook.description')} id="hkDesc">
      <Input placeholder={$t('modal.hook.descPlaceholder')} bind:value={description} />
    </FormField>
    <FormField label={$t('modal.hook.type')} id="hkType">
      <Select
        disabled={!!editing}
        fullWidth
        bind:value={hookType}
        options={[
          { value: 'webhook', label: $t('modal.hook.typeWebhook') },
          { value: 'event', label: $t('modal.hook.typeEvent') },
          { value: 'schedule', label: $t('modal.hook.typeSchedule') },
        ]}
      />
    </FormField>
    {#if isEvent}
      <div class="events">
        <span class="events-label">{$t('modal.hook.events')}</span>
        <div class="event-list">
          {#each HOOK_EVENTS as evt (evt)}
            <Checkbox
              checked={events.has(evt)}
              label={$t(`hook.event.${evt}`)}
              description={evt}
              onChange={() => toggleEvent(evt)}
            />
          {/each}
        </div>
      </div>
    {/if}
    {#if isSchedule}
      <FormField label={$t('modal.hook.interval')} id="hkInterval">
        <Select
          fullWidth
          bind:value={interval}
          options={[
            { value: '5m', label: $t('modal.hook.interval5m') },
            { value: '15m', label: $t('modal.hook.interval15m') },
            { value: '30m', label: $t('modal.hook.interval30m') },
            { value: '1h', label: $t('modal.hook.interval1h') },
            { value: '6h', label: $t('modal.hook.interval6h') },
            { value: '12h', label: $t('modal.hook.interval12h') },
            { value: '24h', label: $t('modal.hook.interval24h') },
            { value: 'custom', label: $t('modal.hook.intervalCustom') },
          ]}
        />
      </FormField>
      {#if isCustomInterval}
        <FormField label={$t('modal.hook.cron')} id="hkCron" hint={$t('modal.hook.cronFormat')}>
          <Input placeholder="*/10 * * * *" bind:value={cron} />
        </FormField>
      {/if}
    {/if}
    <div class="script">
      <FormField label={$t('modal.hook.script')} id="hkScript">
        <Input
          multiline
          rows={10}
          placeholder={$t('modal.hook.scriptPlaceholder')}
          required
          bind:value={script}
        />
      </FormField>
      <small class="help"
        >{#each scriptHelp.split('`') as part, i (i)}{#if i % 2 === 1}<code>{part}</code
            >{:else}{part}{/if}{/each}</small
      >
    </div>
  </form>
  {#snippet footer()}
    <Button variant="ghost" onclick={() => onClose()}>{$t('action.cancel')}</Button>
    <Button
      variant="primary"
      type="submit"
      loading={submitting}
      disabled={submitting}
      form="hook-form"
    >
      {$t('action.save')}
    </Button>
  {/snippet}
</Modal>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .events {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .events-label {
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .event-list {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: var(--space-2);
    max-height: 220px;
    overflow-y: auto;
    padding: var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
  }
  .script {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .script :global(textarea) {
    font-family: var(--font-mono);
    font-size: var(--text-sm);
  }
  .help {
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .help code {
    font-family: var(--font-mono);
  }
</style>
