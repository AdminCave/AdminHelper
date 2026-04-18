<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';
  import { t } from '$lib/i18n';

  interface Props { check: MonitorCheck; }
  let { check }: Props = $props();

  let details = $derived((check.state?.details ?? null) as Record<string, unknown> | null);

  let auto = $derived.by(() => {
    if (!details || details.mode !== 'auto') return null;
    return {
      failed: (details.failed ?? []) as string[],
      inactive: (details.enabled_inactive ?? []) as string[],
    };
  });

  let list = $derived.by(() => {
    if (!details || details.mode === 'auto') return null;
    return (details.watched ?? []) as Array<{ name: string; running: boolean }>;
  });

  let total = $derived.by(() => {
    if (auto) return null;
    if (!list) return null;
    const running = list.filter((s) => s.running).length;
    return { running, total: list.length };
  });

  let autoStats = $derived.by(() => {
    if (!auto) return null;
    return {
      failed: auto.failed.length,
      inactive: auto.inactive.length,
      bad: auto.failed.length + auto.inactive.length,
    };
  });
</script>

<div class="mon-hero mon-hero-service">
  {#if total}
    <div class="mon-hero-main">
      <span class="mon-hero-value">{total.running}</span>
      <span class="mon-hero-fraction">/ {total.total}</span>
    </div>
    <span class="mon-hero-sub">{$t('monitoring.hero.service.running')}</span>
    {#if list && total.running < total.total}
      <div class="mon-chip-row">
        {#each list.filter((s) => !s.running) as svc}
          <span class="mon-chip chip-crit">{svc.name}</span>
        {/each}
      </div>
    {/if}
  {:else if autoStats}
    {#if autoStats.bad === 0}
      <div class="mon-hero-main">
        <span class="mon-hero-value mon-hero-ok">✓</span>
      </div>
      <span class="mon-hero-sub">{$t('monitoring.service.allOk')}</span>
    {:else}
      <div class="mon-hero-main">
        <span class="mon-hero-value level-crit">{autoStats.bad}</span>
        <span class="mon-hero-fraction">Problem{autoStats.bad === 1 ? '' : 'e'}</span>
      </div>
      <div class="mon-chip-row">
        {#each auto?.failed ?? [] as svc}
          <span class="mon-chip chip-crit">{svc}</span>
        {/each}
        {#each auto?.inactive ?? [] as svc}
          <span class="mon-chip chip-warn">{svc}</span>
        {/each}
      </div>
    {/if}
  {:else}
    <span class="mon-hero-empty">—</span>
  {/if}
</div>
