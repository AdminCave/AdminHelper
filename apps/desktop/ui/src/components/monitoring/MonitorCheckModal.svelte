<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errMsg } from '$lib/utils/errors';
  import type {
    MonitorCheck,
    MonitorCheckType,
    MonitorInterval,
    MonitorSeverity,
  } from '$lib/api/types';
  import {
    CENTRAL_SENSORS,
    SERVER_CHECK_TYPES,
    SEVERITIES,
    centralConfigFor,
    emptyCheckForm,
    checkToForm,
    failsAfterTypeChange,
    formToInput,
    intervalsFor,
    learnsBaseline,
    validateCheckForm,
    type CheckForm,
  } from '$lib/models/monitorCheck';
  import { monitoringApi } from '$lib/api/monitoring';
  import { session } from '$lib/stores/session';
  import { reportError, showStatus } from '$lib/stores/statusBar';
  import { t } from '$lib/i18n';
  import CheckConfigFields from '../monitoring/CheckConfigFields.svelte';
  import Modal from '../ui/Modal.svelte';
  import { confirmDialog } from '../ui/ConfirmDialog.svelte';

  interface Props {
    open: boolean;
    target: MonitorCheck | null;
    serverId: string;
    onClose: () => void;
    onSaved: () => void;
  }
  let { open, target, serverId, onClose, onSaved }: Props = $props();

  // Seeded for real by the $effect below whenever the modal opens; the initial
  // value must not capture the reactive `serverId` prop (svelte warning).
  let form = $state<CheckForm>(emptyCheckForm(''));
  let saving = $state(false);
  // Fails in a row from before system_state was picked in this form; leaving the
  // type with its suggested 1 gives it back (failsAfterTypeChange).
  let failsBefore: number | undefined;

  // The server's checks, for a central check's partner (R-1224); loaded once per
  // opening and only once the form is a central check, the other types never need them.
  let serverChecks = $state<MonitorCheck[]>([]);
  let checksLoaded = false;

  let isNew = $derived(target === null);
  // A central dns check compares each answer with the one it learned first.
  let canRebaseline = $derived(learnsBaseline(target));

  $effect(() => {
    if (!open) return;
    form = target ? checkToForm(target) : emptyCheckForm(serverId);
    failsBefore = undefined;
    checksLoaded = false;
    serverChecks = [];
  });

  $effect(() => {
    if (!open || form.checkType !== 'central' || checksLoaded) return;
    const s = $session;
    if (!s) return;
    checksLoaded = true;
    const sid = form.serverId;
    monitoringApi
      .fetchStatus(s)
      .then((all) => (serverChecks = all.filter((c) => c.serverId === sid)))
      .catch((err: unknown) => reportError(errMsg(err)));
  });

  async function onRebaseline(): Promise<void> {
    const s = $session;
    if (!s || !form.id) return;
    // Learned again while an answer is wrong, the wrong answer becomes the baseline.
    const confirmed = await confirmDialog($t('monitoring.checkEdit.rebaselineConfirm'), {
      confirmLabel: $t('monitoring.checkEdit.rebaseline'),
    });
    if (!confirmed) return;
    saving = true;
    try {
      await monitoringApi.rebaseline(s, form.id);
      showStatus($t('monitoring.checkEdit.rebaselined'));
      onSaved();
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      saving = false;
    }
  }

  async function onSave(): Promise<void> {
    const s = $session;
    if (!s) return;
    const result = validateCheckForm(form);
    if (!result.ok) {
      reportError(result.message ?? $t('monitoring.checkEdit.nameRequired'));
      return;
    }
    saving = true;
    try {
      const input = formToInput(form);
      if (form.id) {
        await monitoringApi.updateCheck(s, form.id, input);
        showStatus($t('monitoring.checkEdit.updated'));
      } else {
        await monitoringApi.createCheck(s, input);
        showStatus($t('monitoring.checkEdit.created'));
      }
      onSaved();
      onClose();
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      saving = false;
    }
  }

  async function onDelete(): Promise<void> {
    const s = $session;
    if (!s || !form.id) return;
    const confirmed = await confirmDialog($t('monitoring.checkEdit.deleteConfirm'), {
      confirmLabel: $t('action.delete'),
    });
    if (!confirmed) return;
    saving = true;
    try {
      await monitoringApi.removeCheck(s, form.id);
      showStatus($t('monitoring.checkEdit.deleted'));
      onSaved();
      onClose();
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      saving = false;
    }
  }
