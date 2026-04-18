<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';
  import MonSparkline from '../MonSparkline.svelte';

  interface Props { check: MonitorCheck; }
  let { check }: Props = $props();

  let status = $derived(check.state?.status || 'pending');
  let message = $derived(check.state?.message || '');

  let latency = $derived.by(() => {
    const match = message.match(/([\d.]+)\s*ms/i);
    return match ? parseFloat(match[1]) : null;
  });

  let targetLabel = $derived.by(() => {
    const cfg = (check.config ?? {}) as Record<string, unknown>;
    if (check.checkType === 'http') return String(cfg.url ?? '');
    if (check.checkType === 'tcp') return `${cfg.target ?? ''}:${cfg.port ?? ''}`;
    return String(cfg.target ?? '');
  });
</script>

<div class="mon-hero mon-hero-ping">
  <div class="mon-hero-main">
    {#if latency != null}
      <span class="mon-hero-value">{latency.toFixed(latency < 10 ? 1 : 0)}</span>
      <span class="mon-hero-unit">ms</span>
    {:else}
      <span class="mon-hero-value mon-hero-dash">—</span>
    {/if}
  </div>
  <div class="mon-hero-spark">
    <MonSparkline checkId={check.id} status={status} width={140} height={44} />
  </div>
  {#if targetLabel}
    <span class="mon-hero-sub">{targetLabel}</span>
  {/if}
</div>
