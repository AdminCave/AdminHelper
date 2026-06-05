<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { MonitorCheck } from '$lib/api/types';
  import { statusClass, formatCheckTime } from '$lib/models/monitoring';
  import { toggleExpanded, monitoring, toggleCheck, runCheck } from '$lib/stores/monitoring';
  import MonSectionIcon from './MonSectionIcon.svelte';
  import ExpandChart from './ExpandChart.svelte';
  import { t } from '$lib/i18n';

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
  let expanded = $derived($monitoring.expandedCheckId === check.id);

  function onClick(): void {
    toggleExpanded(check.id);
  }

  function onToggle(e: MouseEvent | KeyboardEvent): void {
    e.stopPropagation();
    void toggleCheck(check.id);
  }

  function onRun(e: MouseEvent | KeyboardEvent): void {
    e.stopPropagation();
    void runCheck(check.id);
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
    <span class="mon-line-label">{@render label()}</span>
    {#if value}
      <span class="mon-line-value">{@render value()}</span>
    {/if}
    <span class="mon-line-time">{formatCheckTime(check.state?.lastCheck)}</span>
    <div class="mon-line-actions">
      <button
        class="mon-line-action"
        onclick={onRun}
        onkeydown={(e) => e.key === 'Enter' && onRun(e)}
        title={$t('monitoring.check.runNow')}
        aria-label={$t('monitoring.check.runNow')}
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
