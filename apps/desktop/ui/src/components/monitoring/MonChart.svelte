<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import uPlot, { type Options } from 'uplot';
  import type { MonitoringMetricsResponse, MonitoringMetricSeries } from '$lib/api/types';
  import {
    buildAlignedData,
    checkTypeUnit,
    isPercentCheck,
    metricSeriesLabel,
  } from '$lib/models/monitoring';
  import { tNow } from '$lib/i18n';

  interface Props {
    metrics: MonitoringMetricsResponse | null;
    checkType: string;
  }
  let { metrics, checkType }: Props = $props();

  let container: HTMLDivElement | null = $state(null);
  let chart: uPlot | null = null;
  let resizer: ResizeObserver | null = null;
  // Tracked so a pending "create once the container has width" rAF can be cancelled on destroy or
  // the next render — else the stale rAF fires later, builds a uPlot into the detached/emptied
  // container and overwrites `chart`, leaking the previous instance's DOM + listeners (4.103).
  let raf = 0;
  // Bumped when <html data-theme> changes so the render $effect re-themes the uPlot canvas
  // (axis/grid stroke are baked into the chart at build time, unlike the CSS-var timeline).
  let themeVersion = $state(0);

  // Series palette: mid-saturation (no neon/pastel), each hue stays legible on both the
  // True-Black dark and pure-white light background.
  const COLORS = ['#38bdf8', '#22c55e', '#f97316', '#a855f7', '#ec4899', '#14b8a6'];

  function destroy(): void {
    if (raf) {
      cancelAnimationFrame(raf);
      raf = 0;
    }
    if (chart) {
      chart.destroy();
      chart = null;
    }
    if (resizer) {
      resizer.disconnect();
      resizer = null;
    }
  }

  // DOM API, not innerHTML: tNow supports {placeholder} interpolation, so an HTML
  // string here would become an XSS sink the moment a key carries server data (3.65).
  function showPlaceholder(el: HTMLElement, key: string): void {
    const div = document.createElement('div');
    div.className = 'mon-chart-loading';
    div.textContent = tNow(key);
    el.replaceChildren(div);
  }

  function render(el: HTMLDivElement, data: MonitoringMetricsResponse): void {
    destroy();
    el.replaceChildren();

    const results: MonitoringMetricSeries[] = data?.data || [];
    if (results.length === 0) {
      showPlaceholder(el, 'monitoring.chart.noData');
      return;
    }

    const filtered = results.filter((r) => !(r.metric?.__name__ || '').includes('status'));
    const series = filtered.length > 0 ? filtered : results;

    // Join series on the union of their timestamps so a series with fewer/shifted points isn't
    // mapped to the wrong x-values or truncated (4.102, see buildAlignedData).
    const aligned = buildAlignedData(series);
    const uplotSeries: Options['series'] = [{}];

    for (let i = 0; i < series.length; i++) {
      uplotSeries.push({
        label: metricSeriesLabel(series[i].metric) || `Series ${i + 1}`,
        stroke: COLORS[i % COLORS.length],
        width: 2,
        fill: ['service_process', 'proxmox_backup', 'docker_health'].includes(checkType)
          ? COLORS[i % COLORS.length] + '30'
          : undefined,
      });
    }

    const unit = checkTypeUnit(checkType);
    const pctCheck = isPercentCheck(checkType);
    // Axis/grid colours from the theme tokens (read live so a data-theme toggle re-themes
    // the canvas on the next render); fall back to the old slate values if unresolved.
    const cs = getComputedStyle(document.documentElement);
    const axisStroke = cs.getPropertyValue('--text-muted').trim() || '#94a3b8';
    const gridStroke = cs.getPropertyValue('--border').trim() || 'rgba(148,163,184,0.12)';
    const axisStyle = {
      stroke: axisStroke,
      grid: { stroke: gridStroke },
      ticks: { stroke: gridStroke },
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
    else
      raf = requestAnimationFrame(() => {
        raf = 0;
        create();
      });

    resizer = new ResizeObserver(() => {
      if (chart && el.offsetWidth > 0) chart.setSize({ width: el.offsetWidth, height: 250 });
    });
    resizer.observe(el);
  }

  // Re-render on theme toggle: uPlot bakes axis/grid colours into the canvas at build
  // time, so the chart must be rebuilt when <html data-theme> flips.
  $effect(() => {
    const obs = new MutationObserver(() => themeVersion++);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => obs.disconnect();
  });

  $effect(() => {
    // Track checkType too: render() reads it (fill/unit/scale) but only `metrics`
    // would otherwise be a dependency, so a pure checkType change must re-render.
    void checkType;
    void themeVersion;
    if (!container) return;
    if (!metrics) {
      showPlaceholder(container, 'monitoring.chart.loading');
      return;
    }
    render(container, metrics);
  });

  onDestroy(destroy);
</script>

<div bind:this={container} class="mon-chart-container"></div>
