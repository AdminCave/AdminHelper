<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';
  import { worstStatus } from '$lib/models/monitoring';
  import MonSectionHeader from './MonSectionHeader.svelte';
  import MonCheckLine from './MonCheckLine.svelte';
  import MonSparkline from '../MonSparkline.svelte';
  import { t } from '$lib/i18n';

  interface Props {
    checks: MonitorCheck[];
  }
  let { checks }: Props = $props();

  let worst = $derived(worstStatus(checks));

  function latencyOf(check: MonitorCheck): number | null {
    const msg = check.state?.message || '';
    const m = msg.match(/([\d.]+)\s*ms/i);
    return m ? parseFloat(m[1]) : null;
  }
  function targetOf(check: MonitorCheck): string {
    const cfg = (check.config ?? {}) as Record<string, unknown>;
    if (check.checkType === 'http') return String(cfg.url ?? '');
    if (check.checkType === 'tcp') return `${cfg.target ?? ''}:${cfg.port ?? ''}`;
    return String(cfg.target ?? '');
  }
</script>

<section class="mon-section">
  <MonSectionHeader
    icon="network"
    title={$t('monitoring.section.network')}
    {worst}
    count={checks.length}
  />

  <div class="mon-section-body">
    {#each checks as check (check.id)}
      {@const lat = latencyOf(check)}
      {@const tgt = targetOf(check)}
      <MonCheckLine {check} dense>
        {#snippet label()}
          <span class="mon-type-badge badge-{check.checkType}">{check.checkType.toUpperCase()}</span
          >
          <span class="mon-line-name">{check.name}</span>
          <span class="mon-line-target">{tgt}</span>
        {/snippet}
        {#snippet value()}
          <span class="mon-line-spark">
            <MonSparkline
              checkId={check.id}
              status={check.state?.status || 'pending'}
              width={96}
              height={24}
            />
          </span>
          <span class="mon-line-metric">
            {#if lat != null}
              <span class="mon-line-num">{lat.toFixed(lat < 10 ? 1 : 0)}</span>
              <span class="mon-line-unit">ms</span>
            {:else}
              <span class="mon-line-num mon-hero-dash">—</span>
            {/if}
          </span>
        {/snippet}
      </MonCheckLine>
    {/each}
  </div>
</section>
