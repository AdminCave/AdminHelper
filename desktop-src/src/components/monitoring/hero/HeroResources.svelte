<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';

  interface Props { check: MonitorCheck; }
  let { check }: Props = $props();

  let details = $derived((check.state?.details ?? null) as Record<string, unknown> | null);
  let cfg = $derived((check.config ?? {}) as Record<string, unknown>);

  function num(v: unknown, fb = 0): number {
    const n = Number(v);
    return Number.isNaN(n) ? fb : n;
  }

  function level(pct: number, warn: number, crit: number): 'ok' | 'warn' | 'crit' {
    if (pct >= crit) return 'crit';
    if (pct >= warn) return 'warn';
    return 'ok';
  }

  interface Ring {
    label: string;
    pct: number;
    level: 'ok' | 'warn' | 'crit';
    sub: string | null;
  }

  let rings = $derived.by<Ring[]>(() => {
    if (!details) return [];
    const out: Ring[] = [];
    if (details.cpu != null) {
      const pct = num(details.cpu);
      out.push({
        label: 'CPU',
        pct,
        level: level(pct, num(cfg.cpu_warn, 80), num(cfg.cpu_crit, 95)),
        sub: null,
      });
    }
    if (details.memory != null) {
      const pct = num(details.memory);
      const sub =
        details.memory_total_mb != null
          ? `${num(details.memory_used_mb)}/${num(details.memory_total_mb)} MB`
          : null;
      out.push({
        label: 'RAM',
        pct,
        level: level(pct, num(cfg.memory_warn, 80), num(cfg.memory_crit, 95)),
        sub,
      });
    }
    return out;
  });

  let disks = $derived.by(() => {
    if (!details) return [];
    const ds = (details.disks ?? []) as Array<Record<string, unknown>>;
    return ds.map((d) => {
      const pct = num(d.percent);
      return {
        mount: String(d.mount ?? '?'),
        pct,
        level: level(pct, num(cfg.disk_warn, 85), num(cfg.disk_crit, 95)),
        sub:
          d.total_gb != null
            ? `${num(d.used_gb).toFixed(1)}/${num(d.total_gb).toFixed(1)} GB`
            : null,
      };
    });
  });

  function ringDash(pct: number, circumference: number): string {
    const clamped = Math.min(Math.max(pct, 0), 100);
    const filled = (clamped / 100) * circumference;
    return `${filled.toFixed(1)} ${(circumference - filled).toFixed(1)}`;
  }

  const R = 26;
  const C = 2 * Math.PI * R;
</script>

<div class="mon-hero mon-hero-resources">
  {#if rings.length > 0}
    <div class="mon-ring-row">
      {#each rings as r}
        <div class="mon-ring level-{r.level}">
          <svg viewBox="0 0 64 64" width="64" height="64" aria-hidden="true">
            <circle cx="32" cy="32" r={R} class="mon-ring-track" fill="none" stroke-width="6" />
            <circle
              cx="32"
              cy="32"
              r={R}
              fill="none"
              stroke-width="6"
              stroke-linecap="round"
              class="mon-ring-progress"
              stroke-dasharray={ringDash(r.pct, C)}
              transform="rotate(-90 32 32)"
            />
          </svg>
          <span class="mon-ring-pct">{r.pct.toFixed(0)}%</span>
          <span class="mon-ring-label">{r.label}</span>
          {#if r.sub}
            <span class="mon-ring-sub">{r.sub}</span>
          {/if}
        </div>
      {/each}
    </div>
  {/if}

  {#if disks.length > 0}
    <div class="mon-hero-bars">
      {#each disks as d}
        <div class="mon-hero-bar-row">
          <span class="mon-hero-bar-label">{d.mount}</span>
          <div class="mon-hero-bar">
            <div class="mon-hero-bar-fill level-{d.level}" style="width:{Math.min(d.pct, 100)}%"></div>
          </div>
          <span class="mon-hero-bar-pct">{d.pct.toFixed(0)}%</span>
          {#if d.sub}<span class="mon-hero-bar-sub">{d.sub}</span>{/if}
        </div>
      {/each}
    </div>
  {/if}

  {#if rings.length === 0 && disks.length === 0}
    <span class="mon-hero-empty">—</span>
  {/if}
</div>
