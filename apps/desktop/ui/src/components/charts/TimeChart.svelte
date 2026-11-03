<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import {
    formatAxis,
    formatTick,
    formatTip,
    formatValue,
    indexOfTime,
    niceMax,
    type ChartBand,
    type ChartEvent,
    type ChartSeries,
    type ChartThreshold,
    type ChartUnit,
  } from '$lib/charts';
  import { currentLocale, t } from '$lib/i18n';

  interface Props {
    series: ChartSeries[];
    /** Unix seconds of every grid index; forecast points continue the grid. */
    times: number[];
    unit?: ChartUnit;
    yMax?: number;
    thresholds?: ChartThreshold[];
    events?: ChartEvent[];
    bands?: ChartBand[];
    height?: number;
    /** Zero in the middle, `neg` series below it. */
    mirror?: boolean;
    /** The visible index range, null for all. */
    zoom?: [number, number] | null;
    onZoom?: (range: [number, number] | null) => void;
    /** The last measured index; the rest of the grid is the forecast. */
    nowIndex?: number | null;
    label: string;
  }
  let {
    series,
    times,
    unit = '%',
    yMax,
    thresholds = [],
    events = [],
    bands = [],
    height = 230,
    mirror = false,
    zoom = null,
    onZoom,
    nowIndex = null,
    label,
  }: Props = $props();

  const PAD_L = 46;
  const PAD_R = 16;
  const PAD_T = 16;
  const PAD_B = 28;
  const MIN_ZOOM = 3;
  // Unique per instance: several charts share one document, and an SVG clipPath id is global.
  const clipId = `tc-clip-${Math.random().toString(36).slice(2, 10)}`;

  let host: HTMLDivElement | null = $state(null);
  let measured = $state(0);
  let hover = $state<number | null>(null);
  let drag = $state<{ a: number; b: number } | null>(null);
  let resizer: ResizeObserver | null = null;

  onMount(() => {
    if (!host) return;
    measured = Math.floor(host.clientWidth);
    if (typeof ResizeObserver === 'undefined') return;
    resizer = new ResizeObserver(() => {
      if (host) measured = Math.floor(host.clientWidth);
    });
    resizer.observe(host);
  });
  onDestroy(() => resizer?.disconnect());

  const n = $derived(Math.max(times.length, ...series.map((s) => s.data.length), 1));
  const z0 = $derived(zoom ? zoom[0] : 0);
  const z1 = $derived(zoom ? zoom[1] : n - 1);
  // jsdom and a hidden tab measure 0; draw at a usable width instead of collapsing.
  const width = $derived(Math.max(240, measured > 0 ? measured : 800));
  const innerW = $derived(width - PAD_L - PAD_R);
  const innerH = $derived(height - PAD_T - PAD_B);
  const visible = $derived(series.filter((s) => !s.hidden));

  const max = $derived.by(() => {
    if (yMax != null) return yMax;
    let m = 0;
    for (const s of visible) {
      s.data.forEach((v, i) => {
        if (v != null && i >= z0 && i <= z1) m = Math.max(m, v);
      });
      for (const v of s.prev ?? []) if (v != null) m = Math.max(m, v);
    }
    for (const th of thresholds) m = Math.max(m, th.value);
    return niceMax(m * 1.12);
  });

  function x(i: number): number {
    return PAD_L + ((i - z0) / Math.max(1, z1 - z0)) * innerW;
  }
  function y(v: number): number {
    if (mirror) return PAD_T + innerH / 2 - (v / max) * (innerH / 2);
    return PAD_T + innerH - (Math.min(v, max) / max) * innerH;
  }

  function linePath(data: (number | null)[], neg = false): string {
    let d = '';
    let pen = false;
    for (let i = Math.max(0, Math.floor(z0)); i <= Math.min(n - 1, Math.ceil(z1)); i += 1) {
      const v = data[i];
      if (v == null) {
        pen = false;
        continue;
      }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)} ${y(neg ? -v : v).toFixed(1)}`;
      pen = true;
    }
    return d;
  }

  function areaPath(data: (number | null)[], neg = false): string {
    const idx: number[] = [];
    for (let i = Math.max(0, Math.floor(z0)); i <= Math.min(n - 1, Math.ceil(z1)); i += 1) {
      if (data[i] != null) idx.push(i);
    }
    if (idx.length < 2) return '';
    const base = y(0).toFixed(1);
    return `${linePath(data, neg)}L${x(idx[idx.length - 1]).toFixed(1)} ${base}L${x(idx[0]).toFixed(1)} ${base}Z`;
  }

  function statusColor(status: string): string {
    if (status === 'critical') return 'var(--danger)';
    if (status === 'warning') return 'var(--warning)';
    if (status === 'ok') return 'var(--success)';
    return 'var(--text-muted)';
  }

  function timeAt(i: number): number {
    if (times.length >= 2) return times[0] + i * (times[1] - times[0]);
    return times[0] ?? 0;
  }

  const yTicks = $derived(
    mirror ? [-max, -max / 2, 0, max / 2, max] : [0, max / 4, max / 2, (3 * max) / 4, max],
  );
  const xTicks = $derived(
    Array.from({ length: 6 }, (_, k) => Math.round(z0 + (k * (z1 - z0)) / 5)),
  );
  const span = $derived(timeAt(z1) - timeAt(z0));
  const eventMarks = $derived(
    events
      .map((e) => ({ ...e, i: indexOfTime(times, e.at) }))
      .filter((e) => e.i >= z0 && e.i <= z1),
  );
  const bandMarks = $derived(
    bands
      .map((b) => ({
        label: b.label,
        i0: Math.max(z0, indexOfTime(times, b.start)),
        i1: Math.min(z1, indexOfTime(times, b.end)),
      }))
      .filter((b) => b.i1 > b.i0),
  );
  const showNow = $derived(
    nowIndex != null && nowIndex < n - 1 && nowIndex >= z0 && nowIndex <= z1,
  );

  const tip = $derived(hover != null && drag == null ? hover : null);
  const nearEvents = $derived(
    tip == null ? [] : eventMarks.filter((e) => Math.abs(e.i - tip) <= Math.max(1, (z1 - z0) / 60)),
  );
  const tipFlip = $derived(tip != null && x(tip) > PAD_L + innerW * 0.62);

  function indexAt(clientX: number): number {
    const left = host?.getBoundingClientRect().left ?? 0;
    const ratio = (clientX - left - PAD_L) / innerW;
    return Math.max(z0, Math.min(z1, Math.round(z0 + ratio * (z1 - z0))));
  }

  function onMove(e: MouseEvent): void {
    const i = indexAt(e.clientX);
    hover = i;
    if (drag) drag = { ...drag, b: i };
  }
  function onDown(e: MouseEvent): void {
    const i = indexAt(e.clientX);
    drag = { a: i, b: i };
  }
  function onUp(): void {
    if (drag && Math.abs(drag.b - drag.a) >= MIN_ZOOM) {
      onZoom?.([Math.min(drag.a, drag.b), Math.max(drag.a, drag.b)]);
    }
    drag = null;
  }
  function onLeave(): void {
    hover = null;
    drag = null;
  }
  function onKey(e: KeyboardEvent): void {
    const last = Math.min(z1, nowIndex ?? z1);
    const step = e.shiftKey ? 10 : 1;
    let next: number | null;
    if (e.key === 'ArrowLeft') next = Math.max(z0, (hover ?? last) - step);
    else if (e.key === 'ArrowRight') next = Math.min(z1, (hover ?? last) + step);
    else if (e.key === 'Home') next = z0;
    else if (e.key === 'End') next = last;
    else if (e.key === 'Escape') next = null;
    else return;
    e.preventDefault();
    hover = next;
  }
</script>

<!-- The chart is one focusable widget that the keyboard and the mouse drive; aria-query counts
     role="application" as non-interactive, so Svelte warns although focus and keys are the point. -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
  bind:this={host}
  class="time-chart"
  role="application"
  tabindex="0"
  aria-label={label}
  aria-roledescription="chart"
  aria-describedby="{clipId}-keys"
  onmousemove={onMove}
  onmousedown={onDown}
  onmouseup={onUp}
  onmouseleave={onLeave}
  ondblclick={() => onZoom?.(null)}
  onkeydown={onKey}
  onfocus={() => (hover = Math.min(z1, nowIndex ?? z1))}
  onblur={() => (hover = null)}
>
  <span id="{clipId}-keys" class="visually-hidden">{$t('monitoring.chart.keys')}</span>
  <svg {width} {height} aria-hidden="true">
    <defs>
      <clipPath id={clipId}>
        <rect x={PAD_L} y={PAD_T - 2} width={innerW} height={innerH + 4} />
      </clipPath>
    </defs>
    {#each yTicks as v, k (k)}
      <line
        x1={PAD_L}
        x2={PAD_L + innerW}
        y1={y(v)}
        y2={y(v)}
        class="grid"
        stroke-dasharray={v === 0 && mirror ? '' : '2 4'}
      />
      <text x={PAD_L - 8} y={y(v) + 3.5} text-anchor="end" class="axis">{formatAxis(v, unit)}</text>
    {/each}
    {#each xTicks as i, k (k)}
      <text
        x={x(i)}
        y={height - 8}
        text-anchor={k === 0 ? 'start' : k === 5 ? 'end' : 'middle'}
        class="axis">{formatTick(timeAt(i), span, currentLocale())}</text
      >
    {/each}
    <g clip-path="url(#{clipId})">
      {#each bandMarks as b, k (k)}
        <rect
          class="band"
          data-testid="chart-band"
          x={x(b.i0)}
          y={PAD_T}
          width={Math.max(2, x(b.i1) - x(b.i0))}
          height={innerH}
        />
        {#if x(b.i1) - x(b.i0) > 30}
          <text x={x(b.i0) + 4} y={PAD_T + 11} class="band-label">{b.label}</text>
        {/if}
      {/each}
      {#each thresholds as th, k (k)}
        <line
          data-testid="chart-threshold"
          x1={PAD_L}
          x2={PAD_L + innerW}
          y1={y(th.value)}
          y2={y(th.value)}
          stroke={statusColor(th.status)}
          stroke-opacity="0.7"
          stroke-dasharray="6 4"
        />
      {/each}
      {#if showNow && nowIndex != null}
        <rect
          class="forecast-area"
          x={x(nowIndex)}
          y={PAD_T}
          width={Math.max(0, PAD_L + innerW - x(nowIndex))}
          height={innerH}
        />
      {/if}
      {#each visible as s (s.key)}
        {#if s.prev}
          <path
            data-testid="chart-prev"
            d={linePath(s.prev, s.neg)}
            fill="none"
            stroke={s.color}
            stroke-opacity="0.4"
            stroke-width="1.25"
            stroke-dasharray="2 3"
          />
        {/if}
        {#if s.area}
          <path
            d={areaPath(s.data, s.neg)}
            style="fill: color-mix(in srgb, {s.color} 11%, transparent)"
          />
        {/if}
        <path
          data-testid="chart-line"
          data-series={s.key}
          d={linePath(s.data, s.neg)}
          fill="none"
          stroke={s.color}
          stroke-width={s.dash ? 1.5 : 1.8}
          stroke-dasharray={s.dash ?? ''}
          stroke-linejoin="round"
          stroke-linecap="round"
        />
      {/each}
      {#each eventMarks as e, k (k)}
        <g data-testid="chart-event">
          <line
            x1={x(e.i)}
            x2={x(e.i)}
            y1={PAD_T}
            y2={PAD_T + innerH}
            stroke={statusColor(e.status)}
            stroke-opacity="0.55"
            stroke-dasharray="3 3"
          />
          <circle cx={x(e.i)} cy={PAD_T + 3} r="4" fill={statusColor(e.status)} class="marker" />
        </g>
      {/each}
      {#if drag}
        <rect
          class="zoom-area"
          x={Math.min(x(drag.a), x(drag.b))}
          y={PAD_T}
          width={Math.abs(x(drag.b) - x(drag.a))}
          height={innerH}
        />
      {/if}
      {#if tip != null}
        <line x1={x(tip)} x2={x(tip)} y1={PAD_T} y2={PAD_T + innerH} class="crosshair" />
        {#each visible as s (s.key)}
          {@const v = s.data[tip]}
          {#if v != null}
            <circle cx={x(tip)} cy={y(s.neg ? -v : v)} r="3.5" fill={s.color} class="marker" />
          {/if}
        {/each}
      {/if}
    </g>
    {#if showNow && nowIndex != null}
      <line x1={x(nowIndex)} x2={x(nowIndex)} y1={PAD_T} y2={PAD_T + innerH} class="now" />
      <text x={x(nowIndex) + 5} y={PAD_T + 11} class="now-label">{$t('monitoring.chart.now')}</text>
    {/if}
    {#each thresholds as th, k (k)}
      {#if y(th.value) >= PAD_T}
        <text
          x={PAD_L + innerW - 2}
          y={y(th.value) - 4}
          text-anchor="end"
          class="threshold-label"
          fill={statusColor(th.status)}>{th.label}</text
        >
      {/if}
    {/each}
  </svg>
  {#if tip != null}
    <div
      class="tip"
      class:flip={tipFlip}
      role="status"
      style="top: {PAD_T + 4}px; left: {tipFlip ? x(tip) - 12 : x(tip) + 12}px"
    >
      <div class="tip-time">
        {formatTip(timeAt(tip), currentLocale())}{nowIndex != null && tip > nowIndex
          ? ` · ${$t('monitoring.chart.forecast')}`
          : ''}
      </div>
      {#each visible as s (s.key)}
        {@const v = s.data[tip]}
        {#if v != null}
          <div class="tip-row" data-testid="chart-tip-row">
            <svg width="14" height="6" aria-hidden="true">
              <line
                x1="0"
                x2="14"
                y1="3"
                y2="3"
                stroke={s.color}
                stroke-width="2"
                stroke-dasharray={s.dash ?? ''}
              />
            </svg>
            <span class="tip-label">{s.label}</span>
            <span class="tip-value">{formatValue(v, unit)}</span>
            {#if s.prev && s.prev[tip] != null}
              <span class="tip-prev"
                >{$t('monitoring.chart.previous', { value: formatValue(s.prev[tip], unit) })}</span
              >
            {/if}
          </div>
        {/if}
      {/each}
      {#each nearEvents as e, k (k)}
        <div class="tip-event">
          <span class="dot" style="background: {statusColor(e.status)}"></span>{formatTip(
            e.at,
            currentLocale(),
          )} · {e.label}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .time-chart {
    position: relative;
    width: 100%;
    user-select: none;
    cursor: crosshair;
    border-radius: var(--radius-md);
  }
  .time-chart:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  svg {
    display: block;
    overflow: visible;
  }
  .grid {
    stroke: var(--border);
  }
  .axis {
    font-family: var(--font-mono);
    font-size: 10px;
    fill: var(--text-subtle);
  }
  .band {
    fill: color-mix(in srgb, var(--text-strong) 6%, transparent);
  }
  .band-label {
    font-family: var(--font-mono);
    font-size: 9px;
    fill: var(--text-subtle);
  }
  .forecast-area {
    fill: color-mix(in srgb, var(--accent) 5%, transparent);
  }
  .zoom-area {
    fill: color-mix(in srgb, var(--accent) 14%, transparent);
    stroke: var(--accent);
    stroke-opacity: 0.6;
  }
  .crosshair {
    stroke: var(--text-muted);
    stroke-width: 1;
  }
  .marker {
    stroke: var(--surface);
    stroke-width: 2;
  }
  .now {
    stroke: var(--accent);
    stroke-opacity: 0.8;
  }
  .now-label {
    font-family: var(--font-mono);
    font-size: 9.5px;
    fill: var(--accent);
  }
  .threshold-label {
    font-family: var(--font-mono);
    font-size: 9.5px;
  }
  .tip {
    position: absolute;
    min-width: 180px;
    padding: 9px 11px;
    background: var(--surface-raised);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-pop);
    pointer-events: none;
    z-index: 5;
  }
  .tip.flip {
    transform: translateX(-100%);
  }
  .tip-time {
    font-family: var(--font-mono);
    font-size: 10.5px;
    color: var(--text-subtle);
    margin-bottom: 6px;
    white-space: nowrap;
  }
  .tip-row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    padding: 2px 0;
    white-space: nowrap;
  }
  .tip-label {
    flex: 1;
    color: var(--text-muted);
  }
  .tip-value {
    font-family: var(--font-mono);
    font-weight: 600;
    color: var(--text-strong);
  }
  .tip-prev {
    font-family: var(--font-mono);
    font-size: 10.5px;
    color: var(--text-subtle);
  }
  .tip-event {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-top: 6px;
    padding-top: 6px;
    border-top: 1px solid var(--border);
    font-size: 11.5px;
    color: var(--text);
    white-space: nowrap;
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
  }
  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
</style>
