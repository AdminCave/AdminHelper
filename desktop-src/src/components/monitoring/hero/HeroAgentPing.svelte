<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';
  import { t } from '$lib/i18n';

  interface Props { check: MonitorCheck; }
  let { check }: Props = $props();

  let status = $derived(check.state?.status || 'pending');
  let message = $derived(check.state?.message || '');

  let seconds = $derived.by(() => {
    const match = message.match(/(\d+)/);
    return match ? parseInt(match[1], 10) : null;
  });

  let display = $derived.by(() => {
    if (seconds == null) return { value: '—', unit: '' };
    if (seconds < 60) return { value: String(seconds), unit: 's' };
    if (seconds < 3600) return { value: String(Math.round(seconds / 60)), unit: 'min' };
    return { value: (seconds / 3600).toFixed(1), unit: 'h' };
  });

  let cfg = $derived((check.config ?? {}) as Record<string, unknown>);
  let staleMin = $derived(Number(cfg.stale_minutes ?? 5));
</script>

<div class="mon-hero mon-hero-ping">
  <div class="mon-hero-main">
    <span class="mon-hero-value">{display.value}</span>
    <span class="mon-hero-unit">{display.unit}</span>
  </div>
  <div class="mon-hero-spark mon-hero-icon status-{status}" aria-hidden="true">
    <svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
      <path d="M2 12a16 16 0 0 1 20 0" opacity="0.4" />
      <path d="M5 16a11 11 0 0 1 14 0" opacity="0.7" />
      <path d="M8.5 19.5a6 6 0 0 1 7 0" />
      <circle cx="12" cy="22" r="1" fill="currentColor" />
    </svg>
  </div>
  <span class="mon-hero-sub">{$t('monitoring.agentPing.lastSeen')} · Stale &gt; {staleMin} min</span>
</div>
