<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errMsg } from '$lib/utils/errors';
  import { sessionStore } from '$lib/stores/session';
  import { monitoringServers } from '$lib/stores/monitoring';
  import { monitoringApi } from '$lib/api/monitoring';
  import type { ServerCompare } from '$lib/api/types';
  import { formatValue, stats, type ChartSeries, type ChartUnit, type Value } from '$lib/charts';
  import TimeChart from '../charts/TimeChart.svelte';
  import { t } from '$lib/i18n';

  const METRICS = ['cpu', 'ram', 'disk', 'load'] as const;
  type Metric = (typeof METRICS)[number];
  const PERIODS = ['1h', '24h', '7d', '30d'] as const;
  type Period = (typeof PERIODS)[number];
  const COLORS = ['#38bdf8', '#22c55e', '#f97316', '#a855f7'];
  const MAX_SELECTED = 4;
  const SPARK_W = 80;
  const SPARK_H = 20;

  let metric = $state<Metric>('cpu');
  let period = $state<Period>('24h');
  let data = $state<ServerCompare | null>(null);
  let error = $state<string | null>(null);
  let loading = $state(false);
  /** Chosen server ids, oldest first. */
  let selected = $state<string[]>([]);
  let zoom = $state<[number, number] | null>(null);
  let picked = false;
  let loadGen = 0;

  async function load(m: Metric, p: Period): Promise<void> {
    const { session } = $sessionStore;
    if (!session) return;
    const gen = ++loadGen;
    data = null;
    loading = true;
    error = null;
    try {
      const res = await monitoringApi.fetchServerCompare(session, m, p);
      if (gen !== loadGen) return;
      data = res;
    } catch (err) {
      if (gen !== loadGen) return;
      error = errMsg(err);
    } finally {
      if (gen === loadGen) loading = false;
    }
  }

  $effect(() => {
    const m = metric;
    const p = period;
    zoom = null;
    void load(m, p);
  });

  function nameOf(id: string): string {
    const srv = $monitoringServers.find((s) => s.id === id);
    return srv ? srv.name || srv.hostname || id : id;
  }

  const unit = $derived<ChartUnit>(metric === 'load' ? '' : '%');
  const gridLength = $derived(data ? Math.floor((data.end - data.start) / data.step) + 1 : 0);
  const times = $derived(
    Array.from({ length: gridLength }, (_, i) => (data?.start ?? 0) + i * (data?.step ?? 0)),
  );
  const servers = $derived(
    (data?.servers ?? []).map((s) => ({
      id: s.serverId,
      name: nameOf(s.serverId),
      values: s.points.map((p) => p[1]) as Value[],
    })),
  );

  // The first answer picks the busiest servers, so the chart does not start empty; after
  // that the selection is the user's, even when it is empty.
  $effect(() => {
    if (!picked && ranking.length > 0) {
      picked = true;
      selected = ranking.slice(0, MAX_SELECTED).map((r) => r.id);
    }
  });

  const z0 = $derived(zoom ? zoom[0] : 0);
  const z1 = $derived(zoom ? zoom[1] : Math.max(0, gridLength - 1));
  const ranking = $derived(
    servers
      .map((s) => ({ ...s, stats: stats(s.values, z0, z1) }))
      .filter((s) => s.stats != null)
      .sort((a, b) => (b.stats?.avg ?? 0) - (a.stats?.avg ?? 0) || a.name.localeCompare(b.name)),
  );
  const barMax = $derived(
    unit === '%' ? 100 : Math.max(1e-9, ...ranking.map((r) => r.stats?.avg ?? 0)),
  );

  const chartSeries = $derived.by((): ChartSeries[] =>
    selected
      .map((id) => servers.find((s) => s.id === id))
      .filter((s) => s != null)
      .map((s, i) => ({ key: s.id, label: s.name, color: COLORS[i], data: s.values })),
  );

  function toggle(id: string): void {
    if (selected.includes(id)) {
      selected = selected.filter((x) => x !== id);
    } else {
      const next = [...selected, id];
      selected = next.length > MAX_SELECTED ? next.slice(next.length - MAX_SELECTED) : next;
    }
  }

  function colorOf(id: string): string | null {
    const i = chartSeries.findIndex((s) => s.key === id);
    return i < 0 ? null : chartSeries[i].color;
  }

  function sparkPath(values: Value[]): string {
    const max = unit === '%' ? 100 : Math.max(1e-9, ...values.filter((v) => v != null));
    const n = Math.max(1, values.length - 1);
    let d = '';
    let pen = false;
    values.forEach((v, i) => {
      if (v == null) {
        pen = false;
        return;
      }
      const x = (i / n) * SPARK_W;
      const y = SPARK_H - (Math.min(v, max) / max) * SPARK_H;
      d += `${pen ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
      pen = true;
    });
    return d;
  }
</script>

<section class="mon-section compare-view" aria-label={$t('monitoring.compare.title')}>
  <header class="compare-head">
    <h3 class="compare-title">{$t('monitoring.compare.title')}</h3>
    <div class="mon-segmented" role="group" aria-label={$t('monitoring.compare.metric')}>
      {#each METRICS as m (m)}
        <button
          class="mon-seg-btn"
          class:active={metric === m}
          aria-pressed={metric === m}
          onclick={() => (metric = m)}>{$t(`monitoring.compare.metric.${m}`)}</button
        >
      {/each}
    </div>
    <div class="mon-segmented" role="group" aria-label={$t('monitoring.history.period')}>
      {#each PERIODS as p (p)}
        <button
          class="mon-seg-btn"
          class:active={period === p}
          aria-pressed={period === p}
          onclick={() => (period = p)}>{$t(`monitoring.history.period.${p}`)}</button
        >
      {/each}
    </div>
  </header>

  {#if error}
    <div class="compare-message" role="alert">{$t('monitoring.compare.error', { error })}</div>
  {:else if !data}
    <div class="compare-message">{loading ? $t('monitoring.chart.loading') : ''}</div>
  {:else if ranking.length === 0}
    <div class="compare-message">{$t('monitoring.compare.empty')}</div>
  {:else}
    <TimeChart
      series={chartSeries}
      {times}
      {unit}
      yMax={unit === '%' ? 100 : undefined}
      {zoom}
      onZoom={(range) => (zoom = range)}
      label={$t('monitoring.compare.chartLabel', {
        metric: $t(`monitoring.compare.metric.${metric}`),
      })}
    />
    {#if zoom}
      <div class="compare-tools">
        <button class="btn small" onclick={() => (zoom = null)}>
          {$t('monitoring.history.resetZoom')}
        </button>
      </div>
    {/if}
    <p class="compare-hint">{$t('monitoring.compare.hint')}</p>
    <table class="compare-ranking" aria-label={$t('monitoring.compare.ranking')}>
      <thead>
        <tr>
          <th></th>
          <th scope="col">{$t('monitoring.history.stat.series')}</th>
          <th></th>
          <th></th>
          <th scope="col">{$t('monitoring.history.stat.avg')}</th>
          <th scope="col">{$t('monitoring.history.stat.max')}</th>
        </tr>
      </thead>
      <tbody>
        {#each ranking as r (r.id)}
          {@const color = colorOf(r.id)}
          <tr class:chosen={color != null} data-testid="compare-row" data-server={r.id}>
            <td>
              <input
                type="checkbox"
                checked={color != null}
                aria-label={$t('monitoring.compare.select', { server: r.name })}
                onchange={() => toggle(r.id)}
              />
            </td>
            <th scope="row">
              <button class="compare-name" onclick={() => toggle(r.id)}>
                {#if color}<span class="swatch" style="background: {color}"></span>{/if}{r.name}
              </button>
            </th>
            <td class="compare-bar-cell">
              <span
                class="compare-bar"
                style="width: {Math.min(100, ((r.stats?.avg ?? 0) / barMax) * 100)}%"
              ></span>
            </td>
            <td>
              <svg
                width={SPARK_W}
                height={SPARK_H}
                viewBox="0 0 {SPARK_W} {SPARK_H}"
                aria-hidden="true"
                class="compare-spark"
              >
                <path d={sparkPath(r.values)} fill="none" stroke={color ?? 'currentColor'} />
              </svg>
            </td>
            <td>{formatValue(r.stats?.avg, unit)}</td>
            <td>{formatValue(r.stats?.max, unit)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .compare-view {
    padding: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .compare-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
  }
  .compare-title {
    margin: 0;
    margin-right: auto;
    font-size: var(--text-base);
    color: var(--text-strong);
  }
  .compare-tools {
    display: flex;
    justify-content: flex-end;
  }
  .compare-message,
  .compare-hint {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .compare-ranking {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  .compare-ranking th,
  .compare-ranking td {
    padding: 4px 8px;
    text-align: right;
    border-bottom: 1px solid var(--border-faint);
  }
  .compare-ranking th[scope='row'] {
    text-align: left;
    font-weight: 500;
  }
  .compare-ranking thead th {
    color: var(--text-subtle);
    font-weight: 500;
  }
  .compare-ranking td {
    font-family: var(--font-mono);
  }
  .compare-ranking tr.chosen th[scope='row'] {
    color: var(--text-strong);
  }
  .compare-name {
    background: none;
    border: 0;
    padding: 0;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }
  .compare-bar-cell {
    width: 30%;
  }
  .compare-bar {
    display: block;
    height: 6px;
    border-radius: 3px;
    background: var(--accent);
    opacity: 0.7;
  }
  .compare-spark {
    color: var(--text-subtle);
    vertical-align: middle;
  }
  .swatch {
    display: inline-block;
    width: 10px;
    height: 3px;
    margin-right: 6px;
    border-radius: 2px;
    vertical-align: middle;
  }
</style>
