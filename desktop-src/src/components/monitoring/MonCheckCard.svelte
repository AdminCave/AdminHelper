<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';
  import { statusClass, formatCheckTime } from '$lib/models/monitoring';
  import { toggleCheck, runCheck, toggleExpanded, monitoring } from '$lib/stores/monitoring';
  import MonDetailPanel from './MonDetailPanel.svelte';
  import HeroRouter from './hero/HeroRouter.svelte';
  import { t } from '$lib/i18n';

  interface Props { check: MonitorCheck; }
  let { check }: Props = $props();

  let expanded = $derived($monitoring.expandedCheckId === check.id);
  let status = $derived(check.state?.status || 'pending');
  let message = $derived(check.state?.message || '');

  let running = $state(false);

  function onCardClick(): void {
    toggleExpanded(check.id);
  }

  async function onToggle(e: MouseEvent | KeyboardEvent): Promise<void> {
    e.stopPropagation();
    await toggleCheck(check.id);
  }

  async function onRun(e: MouseEvent | KeyboardEvent): Promise<void> {
    e.stopPropagation();
    if (running) return;
    running = true;
    try {
      await runCheck(check.id);
    } finally {
      setTimeout(() => { running = false; }, 2000);
    }
  }
</script>

<div class="mon-check-card {statusClass(status)}" class:open={expanded} class:disabled={!check.enabled}>
  <div
    class="mon-card-body"
    role="button"
    tabindex="0"
    onclick={onCardClick}
    onkeydown={(e) => e.key === 'Enter' && onCardClick()}
  >
    <span class="mon-card-stripe"></span>

    <div class="mon-card-head">
      <span class="mon-type-badge badge-{check.checkType}">{check.checkType.toUpperCase()}</span>
      <span class="mon-card-name">{check.name}</span>
      <span class="mon-card-time">{formatCheckTime(check.state?.lastCheck)}</span>
      <div class="mon-card-actions">
        <button
          class="btn small {check.enabled ? 'ghost' : 'primary'}"
          onclick={onToggle}
          onkeydown={(e) => e.key === 'Enter' && onToggle(e)}
          title={check.enabled ? $t('monitoring.check.disable') : $t('monitoring.check.enable')}
        >
          {check.enabled ? $t('monitoring.check.disable') : $t('monitoring.check.enable')}
        </button>
        <button
          class="btn small accent"
          onclick={onRun}
          onkeydown={(e) => e.key === 'Enter' && onRun(e)}
          disabled={running}
        >
          {running ? '…' : $t('monitoring.check.runNow')}
        </button>
      </div>
    </div>

    <div class="mon-card-hero">
      <HeroRouter {check} />
    </div>

    {#if message}
      <div class="mon-card-msg">{message}</div>
    {/if}
  </div>

  {#if expanded}
    <MonDetailPanel {check} />
  {/if}
</div>
