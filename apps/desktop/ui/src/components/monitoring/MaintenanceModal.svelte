<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errMsg } from '$lib/utils/errors';
  import type { MaintenanceInput, MaintenanceWindow } from '$lib/api/types';
  import { monitoringApi } from '$lib/api/monitoring';
  import { session } from '$lib/stores/session';
  import { reportError, showStatus } from '$lib/stores/statusBar';
  import { t } from '$lib/i18n';
  import Modal from '../ui/Modal.svelte';
  import { confirmDialog } from '../ui/ConfirmDialog.svelte';

  interface Props {
    open: boolean;
    editing: MaintenanceWindow | null;
    serverId: string;
    onClose: () => void;
    onSaved: () => void;
  }
  let { open, editing, serverId, onClose, onSaved }: Props = $props();

  let kind = $state<'once' | 'weekly'>('once');
  let startsLocal = $state('');
  let endsLocal = $state('');
  let weekdays = $state<number[]>([]);
  let startTime = $state('02:00');
  let durationMinutes = $state(120);
  let tz = $state('UTC');
  let note = $state('');
  let isGlobal = $state(false);
  let enabled = $state(true);
  let saving = $state(false);

  let isNew = $derived(editing === null);
  const DAYS = [0, 1, 2, 3, 4, 5, 6];

  function clientTimezone(): string {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch {
      return 'UTC';
    }
  }

  // One-off windows travel as UTC ISO (backend stores naive UTC); the inputs
  // are datetime-local, so convert local wall clock <-> UTC here.
  function utcIsoToLocalInput(iso: string | null | undefined): string {
    if (!iso) return '';
    const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`);
    if (Number.isNaN(d.getTime())) return '';
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  function localInputToUtcIso(v: string): string | null {
    if (!v) return null;
    const d = new Date(v); // interpreted in the client's local zone
    return Number.isNaN(d.getTime()) ? null : d.toISOString();
  }

  $effect(() => {
    if (!open) return;
    kind = editing?.kind ?? 'once';
    startsLocal = utcIsoToLocalInput(editing?.startsAt);
    endsLocal = utcIsoToLocalInput(editing?.endsAt);
    weekdays = editing?.weekdays ? [...editing.weekdays] : [];
    startTime = editing?.startTime ?? '02:00';
    durationMinutes = editing?.durationMinutes ?? 120;
    // Timezone default = the client's zone — the wall-clock the user thinks in.
    tz = editing?.timezone ?? clientTimezone();
    note = editing?.note ?? '';
    isGlobal = editing ? editing.serverId == null : false;
    enabled = editing?.enabled ?? true;
  });

  function buildInput(): MaintenanceInput | null {
    if (kind === 'once') {
      const starts = localInputToUtcIso(startsLocal);
      const ends = localInputToUtcIso(endsLocal);
      // Client-side ends>starts check: the backend rejects it too, but as a
      // raw 422 instead of the friendly validation message.
      if (!starts || !ends || ends <= starts) return null;
      return {
        server_id: isGlobal ? null : serverId,
        note: note.trim() || null,
        kind,
        starts_at: starts,
        ends_at: ends,
        weekdays: [],
        start_time: null,
        duration_minutes: null,
        timezone: tz.trim() || 'UTC',
        enabled,
      };
    }
    if (weekdays.length === 0 || !startTime || !durationMinutes) return null;
    return {
      server_id: isGlobal ? null : serverId,
      note: note.trim() || null,
      kind,
      starts_at: null,
      ends_at: null,
      weekdays: [...weekdays].sort(),
      start_time: startTime,
      duration_minutes: durationMinutes,
      timezone: tz.trim() || 'UTC',
      enabled,
    };
  }

  async function onSave(): Promise<void> {
    const s = $session;
    if (!s) return;
    const input = buildInput();
    if (!input) {
      reportError($t('monitoring.maint.validation'));
      return;
    }
    saving = true;
    try {
      if (editing) await monitoringApi.updateMaintenance(s, editing.id, input);
      else await monitoringApi.createMaintenance(s, input);
      showStatus($t('monitoring.maint.saved'));
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
    if (!s || !editing) return;
    const confirmed = await confirmDialog($t('monitoring.maint.deleteConfirm'), {
      confirmLabel: $t('action.delete'),
    });
    if (!confirmed) return;
    saving = true;
    try {
      await monitoringApi.removeMaintenance(s, editing.id);
      showStatus($t('monitoring.maint.deleted'));
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
  title={isNew ? $t('monitoring.maint.new') : $t('monitoring.maint.edit')}
  width="560px"
  {onClose}
>
  <div class="form-grid">
    <label class="field">
      <span class="field-label">{$t('monitoring.maint.kind')}</span>
      <select value={kind} onchange={(e) => (kind = e.currentTarget.value as 'once' | 'weekly')}>
        <option value="once">{$t('monitoring.maint.kindOnce')}</option>
        <option value="weekly">{$t('monitoring.maint.kindWeekly')}</option>
      </select>
    </label>

    <label class="field">
      <span class="field-label">{$t('monitoring.maint.note')}</span>
      <input type="text" bind:value={note} />
    </label>

    {#if kind === 'once'}
      <label class="field">
        <span class="field-label">{$t('monitoring.maint.from')}</span>
        <input type="datetime-local" bind:value={startsLocal} />
      </label>
      <label class="field">
        <span class="field-label">{$t('monitoring.maint.until')}</span>
        <input type="datetime-local" bind:value={endsLocal} />
      </label>
    {:else}
      <div class="field span2">
        <span class="field-label">{$t('monitoring.maint.weekdays')}</span>
        <div class="day-row">
          {#each DAYS as d (d)}
            <label class="day-choice">
              <input type="checkbox" value={d} bind:group={weekdays} />
              <span>{$t(`monitoring.maint.day.${d}`)}</span>
            </label>
          {/each}
        </div>
      </div>
      <label class="field">
        <span class="field-label">{$t('monitoring.maint.startTime')}</span>
        <input type="time" bind:value={startTime} />
      </label>
      <label class="field">
        <span class="field-label">{$t('monitoring.maint.duration')}</span>
        <input type="number" min="1" max="1440" bind:value={durationMinutes} />
      </label>
      <label class="field span2">
        <span class="field-label">{$t('monitoring.maint.timezone')}</span>
        <input type="text" bind:value={tz} placeholder="Europe/Berlin" />
      </label>
    {/if}

    <label class="field checkbox">
      <input type="checkbox" bind:checked={isGlobal} />
      <span>{$t('monitoring.maint.global')}</span>
    </label>
    <label class="field checkbox">
      <input type="checkbox" bind:checked={enabled} />
      <span>{$t('monitoring.maint.enabled')}</span>
    </label>
  </div>

  {#snippet footer()}
    {#if !isNew}
      <button class="btn danger" onclick={onDelete} disabled={saving}>{$t('action.delete')}</button>
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
  .field.span2 {
    grid-column: span 2;
  }
  .field.checkbox {
    flex-direction: row;
    align-items: center;
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
  .day-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-3);
  }
  .day-choice {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1, 4px);
    font-size: 13px;
  }
</style>
