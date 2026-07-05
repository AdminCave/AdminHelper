<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errMsg } from '$lib/utils/errors';
  import { sessionStore } from '$lib/stores/session';
  import { monitoringApi } from '$lib/api/monitoring';
  import type { MonitorCheck, MonitoringMetricsResponse } from '$lib/api/types';
  import MonChart from '../MonChart.svelte';
  import MonCurrentValues from '../MonCurrentValues.svelte';
  import MonStatusTimeline from '../MonStatusTimeline.svelte';
  import { t } from '$lib/i18n';

  interface Props {
    check: MonitorCheck;
  }
  let { check }: Props = $props();

  const PERIODS = ['1h', '6h', '24h', '7d'] as const;
  let activePeriod = $state<(typeof PERIODS)[number]>('1h');
  let metrics = $state<MonitoringMetricsResponse | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);

  // Request generation: a fast period switch (1h -> 7d) can leave two fetches in flight, and the
  // slower one resolving last would otherwise overwrite the newer period's data — the `loading`
  // flag doesn't protect since the second request clears it before the first resolves (4.38).
  let loadGen = 0;

  async function load(): Promise<void> {
    const { session } = $sessionStore;
    if (!session) return;
    const gen = ++loadGen;
    loading = true;
    error = null;
    try {
      const res = await monitoringApi.fetchMetrics(session, check.id, activePeriod);
      if (gen !== loadGen) return;
      metrics = res;
    } catch (err) {
      if (gen !== loadGen) return;
      error = errMsg(err);
      metrics = null;
    } finally {
      if (gen === loadGen) loading = false;
    }
  }

  $effect(() => {
    // Register activePeriod as a synchronous dependency: load() can early-return
    // before reading it (no session), so this guarantees the effect re-runs when
    // the period changes regardless of that path.
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    activePeriod;
    void load();
  });

  function setPeriod(p: (typeof PERIODS)[number]): void {
    activePeriod = p;
  }
</script>

<div class="mon-expand-chart">
  <MonCurrentValues {metrics} checkType={check.checkType} />

  <div class="mon-segmented">
    {#each PERIODS as p (p)}
      <button class="mon-seg-btn" class:active={p === activePeriod} onclick={() => setPeriod(p)}>
        {p}
      </button>
    {/each}
  </div>

  {#if loading}
    <div class="mon-chart-loading">{$t('monitoring.detail.loading')}</div>
  {:else if error}
    <div class="mon-chart-loading">{$t('monitoring.detail.error')}</div>
  {:else}
    <MonChart {metrics} checkType={check.checkType} />
    <MonStatusTimeline statusHistory={metrics?.statusHistory} />
  {/if}
</div>
