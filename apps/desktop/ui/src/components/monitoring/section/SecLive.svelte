<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitorCheck, MonitorResourceDetails } from '$lib/api/types';
  import { resourceDetails } from '$lib/models/checkDetails';
  import { worstStatus } from '$lib/models/monitoring';
  import MonSectionHeader from './MonSectionHeader.svelte';
  import MonCheckLine from './MonCheckLine.svelte';
  import { t } from '$lib/i18n';

  interface Props {
    checks: MonitorCheck[];
  }
  let { checks }: Props = $props();

  let worst = $derived(worstStatus(checks));

  type Level = 'ok' | 'warn' | 'crit';

  function num(v: unknown, fb = 0): number {
    const n = Number(v);
    return Number.isNaN(n) ? fb : n;
  }
  function level(pct: number, warn: number, crit: number): Level {
    if (pct >= crit) return 'crit';
    if (pct >= warn) return 'warn';
    return 'ok';
  }

  const PROBLEM_LEVEL = new Map<string, Level>([
    ['warning', 'warn'],
    ['critical', 'crit'],
  ]);
  const ORDER: Record<Level, number> = { ok: 0, warn: 1, crit: 2 };

  // The checker's own rating: only it knows the free-GB gate, the thresholds per
  // mount and the hysteresis, so a metric missing from problems is ok. Details
  // without problems (written before the per-metric hysteresis) keep the rating
  // from the config.
  function rate(d: MonitorResourceDetails, key: string, fromConfig: Level): Level {
    if (!d.problems) return fromConfig;
    return PROBLEM_LEVEL.get(d.problems[key] ?? '') ?? 'ok';
  }
  function worse(a: Level, b: Level): Level {
    return ORDER[b] > ORDER[a] ? b : a;
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
    level: Level;
    sub: string | null;
  }
  interface LoadPill {
    perCpu: number;
    // unrated: the load of a container (load_rated false), shown grey without a rating.
    level: Level | 'unrated';
  }
  interface DiskBar {
    mount: string;
    pct: number;
    // ignored: a mount from ignore_mounts, shown grey without a rating.
    level: Level | 'ignored';
    sub: string | null;
  }

  function rings(check: MonitorCheck): Ring[] {
    const d = resourceDetails(check.state?.details);
    const cfg = (check.config ?? {}) as Record<string, unknown>;
    if (!d) return [];
    const out: Ring[] = [];
    if (d.cpu != null) {
      const pct = num(d.cpu);
      out.push({
        label: 'CPU',
        pct,
        level: rate(d, 'cpu', level(pct, num(cfg.cpu_warn, 80), num(cfg.cpu_crit, 95))),
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
        level: rate(d, 'memory', level(pct, num(cfg.memory_warn, 80), num(cfg.memory_crit, 95))),
        sub,
      });
    }
    // A host without a swap device sends swap_total_mb 0.
    if (d.swap != null && num(d.swap_total_mb) > 0) {
      const pct = num(d.swap);
      out.push({
        label: 'Swap',
        pct,
        level: rate(d, 'swap', level(pct, num(cfg.swap_warn, 80), num(cfg.swap_crit, 95))),
        sub: `${num(d.swap_used_mb)} / ${num(d.swap_total_mb)} MB`,
      });
    }
    return out;
  }
  function load(check: MonitorCheck): LoadPill | null {
    const d = resourceDetails(check.state?.details);
    const cfg = (check.config ?? {}) as Record<string, unknown>;
    if (d?.load_per_cpu == null) return null;
    const perCpu = num(d.load_per_cpu);
    if (d.load_rated === false) return { perCpu, level: 'unrated' };
    return {
      perCpu,
      level: rate(d, 'load', level(perCpu, num(cfg.load_warn, 1.5), num(cfg.load_crit, 3))),
    };
  }
  function disks(check: MonitorCheck): DiskBar[] {
    const d = resourceDetails(check.state?.details);
    const cfg = (check.config ?? {}) as Record<string, unknown>;
    if (!d) return [];
    const list = d.disks ?? [];
    return list.map((x) => {
      const pct = num(x.percent);
      const mount = String(x.mount ?? '?');
      const sub: string[] = [];
      if (x.ignored) sub.push($t('monitoring.live.ignored'));
      if (x.total_gb != null) {
        sub.push(`${num(x.used_gb).toFixed(1)} / ${num(x.total_gb).toFixed(1)} GB`);
      }
      if (x.free_gb != null) {
        sub.push($t('monitoring.live.free', { gb: num(x.free_gb).toFixed(1) }));
      }
      if (x.inodes_percent != null) sub.push(`Inodes ${num(x.inodes_percent).toFixed(0)}%`);
      // Full inodes stop writes like a full disk, so they raise the disk's bar.
      const usage = rate(
        d,
        `disk:${mount}`,
        level(pct, num(cfg.disk_warn, 85), num(cfg.disk_crit, 95)),
      );
      const inodes =
        x.inodes_percent == null
          ? 'ok'
          : rate(
              d,
              `inode:${mount}`,
              level(num(x.inodes_percent), num(cfg.inode_warn, 80), num(cfg.inode_crit, 90)),
            );
      return {
        mount,
        pct,
        level: x.ignored ? 'ignored' : worse(usage, inodes),
        sub: sub.length > 0 ? sub.join(' · ') : null,
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
      {@const rs = rings(check)}
      {@const ld = load(check)}
      {@const ds = disks(check)}
      <MonCheckLine {check}>
        {#snippet label()}
          <span class="mon-line-name">{check.name}</span>
        {/snippet}
        {#snippet value()}
          <span class="mon-live-summary">
            {#each rs as r (r.label)}
              <span class="mon-live-pill level-{r.level}">{r.label} {r.pct.toFixed(0)}%</span>
            {/each}
            {#if ld}
              <span
                class="mon-live-pill level-{ld.level}"
                title={ld.level === 'unrated' ? $t('monitoring.live.loadUnrated') : undefined}
                >Load {ld.perCpu.toFixed(2)}/CPU</span
              >
            {/if}
            {#if ds.length > 0}
              <span class="mon-live-pill">{ds.length} Disk{ds.length === 1 ? '' : 's'}</span>
            {/if}
          </span>
        {/snippet}
        {#snippet extraBody()}
          <div class="mon-live-detail">
            {#if rs.length > 0}
              <div class="mon-ring-row">
                {#each rs as r (r.label)}
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
            {#if ds.length > 0}
              <div class="mon-hero-bars">
                <!-- A report can list a mount twice; a duplicate key makes Svelte throw. -->
                {#each ds as d, i (`${i}:${d.mount}`)}
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

<style>
  .mon-hero-bar-fill.level-ignored {
    background: var(--text-faint);
  }
  .mon-live-pill.level-unrated {
    color: var(--text-muted);
  }
</style>
