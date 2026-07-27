<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitorCheck, MonitorForecastDetails } from '$lib/api/types';
  import { worstStatus } from '$lib/models/monitoring';
  import MonSectionHeader from './MonSectionHeader.svelte';
  import MonCheckLine from './MonCheckLine.svelte';
  import { t } from '$lib/i18n';

  interface Props {
    checks: MonitorCheck[];
  }
  let { checks }: Props = $props();

  let worst = $derived(worstStatus(checks));

  function mountsOf(check: MonitorCheck) {
    return (check.state?.details as MonitorForecastDetails | undefined)?.mounts ?? [];
  }
  function cfgOf(check: MonitorCheck): Record<string, unknown> {
    return (check.config ?? {}) as Record<string, unknown>;
  }
  function levelOf(hoursLeft: number, warn: number, crit: number): 'ok' | 'warn' | 'crit' {
    if (hoursLeft <= crit) return 'crit';
    if (hoursLeft <= warn) return 'warn';
    return 'ok';
  }
</script>

<section class="mon-section">
  <MonSectionHeader
    icon="storage"
    title={$t('monitoring.section.forecast')}
    {worst}
    count={checks.length}
  />

  <div class="mon-section-body">
    {#each checks as check (check.id)}
      {@const mounts = mountsOf(check)}
      {@const cfg = cfgOf(check)}
      {@const warnH = Number(cfg.warn_hours ?? 24)}
      {@const critH = Number(cfg.crit_hours ?? 8)}
      <MonCheckLine {check} showChart={false}>
        {#snippet label()}
          <span class="mon-line-name">{check.name}</span>
        {/snippet}
        {#snippet value()}
          {#if mounts.length === 0}
            <span class="mon-line-pill">—</span>
          {:else}
            {#each mounts as m (m.mount)}
              {#if m.hours_left != null}
                {@const lvl = levelOf(m.hours_left, warnH, critH)}
                <span class="mon-line-pill pill-{lvl}">{m.mount} ~{Math.round(m.hours_left)}h</span>
              {:else if m.note}
                <span class="mon-line-pill">{m.mount} —</span>
              {:else}
                <span class="mon-line-pill pill-ok"
                  >{m.mount} {$t('monitoring.forecast.stable')}</span
                >
              {/if}
            {/each}
          {/if}
        {/snippet}
      </MonCheckLine>
    {/each}
  </div>
</section>
