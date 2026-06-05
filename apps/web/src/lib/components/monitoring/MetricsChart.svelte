<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import uPlot from 'uplot';
  import { t } from '$lib/i18n';
  import { CHART_COLORS, checkTypeUnit } from '$lib/utils/monitoring';
  import type { MonitorCheckType, MonitoringMetricsResponse } from '$lib/api/types';

  interface Props {
    data: MonitoringMetricsResponse | null;
    checkType: MonitorCheckType;
    loading?: boolean;
    error?: string | null;
  }

  let { data, checkType, loading = false, error = null }: Props = $props();

  let container: HTMLDivElement | undefined = $state();
  let chart: uPlot | null = null;

  function destroy() {
    if (chart) {
      chart.destroy();
      chart = null;
    }
  }

  function render() {
    destroy();
    if (!container) return;
    container.innerHTML = '';
    if (!data) return;

    const allSeries = data.data ?? [];
    if (allSeries.length === 0) return;

    const tempSeries = allSeries.filter((s) => (s.metric?.__name__ ?? '').includes('agent_temp'));
    const otherSeries = allSeries.filter((s) => !(s.metric?.__name__ ?? '').includes('agent_temp'));
    const series = otherSeries.length > 0 ? otherSeries : tempSeries;
    const chartIsTemp = otherSeries.length === 0 && tempSeries.length > 0;
    if (series.length === 0) return;

    const timestamps = series[0].values.map((v) => v[0]);
    const uData: uPlot.AlignedData = [timestamps];
    const uSeries: uPlot.Series[] = [{}];

    series.forEach((s, i) => {
      const name = (s.metric?.__name__ ?? `Serie ${i + 1}`)
        .replace(/^monitor_/, '')
        .replace(/_value$/, '')
        .replace(/_/g, ' ');
      uData.push(s.values.map((v) => parseFloat(v[1])));
      const isCount = ['service_process', 'proxmox_backup', 'docker_health'].includes(checkType);
      uSeries.push({
        label: name,
        stroke: CHART_COLORS[i % CHART_COLORS.length],
        width: 2,
        fill: isCount ? CHART_COLORS[i % CHART_COLORS.length] + '20' : undefined,
      });
    });

    const unit = chartIsTemp ? ' \u00b0C' : checkTypeUnit(checkType);
    const isPercent =
      !chartIsTemp && (checkType === 'agent_resources' || checkType === 'zfs_health');

    const opts: uPlot.Options = {
      width: container.clientWidth || 600,
      height: 200,
      series: uSeries,
      axes: [{}, { label: unit, ...(isPercent ? { range: [0, 100] } : {}) }],
      cursor: { show: true },
      legend: { show: series.length > 1 },
    };

    try {
      chart = new uPlot(opts, uData, container);
    } catch {
      // If rendering fails, leave the error fallback to the markup.
    }
  }

  $effect(() => {
    // Re-render on data or container change
    void data;
    render();
  });

  onDestroy(destroy);
</script>

{#if loading}
  <span style="color:var(--text-muted)">{$t('monitor.loadingMetrics')}</span>
{:else if error}
  <span style="color:var(--red)">Fehler: {error}</span>
{:else if !data || (data.data ?? []).length === 0}
  <span style="color:var(--text-muted)">{$t('monitor.noMetrics')}</span>
{:else}
  <div bind:this={container} class="check-detail-chart-inner"></div>
{/if}
