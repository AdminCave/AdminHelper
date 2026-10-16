<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { MonitorCheck } from '$lib/api/types';
  import {
    statusClass,
    formatCheckTime,
    canRunManually,
    isPushOnlyCheck,
  } from '$lib/models/monitoring';
  import {
    toggleExpanded,
    monitoring,
    toggleCheck,
    runCheck,
    resetCheck,
    openCheckEditor,
  } from '$lib/stores/monitoring';
  import MonSectionIcon from './MonSectionIcon.svelte';
  import ExpandChart from './ExpandChart.svelte';
  import { confirmDialog } from '../../ui/ConfirmDialog.svelte';
  import { t } from '$lib/i18n';

  // The editor's words for the template fields a user can change; overriddenFields
  // names them as the request body does.
  const FIELD_LABELS = new Map<string, string>([
    ['name', 'infra.field.name'],
    ['description', 'monitoring.checkEdit.description'],
    ['check_type', 'monitoring.checkEdit.type'],
    ['config', 'monitoring.check.field.config'],
    ['enabled', 'monitoring.check.field.enabled'],
    ['interval', 'monitoring.checkEdit.interval'],
    ['severity', 'monitoring.checkEdit.severity'],
    ['consecutive_fails', 'monitoring.checkEdit.consecutiveFails'],
  ]);

  interface Props {
    check: MonitorCheck;
    label: Snippet;
    value?: Snippet;
    extraBody?: Snippet;
    showChart?: boolean;
    dense?: boolean;
  }
  let { check, label, value, extraBody, showChart = true, dense = false }: Props = $props();

  let status = $derived(check.state?.status || 'pending');
  // A manual run is a no-op for push-evaluated and disabled checks — the backend
  // answers 409. Do not offer a dead action; explain why instead.
  let runnable = $derived(canRunManually(check));
  let runBlockedReason = $derived(
    isPushOnlyCheck(check.checkType)
      ? $t('monitoring.check.runPushOnly')
      : $t('monitoring.check.runDisabled'),
  );
  let expanded = $derived($monitoring.expandedCheckId === check.id);
  // Only a template check can differ from its template. A field this UI does not
  // know yet shows by its raw name rather than as a gap.
  let overridden = $derived(check.templateId ? (check.overriddenFields ?? []) : []);
  let overriddenNames = $derived(
    overridden
      .map((field) => {
        const key = FIELD_LABELS.get(field);
        return key ? $t(key) : field;
      })
      .join(', '),
  );

  function onClick(): void {
    toggleExpanded(check.id);
  }

  function onToggle(e: MouseEvent | KeyboardEvent): void {
    e.stopPropagation();
    void toggleCheck(check.id);
  }

  function onEdit(e: MouseEvent | KeyboardEvent): void {
    e.stopPropagation();
    openCheckEditor(check, check.serverId ?? '');
  }

  function onRun(e: MouseEvent | KeyboardEvent): void {
    e.stopPropagation();
    void runCheck(check.id);
  }

  async function onReset(e: MouseEvent): Promise<void> {
    e.stopPropagation();
    const id = check.id;
    const ok = await confirmDialog(
      $t('monitoring.check.resetConfirm', { fields: overriddenNames }),
      { confirmLabel: $t('monitoring.check.resetToTemplate') },
    );
    if (ok) await resetCheck(id);
  }
</script>

<div class="mon-line-wrapper" class:open={expanded} class:disabled={!check.enabled}>
  <div
    class="mon-line"
    class:dense
    role="button"
    tabindex="0"
    onclick={onClick}
    onkeydown={(e) => e.key === 'Enter' && onClick()}
  >
    <span class="mon-dot {statusClass(status)}"></span>
    <span class="mon-line-label">
      {@render label()}
      {#if overridden.length > 0}
        <span
          class="mon-line-pill mon-line-badge"
          title={$t('monitoring.check.overriddenHint', { fields: overriddenNames })}
        >
          {$t('monitoring.check.overridden')}
        </span>
      {/if}
    </span>
    {#if value}
      <span class="mon-line-value">{@render value()}</span>
    {/if}
    <span class="mon-line-time">{formatCheckTime(check.state?.lastCheck)}</span>
    <div class="mon-line-actions">
      <button
        class="mon-line-action"
        onclick={onEdit}
        onkeydown={(e) => e.key === 'Enter' && onEdit(e)}
        title={$t('action.edit')}
        aria-label={$t('action.edit')}
      >
        <MonSectionIcon name="edit" />
      </button>
      {#if overridden.length > 0}
        <!-- Enter clicks a button by itself; the key only must not reach the row,
             which would expand. -->
        <button
          class="mon-line-action"
          onclick={onReset}
          onkeydown={(e) => e.key === 'Enter' && e.stopPropagation()}
          title={$t('monitoring.check.resetToTemplate')}
          aria-label={$t('monitoring.check.resetToTemplate')}
        >
          <MonSectionIcon name="reset" />
        </button>
      {/if}
      <button
        class="mon-line-action"
        onclick={onRun}
        onkeydown={(e) => e.key === 'Enter' && onRun(e)}
        disabled={!runnable}
        title={runnable ? $t('monitoring.check.runNow') : runBlockedReason}
        aria-label={runnable ? $t('monitoring.check.runNow') : runBlockedReason}
      >
        <MonSectionIcon name="play" />
      </button>
      <button
        class="mon-line-action"
        class:muted={!check.enabled}
        onclick={onToggle}
        onkeydown={(e) => e.key === 'Enter' && onToggle(e)}
        title={check.enabled ? $t('monitoring.check.disable') : $t('monitoring.check.enable')}
        aria-label={check.enabled ? $t('monitoring.check.disable') : $t('monitoring.check.enable')}
      >
        <MonSectionIcon name="power" />
      </button>
    </div>
    <span class="mon-line-chevron" class:open={expanded}>
      <MonSectionIcon name="chevron" />
    </span>
  </div>

  {#if expanded}
    <div class="mon-line-expand">
      {#if check.state?.message}
        <div class="mon-line-msg">{check.state.message}</div>
      {/if}
      {#if extraBody}
        {@render extraBody()}
      {/if}
      {#if showChart}
        <ExpandChart {check} />
      {/if}
    </div>
  {/if}
</div>
