<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';
  import { t } from '$lib/i18n';

  interface Props { check: MonitorCheck; }
  let { check }: Props = $props();

  let details = $derived((check.state?.details ?? null) as Record<string, unknown> | null);

  let containers = $derived.by(() => {
    const list = (details?.containers ?? []) as Array<{
      name: string;
      image?: string;
      state: string;
      category: 'ok' | 'warning' | 'critical';
    }>;
    return list;
  });

  let stats = $derived.by(() => {
    const s = { total: containers.length, ok: 0, warn: 0, crit: 0 };
    for (const c of containers) {
      if (c.category === 'critical') s.crit += 1;
      else if (c.category === 'warning') s.warn += 1;
      else s.ok += 1;
    }
    return s;
  });

  let problems = $derived(
    [...containers]
      .filter((c) => c.category !== 'ok')
      .sort((a) => (a.category === 'critical' ? -1 : 1)),
  );
</script>

<div class="mon-hero mon-hero-count">
  {#if stats.total === 0}
    <span class="mon-hero-empty">—</span>
  {:else if stats.crit === 0 && stats.warn === 0}
    <div class="mon-hero-main">
      <span class="mon-hero-value mon-hero-ok">✓</span>
      <span class="mon-hero-fraction">{stats.total}</span>
    </div>
    <span class="mon-hero-sub">{$t('monitoring.docker.allOk', { count: stats.total })}</span>
  {:else}
    <div class="mon-hero-main">
      <span class="mon-hero-value">{stats.ok}</span>
      <span class="mon-hero-fraction">/ {stats.total}</span>
    </div>
    <div class="mon-hero-badge-row">
      {#if stats.crit > 0}
        <span class="mon-chip chip-crit">{stats.crit} ✗</span>
      {/if}
      {#if stats.warn > 0}
        <span class="mon-chip chip-warn">{stats.warn} ⚠</span>
      {/if}
    </div>
    <div class="mon-chip-row">
      {#each problems.slice(0, 6) as c}
        <span class="mon-chip chip-{c.category === 'critical' ? 'crit' : 'warn'}">{c.name}</span>
      {/each}
      {#if problems.length > 6}
        <span class="mon-chip chip-muted">+{problems.length - 6}</span>
      {/if}
    </div>
  {/if}
</div>
