<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';

  interface Props { check: MonitorCheck; }
  let { check }: Props = $props();

  let pools = $derived.by(() => {
    const list = ((check.state?.details as Record<string, unknown> | null)?.pools ?? []) as Array<{
      name: string;
      health: string;
      capacityPercent: number;
    }>;
    return list;
  });

  let cfg = $derived((check.config ?? {}) as Record<string, unknown>);
  let capWarn = $derived(Number(cfg.capacity_warn ?? 80));
  let capCrit = $derived(Number(cfg.capacity_crit ?? 90));

  function level(pct: number): 'ok' | 'warn' | 'crit' {
    if (pct >= capCrit) return 'crit';
    if (pct >= capWarn) return 'warn';
    return 'ok';
  }

  function healthBadge(h: string): { cls: string; text: string } {
    if (h === 'ONLINE') return { cls: 'chip-ok', text: 'ONLINE' };
    if (h === 'DEGRADED') return { cls: 'chip-warn', text: 'DEGRADED' };
    return { cls: 'chip-crit', text: h };
  }
</script>

<div class="mon-hero mon-hero-multi">
  {#if pools.length === 0}
    <span class="mon-hero-empty">—</span>
  {:else}
    <div class="mon-hero-bars">
      {#each pools as p}
        {@const lvl = level(p.capacityPercent)}
        {@const badge = healthBadge(p.health)}
        <div class="mon-hero-bar-row">
          <span class="mon-hero-bar-label">{p.name}</span>
          <div class="mon-hero-bar">
            <div class="mon-hero-bar-fill level-{lvl}" style="width:{Math.min(p.capacityPercent, 100)}%"></div>
          </div>
          <span class="mon-hero-bar-pct">{p.capacityPercent}%</span>
          <span class="mon-chip {badge.cls}">{badge.text}</span>
        </div>
      {/each}
    </div>
  {/if}
</div>
