<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';

  interface Props { check: MonitorCheck; }
  let { check }: Props = $props();

  let disks = $derived.by(() => {
    const list = ((check.state?.details as Record<string, unknown> | null)?.disks ?? []) as Array<Record<string, unknown>>;
    return list;
  });

  function num(v: unknown, fb = 0): number {
    const n = Number(v);
    return Number.isNaN(n) ? fb : n;
  }

  function badge(cat: string): { cls: string; text: string } {
    if (cat === 'critical') return { cls: 'chip-crit', text: 'CRIT' };
    if (cat === 'warning') return { cls: 'chip-warn', text: 'WARN' };
    return { cls: 'chip-ok', text: 'OK' };
  }

  function tempLevel(temp: number, warn: number, crit: number): 'ok' | 'warn' | 'crit' {
    if (temp >= crit) return 'crit';
    if (temp >= warn) return 'warn';
    return 'ok';
  }

  let maxTemp = $derived.by(() => {
    let max = 0;
    for (const d of disks) {
      const t = num(d.temp_c);
      if (t > max) max = t;
    }
    return max;
  });
</script>

<div class="mon-hero mon-hero-smart">
  {#if disks.length === 0}
    <span class="mon-hero-empty">—</span>
  {:else}
    <div class="mon-hero-main">
      <span class="mon-hero-value">{maxTemp}</span>
      <span class="mon-hero-unit">°C max</span>
    </div>
    <div class="mon-hero-bars">
      {#each disks as d}
        {@const temp = num(d.temp_c)}
        {@const warn = num(d.temp_warn) || 60}
        {@const crit = num(d.temp_crit) || 70}
        {@const lvl = tempLevel(temp, warn, crit)}
        {@const b = badge(String(d.category ?? 'ok'))}
        <div class="mon-hero-bar-row">
          <span class="mon-hero-bar-label">{d.device}</span>
          <div class="mon-hero-bar">
            <div class="mon-hero-bar-fill level-{lvl}" style="width:{Math.min((temp / crit) * 100, 100)}%"></div>
          </div>
          <span class="mon-hero-bar-pct">{temp}°C</span>
          <span class="mon-chip {b.cls}">{b.text}</span>
        </div>
      {/each}
    </div>
  {/if}
</div>
