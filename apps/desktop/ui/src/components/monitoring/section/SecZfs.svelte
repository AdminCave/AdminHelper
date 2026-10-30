<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';
  import { zfsDetails } from '$lib/models/checkDetails';
  import { worstStatus } from '$lib/models/monitoring';
  import MonSectionHeader from './MonSectionHeader.svelte';
  import MonCheckLine from './MonCheckLine.svelte';
  import { t } from '$lib/i18n';

  interface Props {
    checks: MonitorCheck[];
  }
  let { checks }: Props = $props();

  let worst = $derived(worstStatus(checks));

  // Spelled out: the i18n "no unused keys" guard only sees quoted keys.
  const ERROR_KEY = new Map<string, string>([
    ['timeout', 'monitoring.zfs.error.timeout'],
    ['cli_failed', 'monitoring.zfs.error.cli_failed'],
  ]);
  // The colour comes from the status the line's dot shows: an outage is a
  // warning, and with the outage alert off (unknown) the pill stays grey.
  const OUTAGE_PILL = new Map<string, string>([
    ['critical', 'pill-crit'],
    ['warning', 'pill-warn'],
  ]);

  function poolsOf(check: MonitorCheck) {
    return zfsDetails(check.state?.details)?.pools ?? [];
  }
  // The error's text key when the agent could not read zpool; no pools then.
  function unavailableOf(check: MonitorCheck): string | null {
    const d = zfsDetails(check.state?.details);
    if (d?.available !== false) return null;
    // A code this UI does not know yet (a newer agent) still says something.
    return ERROR_KEY.get(d.error ?? '') ?? 'monitoring.zfs.error.unknown';
  }
  function cfgOf(check: MonitorCheck): Record<string, unknown> {
    return (check.config ?? {}) as Record<string, unknown>;
  }
  function levelOf(pct: number, warn: number, crit: number): 'ok' | 'warn' | 'crit' {
    if (pct >= crit) return 'crit';
    if (pct >= warn) return 'warn';
    return 'ok';
  }
  function healthClass(h: string): 'ok' | 'warn' | 'crit' {
    if (h === 'ONLINE') return 'ok';
    if (h === 'DEGRADED') return 'warn';
    return 'crit';
  }
</script>

<section class="mon-section">
  <MonSectionHeader
    icon="storage"
    title={$t('monitoring.section.storage')}
    {worst}
    count={checks.length}
  />

  <div class="mon-section-body">
    {#each checks as check (check.id)}
      {@const pools = poolsOf(check)}
      {@const unavailable = unavailableOf(check)}
      {@const cfg = cfgOf(check)}
      {@const capWarn = Number(cfg.capacity_warn ?? 80)}
      {@const capCrit = Number(cfg.capacity_crit ?? 90)}
      <MonCheckLine {check} showChart={false}>
        {#snippet label()}
          <span class="mon-line-name">{check.name}</span>
        {/snippet}
        {#snippet value()}
          {#if unavailable}
            <span
              class="mon-line-pill {OUTAGE_PILL.get(check.state?.status ?? '') ?? ''}"
              title={check.state?.message}>{$t(unavailable)}</span
            >
          {:else if pools.length === 0}
            <span class="mon-line-pill">—</span>
          {:else}
            {#each pools as p (p.name)}
              {@const lvl = levelOf(p.capacityPercent, capWarn, capCrit)}
              {@const h = healthClass(p.health)}
              {@const worstPill =
                h === 'crit'
                  ? 'crit'
                  : lvl === 'crit'
                    ? 'crit'
                    : h === 'warn' || lvl === 'warn'
                      ? 'warn'
                      : 'ok'}
              <span class="mon-line-pill pill-{worstPill}">{p.name} {p.capacityPercent}%</span>
            {/each}
          {/if}
        {/snippet}
        {#snippet extraBody()}
          <div class="mon-hero-bars">
            {#each pools as p (p.name)}
              {@const lvl = levelOf(p.capacityPercent, capWarn, capCrit)}
              {@const h = healthClass(p.health)}
              <div class="mon-hero-bar-row">
                <span class="mon-hero-bar-label">{p.name}</span>
                <div class="mon-hero-bar">
                  <div
                    class="mon-hero-bar-fill level-{lvl}"
                    style="width:{Math.min(p.capacityPercent, 100)}%"
                  ></div>
                </div>
                <span class="mon-hero-bar-pct">{p.capacityPercent}%</span>
                <span class="mon-chip chip-{h}">{p.health}</span>
              </div>
            {/each}
          </div>
        {/snippet}
      </MonCheckLine>
    {/each}
  </div>
</section>
