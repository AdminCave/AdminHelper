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
  function disksOf(check: MonitorCheck): Array<Record<string, unknown>> {
    return ((check.state?.details as Record<string, unknown> | null)?.disks ?? []) as Array<
      Record<string, unknown>
    >;
  }
  function maxTempOf(check: MonitorCheck): number {
    let max = 0;
    for (const d of disksOf(check)) {
      const t = num(d.temp_c);
      if (t > max) max = t;
    }
    return max;
  }
  function tempLevel(temp: number, warn: number, crit: number): 'ok' | 'warn' | 'crit' {
    if (temp >= crit) return 'crit';
    if (temp >= warn) return 'warn';
    return 'ok';
  }
  function categoryClass(cat: string): 'ok' | 'warn' | 'crit' {
    if (cat === 'critical') return 'crit';
    if (cat === 'warning') return 'warn';
    return 'ok';
  }
  function smartSecondary(d: Record<string, unknown>): string {
    const hours = num(d.power_on_hours);
    const hoursStr = hours > 0 ? `${hours.toLocaleString('de-DE')} h` : null;
    if (d.kind === 'NVMe') {
      const parts: string[] = [];
      if (d.available_spare_pct != null) parts.push(`Spare ${d.available_spare_pct}%`);
      if (d.percentage_used != null) parts.push(`Wear ${d.percentage_used}%`);
      if (hoursStr) parts.push(hoursStr);
      return parts.join(' · ');
    }
    const parts: string[] = [];
    const realloc = num(d.reallocated_sectors);
    const pending = num(d.pending_sectors);
    if (realloc > 0) parts.push(`Realloc ${realloc}`);
    if (pending > 0) parts.push(`Pending ${pending}`);
    if (hoursStr) parts.push(hoursStr);
    return parts.join(' · ');
  }
</script>

<section class="mon-section">
  <MonSectionHeader
    icon="smart"
    title={$t('monitoring.section.smart')}
    {worst}
    count={checks.length}
  />

  <div class="mon-section-body">
    {#each checks as check (check.id)}
      {@const disks = disksOf(check)}
      {@const maxT = maxTempOf(check)}
      <MonCheckLine {check} showChart={false}>
        {#snippet label()}
          <span class="mon-line-name">{check.name}</span>
        {/snippet}
        {#snippet value()}
          {#if disks.length === 0}
            <span class="mon-line-pill">—</span>
          {:else}
            <span class="mon-line-metric">
              <span class="mon-line-num">{maxT}</span>
              <span class="mon-line-unit">°C max</span>
            </span>
            <span class="mon-line-pill">{disks.length} Disk{disks.length === 1 ? '' : 's'}</span>
          {/if}
        {/snippet}
        {#snippet extraBody()}
          <div class="mon-hero-bars">
            {#each disks as d (d.device)}
              {@const temp = num(d.temp_c)}
              {@const warn = num(d.temp_warn) || 60}
              {@const crit = num(d.temp_crit) || 70}
              {@const lvl = tempLevel(temp, warn, crit)}
              {@const cat = categoryClass(String(d.category ?? 'ok'))}
              {@const cwBits = Array.isArray(d.critical_warning_bits)
                ? (d.critical_warning_bits as string[])
                : []}
              {@const secondary = smartSecondary(d)}
              <div class="mon-hero-bar-row">
                <span class="mon-hero-bar-label"
                  >{d.device}
                  <span class="mon-expand-muted">[{d.kind || d.protocol || 'Disk'}]</span></span
                >
                <div class="mon-hero-bar">
                  <div
                    class="mon-hero-bar-fill level-{lvl}"
                    style="width:{Math.min((temp / crit) * 100, 100)}%"
                  ></div>
                </div>
                <span class="mon-hero-bar-pct">{temp}°C</span>
                <span class="mon-chip chip-{cat}"
                  >{cat === 'crit' ? 'CRIT' : cat === 'warn' ? 'WARN' : 'OK'}</span
                >
                {#if d.model}<span class="mon-hero-bar-sub">{d.model}</span>{/if}
                {#if secondary}<span class="mon-hero-bar-sub">{secondary}</span>{/if}
                {#if cwBits.length > 0}<span class="mon-hero-bar-sub mon-sub-crit"
                    >{cwBits.join(', ')}</span
                  >{/if}
              </div>
            {/each}
          </div>
        {/snippet}
      </MonCheckLine>
    {/each}
  </div>
</section>
