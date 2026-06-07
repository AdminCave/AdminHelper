<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';
  import { worstStatus } from '$lib/models/monitoring';
  import MonSectionHeader from './MonSectionHeader.svelte';
  import MonCheckLine from './MonCheckLine.svelte';
  import { t } from '$lib/i18n';

  interface Props {
    checks: MonitorCheck[];
  }
  let { checks }: Props = $props();

  let worst = $derived(worstStatus(checks));

  function num(v: unknown, fb = 0): number {
    const n = Number(v);
    return Number.isNaN(n) ? fb : n;
  }
  function level(pct: number, warn: number, crit: number): 'ok' | 'warn' | 'crit' {
    if (pct >= crit) return 'crit';
    if (pct >= warn) return 'warn';
    return 'ok';
  }

  const R = 26;
  const C = 2 * Math.PI * R;
  function ringDash(pct: number): string {
    const clamped = Math.min(Math.max(pct, 0), 100);
    const filled = (clamped / 100) * C;
    return `${filled.toFixed(1)} ${(C - filled).toFixed(1)}`;
  }

  interface Ring {
    label: string;
    pct: number;
    level: 'ok' | 'warn' | 'crit';
    sub: string | null;
  }
  interface DiskBar {
    mount: string;
    pct: number;
    level: 'ok' | 'warn' | 'crit';
    sub: string | null;
  }

  function rings(check: MonitorCheck): Ring[] {
    const d = (check.state?.details ?? null) as Record<string, unknown> | null;
    const cfg = (check.config ?? {}) as Record<string, unknown>;
    if (!d) return [];
    const out: Ring[] = [];
    if (d.cpu != null) {
      const pct = num(d.cpu);
      out.push({
        label: 'CPU',
        pct,
        level: level(pct, num(cfg.cpu_warn, 80), num(cfg.cpu_crit, 95)),
        sub: null,
      });
    }
    if (d.memory != null) {
      const pct = num(d.memory);
      const sub =
        d.memory_total_mb != null
          ? `${num(d.memory_used_mb)} / ${num(d.memory_total_mb)} MB`
          : null;
      out.push({
        label: 'RAM',
        pct,
        level: level(pct, num(cfg.memory_warn, 80), num(cfg.memory_crit, 95)),
        sub,
      });
    }
    return out;
  }
  function disks(check: MonitorCheck): DiskBar[] {
    const d = (check.state?.details ?? null) as Record<string, unknown> | null;
    const cfg = (check.config ?? {}) as Record<string, unknown>;
    if (!d) return [];
    const list = (d.disks ?? []) as Array<Record<string, unknown>>;
    return list.map((x) => {
      const pct = num(x.percent);
      return {
        mount: String(x.mount ?? '?'),
        pct,
        level: level(pct, num(cfg.disk_warn, 85), num(cfg.disk_crit, 95)),
        sub:
          x.total_gb != null
            ? `${num(x.used_gb).toFixed(1)} / ${num(x.total_gb).toFixed(1)} GB`
            : null,
      };
    });
  }
</script>

<section class="mon-section">
  <MonSectionHeader
    icon="live"
    title={$t('monitoring.section.live')}
    {worst}
    count={checks.length}
  />

  <div class="mon-section-body">
    {#each checks as check (check.id)}
      <MonCheckLine {check}>
        {#snippet label()}
          <span class="mon-line-name">{check.name}</span>
        {/snippet}
        {#snippet value()}
          <span class="mon-live-summary">
            {#each rings(check) as r (r.label)}
              <span class="mon-live-pill level-{r.level}">{r.label} {r.pct.toFixed(0)}%</span>
            {/each}
            {#if disks(check).length > 0}
              <span class="mon-live-pill"
                >{disks(check).length} Disk{disks(check).length === 1 ? '' : 's'}</span
              >
            {/if}
          </span>
        {/snippet}
        {#snippet extraBody()}
          <div class="mon-live-detail">
            {#if rings(check).length > 0}
              <div class="mon-ring-row">
                {#each rings(check) as r (r.label)}
                  <div class="mon-ring level-{r.level}">
                    <svg viewBox="0 0 64 64" width="64" height="64" aria-hidden="true">
                      <circle
                        cx="32"
                        cy="32"
                        r={R}
                        class="mon-ring-track"
                        fill="none"
                        stroke-width="6"
                      />
                      <circle
                        cx="32"
                        cy="32"
                        r={R}
                        fill="none"
                        stroke-width="6"
                        stroke-linecap="round"
                        class="mon-ring-progress"
                        stroke-dasharray={ringDash(r.pct)}
                        transform="rotate(-90 32 32)"
                      />
                    </svg>
                    <span class="mon-ring-pct">{r.pct.toFixed(0)}%</span>
                    <span class="mon-ring-label">{r.label}</span>
                    {#if r.sub}<span class="mon-ring-sub">{r.sub}</span>{/if}
                  </div>
                {/each}
              </div>
            {/if}
            {#if disks(check).length > 0}
              <div class="mon-hero-bars">
                {#each disks(check) as d (d.mount)}
                  <div class="mon-hero-bar-row">
                    <span class="mon-hero-bar-label">{d.mount}</span>
                    <div class="mon-hero-bar">
                      <div
                        class="mon-hero-bar-fill level-{d.level}"
                        style="width:{Math.min(d.pct, 100)}%"
                      ></div>
                    </div>
                    <span class="mon-hero-bar-pct">{d.pct.toFixed(0)}%</span>
                    {#if d.sub}<span class="mon-hero-bar-sub">{d.sub}</span>{/if}
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        {/snippet}
      </MonCheckLine>
    {/each}
  </div>
</section>
