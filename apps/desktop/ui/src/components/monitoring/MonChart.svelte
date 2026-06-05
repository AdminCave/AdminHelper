<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import uPlot, { type AlignedData, type Options } from 'uplot';
  import type { MonitoringMetricsResponse, MonitoringMetricSeries } from '$lib/api/types';
  import { checkTypeUnit, isPercentCheck, metricLabel } from '$lib/models/monitoring';
  import { tNow } from '$lib/i18n';

  interface Props {
    metrics: MonitoringMetricsResponse | null;
    checkType: string;
  }
  let { metrics, checkType }: Props = $props();

  let container: HTMLDivElement | null = $state(null);
  let chart: uPlot | null = null;
  let resizer: ResizeObserver | null = null;

  const COLORS = ['#38bdf8', '#22c55e', '#f97316', '#a855f7', '#ec4899', '#14b8a6'];

  function destroy(): void {
    if (chart) {
      chart.destroy();
      chart = null;
    }
    if (resizer) {
      resizer.disconnect();
      resizer = null;
    }
  }

  function render(el: HTMLDivElement, data: MonitoringMetricsResponse): void {
    destroy();
    el.innerHTML = '';

    const results: MonitoringMetricSeries[] = data?.data || [];
    if (results.length === 0) {
      el.innerHTML = `<div class="mon-chart-loading">${tNow('monitoring.chart.noData')}</div>`;
      return;
    }

    const filtered = results.filter((r) => !(r.metric?.__name__ || '').includes('status'));
    const series = filtered.length > 0 ? filtered : results;

    const timestamps = series[0].values.map((v) => Number(v[0]));
    const aligned: AlignedData = [timestamps];
    const uplotSeries: Options['series'] = [{}];

    for (let i = 0; i < series.length; i++) {
      const values = series[i].values.map((v) => {
        const n = parseFloat(v[1]);
        return Number.isNaN(n) ? null : n;
      });
      aligned.push(values);
      const metricName = series[i].metric?.__name__ || `Series ${i + 1}`;
      uplotSeries.push({
        label: metricLabel(metricName),
        stroke: COLORS[i % COLORS.length],
        width: 2,
        fill: ['service_process', 'proxmox_backup', 'docker_health'].includes(checkType)
          ? COLORS[i % COLORS.length] + '30'
          : undefined,
      });
    }

    const unit = checkTypeUnit(checkType);
    const pctCheck = isPercentCheck(checkType);
    const axisStyle = {
      stroke: '#94a3b8',
      grid: { stroke: 'rgba(148,163,184,0.12)' },
      ticks: { stroke: 'rgba(148,163,184,0.12)' },
    };

    const opts: Options = {
      width: el.offsetWidth || 600,
      height: 250,
      series: uplotSeries,
      axes: [
        axisStyle,
        {
          ...axisStyle,
          label: unit || undefined,
          ...(pctCheck ? { range: [0, 100] } : {}),
        },
      ],
      cursor: { drag: { x: false, y: false } },
      scales: {
        x: { time: true },
        ...(pctCheck ? { y: { min: 0, max: 100 } } : {}),
      },
    };

    const create = () => {
      opts.width = el.offsetWidth || 600;
      chart = new uPlot(opts, aligned, el);
    };
    if (el.offsetWidth > 0) create();
    else requestAnimationFrame(create);

    resizer = new ResizeObserver(() => {
      if (chart && el.offsetWidth > 0) chart.setSize({ width: el.offsetWidth, height: 250 });
    });
    resizer.observe(el);
  }

  $effect(() => {
    if (!container) return;
    if (!metrics) {
      container.innerHTML = `<div class="mon-chart-loading">${tNow('monitoring.chart.loading')}</div>`;
      return;
    }
    render(container, metrics);
  });

  onDestroy(destroy);
</script>

<div bind:this={container} class="mon-chart-container"></div>
