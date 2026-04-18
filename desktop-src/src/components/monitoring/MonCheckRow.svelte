<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';
  import { statusClass, formatCheckTime } from '$lib/models/monitoring';
  import { toggleCheck, runCheck, toggleExpanded, monitoring } from '$lib/stores/monitoring';
  import MonDetailPanel from './MonDetailPanel.svelte';

  interface Props { check: MonitorCheck; }
  let { check }: Props = $props();

  let expanded = $derived($monitoring.expandedCheckId === check.id);
  let status = $derived(check.state?.status || 'pending');

  function onToggle(e: MouseEvent | KeyboardEvent): void {
    e.stopPropagation();
    void toggleCheck(check.id);
  }
  function onRun(e: MouseEvent | KeyboardEvent): void {
    e.stopPropagation();
    void runCheck(check.id);
  }
  function onClick(): void {
    toggleExpanded(check.id);
  }
</script>

<div class="mon-check-row-wrapper" class:open={expanded}>
  <div
    class="mon-check-row"
    data-check-id={check.id}
    role="button"
    tabindex="0"
    onclick={onClick}
    onkeydown={(e) => e.key === 'Enter' && onClick()}
  >
    <span class="mon-dot {statusClass(status)}"></span>
    <span class="mon-type-badge badge-{check.checkType}">{check.checkType.toUpperCase()}</span>
    <span class="mon-check-name">{check.name}</span>
    <span class="mon-check-msg">{check.state?.message || ''}</span>
    <span class="mon-check-time">{formatCheckTime(check.state?.lastCheck)}</span>
    <div class="mon-check-actions">
      <button
        class="btn small {check.enabled ? 'ghost' : 'primary'}"
        onclick={onToggle}
        onkeydown={(e) => e.key === 'Enter' && onToggle(e)}
      >
        {check.enabled ? 'Deaktivieren' : 'Aktivieren'}
      </button>
      <button
        class="btn small accent"
        onclick={onRun}
        onkeydown={(e) => e.key === 'Enter' && onRun(e)}
      >
        Jetzt pruefen
      </button>
    </div>
  </div>

  {#if expanded}
    <MonDetailPanel {check} />
  {/if}
</div>
