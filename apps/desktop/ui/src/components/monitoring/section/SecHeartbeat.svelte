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

  function secondsOf(check: MonitorCheck): number | null {
    const msg = check.state?.message || '';
    const m = msg.match(/(\d+)/);
    return m ? parseInt(m[1], 10) : null;
  }

  function display(secs: number | null): { value: string; unit: string } {
    if (secs == null) return { value: '—', unit: '' };
    if (secs < 60) return { value: String(secs), unit: 's' };
    if (secs < 3600) return { value: String(Math.round(secs / 60)), unit: 'min' };
    return { value: (secs / 3600).toFixed(1), unit: 'h' };
  }
</script>

<section class="mon-section">
  <MonSectionHeader
    icon="heartbeat"
    title={$t('monitoring.section.heartbeat')}
    {worst}
    count={checks.length}
  />

  <div class="mon-section-body">
    {#each checks as check (check.id)}
      {@const d = display(secondsOf(check))}
      <MonCheckLine {check} dense showChart={false}>
        {#snippet label()}
          <span class="mon-line-name">{check.name}</span>
          <span class="mon-line-sub">{$t('monitoring.agentPing.lastSeen')}</span>
        {/snippet}
        {#snippet value()}
          <span class="mon-line-metric">
            <span class="mon-line-num">{d.value}</span>
            <span class="mon-line-unit">{d.unit}</span>
          </span>
        {/snippet}
      </MonCheckLine>
    {/each}
  </div>
</section>