</script>

<Modal
  {open}
  title={isNew ? $t('monitoring.checkEdit.new') : form.name || $t('monitoring.checkEdit.edit')}
  width="640px"
  {onClose}
>
  <div class="form-grid">
    <label class="field">
      <span class="field-label">{$t('infra.field.name')}</span>
      <input type="text" bind:value={form.name} required />
    </label>

    <label class="field">
      <span class="field-label">{$t('monitoring.checkEdit.type')}</span>
      <select
        value={form.checkType}
        onchange={(e) => {
          const next = e.currentTarget.value as MonitorCheckType;
          if (next === 'system_state') failsBefore = form.consecutiveFails;
          form.consecutiveFails = failsAfterTypeChange(
            form.checkType,
            next,
            form.consecutiveFails,
            failsBefore,
          );
          form.checkType = next;
          if (next === 'central') {
            form.config = centralConfigFor('tls', {});
            form.interval = CENTRAL_SENSORS.tls.defaultInterval;
          } else {
            form.config = {};
          }
        }}
      >
        {#each SERVER_CHECK_TYPES as ct (ct)}
          <option value={ct}>{ct}</option>
        {/each}
      </select>
    </label>

    <label class="field">
      <span class="field-label">{$t('monitoring.checkEdit.interval')}</span>
      <select
        value={form.interval}
        onchange={(e) => (form.interval = e.currentTarget.value as MonitorInterval)}
      >
        {#each intervalsFor(form.checkType, form.config) as iv (iv)}
          <option value={iv}>{iv}</option>
        {/each}
      </select>
    </label>

    <label class="field">
      <span class="field-label">{$t('monitoring.checkEdit.severity')}</span>
      <select
        value={form.severity}
        onchange={(e) => (form.severity = e.currentTarget.value as MonitorSeverity)}
      >
        {#each SEVERITIES as sv (sv)}
          <option value={sv}>{sv}</option>
        {/each}
      </select>
    </label>

    <label class="field">
      <span class="field-label">{$t('monitoring.checkEdit.consecutiveFails')}</span>
      <input
        type="number"
        min="1"
        value={form.consecutiveFails}
        oninput={(e) => (form.consecutiveFails = Number(e.currentTarget.value) || 1)}
      />
    </label>

    <label class="field">
      <span class="field-label">{$t('monitoring.checkEdit.consecutiveOks')}</span>
      <input
        type="number"
        min="1"
        max="100"
        value={form.consecutiveOks}
        oninput={(e) => (form.consecutiveOks = Number(e.currentTarget.value) || 1)}
      />
    </label>

    <label class="field" style="grid-column: span 2;">
      <span class="field-label">{$t('monitoring.checkEdit.description')}</span>
      <textarea rows="2" bind:value={form.description}></textarea>
    </label>

    <CheckConfigFields
      checkType={form.checkType}
      config={form.config}
      {serverChecks}
      onSensorChange={(sensor) => (form.interval = CENTRAL_SENSORS[sensor].defaultInterval)}
    />
  </div>

  {#snippet footer()}
    {#if !isNew}
      <button class="btn danger" onclick={onDelete} disabled={saving}>{$t('action.delete')}</button>
    {/if}
    {#if canRebaseline}
      <button class="btn" onclick={onRebaseline} disabled={saving}>
        {$t('monitoring.checkEdit.rebaseline')}
      </button>
    {/if}
    <div style="flex: 1;"></div>
    <button class="btn" onclick={onClose} disabled={saving}>{$t('action.cancel')}</button>
    <button class="btn primary" onclick={onSave} disabled={saving}>{$t('action.save')}</button>
  {/snippet}
</Modal>

<style>
  .form-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--sp-4);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .field-label {
    font-size: 12px;
    color: var(--text-muted);
  }
  .field input,
  .field select,
  .field textarea {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-2) var(--sp-3);
    font-size: 13px;
    font-family: inherit;
  }
  .field input:focus,
  .field select:focus,
  .field textarea:focus {
    outline: 1px solid var(--accent);
  }
</style>
