<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
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

  async function load(): Promise<void> {
    const { session } = $sessionStore;
    if (!session) return;
    loading = true;
    error = null;
    try {
      metrics = await monitoringApi.fetchMetrics(session, check.id, activePeriod);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      metrics = null;
    } finally {
      loading = false;
    }
  }

  $effect(() => {
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
    {#each PERIODS as p}
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
