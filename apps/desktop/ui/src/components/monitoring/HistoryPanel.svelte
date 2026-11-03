<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { untrack } from 'svelte';
  import { save } from '@tauri-apps/plugin-dialog';
  import { errMsg } from '$lib/utils/errors';
  import { sessionStore } from '$lib/stores/session';
  import { monitoringApi } from '$lib/api/monitoring';
  import { writeExportCsv } from '$lib/bridge';
  import type {
    HistoryPoint,
    HistorySeries,
    MonitorCheck,
    MonitoringMetricsResponse,
    ServerHistory,
  } from '$lib/api/types';
  import {
    daysUntilFull,
    forecast,
    formatValue,
    linearSlope,
    stats,
    toCsv,
    type ChartSeries,
    type ChartThreshold,
    type ChartUnit,
    type Value,
  } from '$lib/charts';
  import TimeChart from '../charts/TimeChart.svelte';
  import { t } from '$lib/i18n';

  interface Props {
    serverId: string;
    serverName: string;
    /** The server's ping, TCP and HTTP checks: one latency line each. */
    latencyChecks: MonitorCheck[];
  }
  let { serverId, serverName, latencyChecks }: Props = $props();

  const PERIODS = ['1h', '24h', '7d', '30d'] as const;
  type Period = (typeof PERIODS)[number];
  type Tab = 'cpu' | 'disk' | 'latency' | 'load';
  const COLORS = ['#38bdf8', '#22c55e', '#f97316', '#a855f7', '#ec4899', '#14b8a6'];
  // The measured value of each latency check type; the check duration is the fallback.
  const LATENCY_NAMES = [
    'monitor_ping_rtt_ms_value',
    'monitor_tcp_connect_ms_value',
    'monitor_http_response_ms_value',
  ];
  const FULL_PILL_DAYS = 60;

  let period = $state<Period>('24h');
  let tab = $state<Tab>('cpu');
  let showPrev = $state(true);
  let hidden = $state<Record<string, boolean>>({});
  let zoom = $state<[number, number] | null>(null);
  let history = $state<ServerHistory | null>(null);
  let latency = $state<Record<string, Value[]>>({});
  let loading = $state(false);
  let error = $state<string | null>(null);
  let exportMsg = $state('');

  // A fast period switch can leave two loads in flight; only the newest may write.
  let loadGen = 0;
  let latencyGen = 0;

  async function load(server: string, p: Period): Promise<void> {
    const { session } = $sessionStore;
    if (!session) return;
    const gen = ++loadGen;
    // The old server's or period's data must not stand under the new name, nor go into a CSV.
    history = null;
    latency = {};
    loading = true;
    error = null;
    try {
      const res = await monitoringApi.fetchServerHistory(session, server, p);
      if (gen !== loadGen) return;
      history = res;
    } catch (err) {
      if (gen !== loadGen) return;
      history = null;
      error = errMsg(err);
    } finally {
      if (gen === loadGen) loading = false;
    }
  }

  function onGrid(res: MonitoringMetricsResponse, h: ServerHistory): Value[] {
    const series = res.data ?? [];
    const pick =
      series.find((s) => LATENCY_NAMES.includes(s.metric?.__name__ ?? '')) ??
      series.find((s) => s.metric?.__name__ === 'monitor_check_duration_ms_value');
    const out: Value[] = Array<Value>(Math.floor((h.end - h.start) / h.step) + 1).fill(null);
    for (const [ts, raw] of pick?.values ?? []) {
      const i = Math.round((ts - h.start) / h.step);
      const v = Number(raw);
      if (i >= 0 && i < out.length && Number.isFinite(v)) out[i] = v;
    }
    return out;
  }

  async function loadLatency(h: ServerHistory, p: Period, checks: MonitorCheck[]): Promise<void> {
    const { session } = $sessionStore;
    if (!session) return;
    const gen = ++latencyGen;
    const results = await Promise.allSettled(
      checks.map((c) => monitoringApi.fetchMetrics(session, c.id, p)),
    );
    if (gen !== latencyGen) return;
    const next: Record<string, Value[]> = {};
    results.forEach((r, i) => {
      if (r.status === 'fulfilled') next[checks[i].id] = onGrid(r.value, h);
    });
    latency = next;
  }

  $effect(() => {
    const server = serverId;
    const p = period;
    zoom = null;
    void load(server, p);
  });

  // The dashboard rebuilds the check list on every poll; only other checks mean a new load.
  const latencyIds = $derived(latencyChecks.map((c) => c.id).join(','));

  $effect(() => {
    void latencyIds;
    if (tab === 'latency' && history) {
      const h = history;
      untrack(() => {
        if (latencyChecks.length > 0) void loadLatency(h, period, latencyChecks);
      });
    }
  });

  function values(points: HistoryPoint[] | undefined): Value[] {
    return (points ?? []).map((p) => p[1]);
  }
  function hasData(points: HistoryPoint[] | undefined): boolean {
    return (points ?? []).some((p) => p[1] != null);
  }

  const gridLength = $derived(
    history ? Math.floor((history.end - history.start) / history.step) + 1 : 0,
  );
  const forecastSteps = $derived(Math.round(gridLength / 4));

  function base(s: HistorySeries | null | undefined, tabName: Tab): ChartSeries[] {
    if (!s) return [];
    if (tabName === 'cpu') {
      const out: ChartSeries[] = [
        { key: 'cpu', label: 'CPU', color: COLORS[0], data: values(s.cpu), area: true },
        { key: 'ram', label: 'RAM', color: COLORS[1], data: values(s.ram) },
      ];
      if (hasData(s.swap))
        out.push({ key: 'swap', label: 'Swap', color: COLORS[2], data: values(s.swap) });
      return out;
    }
    if (tabName === 'disk') {
      return Object.keys(s.disks)
        .sort()
        .map((mount, i) => ({
          key: `disk:${mount}`,
          label: mount,
          color: COLORS[i % COLORS.length],
          data: values(s.disks[mount]),
        }));
    }
    if (tabName === 'load') {
      return [
        {
          key: 'load',
          label: $t('monitoring.history.loadPerCpu'),
          color: COLORS[3],
          data: values(s.loadPerCpu),
          area: true,
        },
      ];
    }
    return [];
  }

  const measured = $derived.by((): ChartSeries[] => {
    if (!history) return [];
    if (tab === 'latency') {
      return latencyChecks.map((c, i) => ({
        key: `check:${c.id}`,
        label: c.name,
        color: COLORS[i % COLORS.length],
        data: latency[c.id] ?? [],
      }));
    }
    const prev = new Map(base(history.previous, tab).map((s) => [s.key, s.data]));
    return base(history.series, tab).map((s) => ({
      ...s,
      prev: showPrev ? (prev.get(s.key) ?? null) : null,
      hidden: hidden[s.key] ?? false,
    }));
  });

  // Disk: a linear fit per mount continued past the last point, as long as it grows.
  const fits = $derived.by(() => {
    if (tab !== 'disk' || !history) return [];
    return measured.map((s) => {
      const slope = linearSlope(s.data);
      const cur = [...s.data].reverse().find((v): v is number => v != null) ?? null;
      const days = cur == null ? null : daysUntilFull(cur, slope, history?.step ?? 0);
      return { series: s, slope, days };
    });
  });

  const chartSeries = $derived.by((): ChartSeries[] => {
    const out = measured.map((s) => ({ ...s, hidden: hidden[s.key] ?? false }));
    for (const f of fits) {
      if (f.slope == null || !(f.slope > 0)) continue;
      out.push({
        key: `${f.series.key}:forecast`,
        label: `${f.series.label} · ${$t('monitoring.chart.forecast')}`,
        color: f.series.color,
        data: forecast(f.series.data, f.slope, forecastSteps),
        dash: '5 4',
        forecast: true,
        hidden: hidden[f.series.key] ?? false,
      });
    }
    return out;
  });

  const showsForecast = $derived(chartSeries.some((s) => s.forecast));
  const times = $derived.by(() => {
    if (!history) return [];
    const n = gridLength + (showsForecast ? forecastSteps : 0);
    return Array.from({ length: n }, (_, i) => (history?.start ?? 0) + i * (history?.step ?? 0));
  });

  const unit = $derived<ChartUnit>(tab === 'latency' ? 'ms' : tab === 'load' ? '' : '%');
  const thresholdKey = $derived(
    tab === 'cpu' ? 'cpu' : tab === 'disk' ? 'disk' : tab === 'load' ? 'load' : '',
  );
  const thresholds = $derived.by((): ChartThreshold[] => {
    const th = history?.thresholds[thresholdKey];
    if (!th) return [];
    const fmt = (v: number) => (unit === '' ? v.toFixed(1) : formatValue(v, unit));
    return [
      {
        value: th.warn,
        status: 'warning',
        label: $t('monitoring.history.warn', { value: fmt(th.warn) }),
      },
      {
        value: th.crit,
        status: 'critical',
        label: $t('monitoring.history.crit', { value: fmt(th.crit) }),
      },
    ];
  });
  const events = $derived(
    (history?.events ?? []).map((e) => ({ at: e.at, status: e.status, label: e.checkName })),
  );
  const bands = $derived(
    (history?.maintenance ?? []).map((m) => ({
      start: m.start,
      end: m.end,
      label: m.note || $t('monitoring.history.maintenance'),
    })),
  );

  const anyData = $derived(measured.some((s) => s.data.some((v) => v != null)));
  const z0 = $derived(zoom ? zoom[0] : 0);
  const z1 = $derived(zoom ? zoom[1] : Math.max(0, gridLength - 1));
  const rows = $derived(
    measured
      .filter((s) => !(hidden[s.key] ?? false))
      .map((s) => ({ series: s, stats: stats(s.data, z0, z1) })),
  );
  const fullPills = $derived(fits.filter((f) => f.days != null && f.days < FULL_PILL_DAYS));

  function setTab(next: Tab): void {
    tab = next;
    zoom = null;
    exportMsg = '';
  }
  function setPeriod(next: Period): void {
    period = next;
    exportMsg = '';
  }
  function toggle(key: string): void {
    hidden = { ...hidden, [key]: !(hidden[key] ?? false) };
  }

  async function exportCsv(): Promise<void> {
    if (!history) return;
    const slug = `${serverName}-${tab}-${period}`.replace(/[^A-Za-z0-9._-]+/g, '-');
    const grid = times.slice(0, gridLength);
    try {
      const destPath = await save({
        defaultPath: `adminhelper-${slug}.csv`,
        filters: [{ name: 'CSV', extensions: ['csv'] }],
      });
      if (!destPath) return;
      const path = await writeExportCsv(
        destPath,
        toCsv(
          grid,
          measured.map((s) => ({ label: s.label, data: s.data })),
        ),
      );
      exportMsg = $t('monitoring.history.csvSaved', { path });
    } catch (err) {
      exportMsg = $t('monitoring.history.csvError', { error: errMsg(err) });
    }
  }

  const tabs = $derived.by((): Tab[] => {
    const out: Tab[] = ['cpu', 'disk'];
    if (latencyChecks.length > 0) out.push('latency');
    out.push('load');
    return out;
  });
</script>

<section class="mon-section history-panel" aria-label={$t('monitoring.history.title')}>
  <header class="history-head">
    <h3 class="history-title">{$t('monitoring.history.title')}</h3>
    <div class="mon-segmented" role="tablist" aria-label={$t('monitoring.history.title')}>
      {#each tabs as name (name)}
        <button
          class="mon-seg-btn"
          class:active={tab === name}
          role="tab"
          aria-selected={tab === name}
          onclick={() => setTab(name)}>{$t(`monitoring.history.tab.${name}`)}</button
        >
      {/each}
    </div>
    <div class="mon-segmented" role="group" aria-label={$t('monitoring.history.period')}>
      {#each PERIODS as p (p)}
        <button
          class="mon-seg-btn"
          class:active={period === p}
          aria-pressed={period === p}
          onclick={() => setPeriod(p)}>{$t(`monitoring.history.period.${p}`)}</button
        >
      {/each}
    </div>
  </header>

  {#if error}
    <div class="history-message" role="alert">
      {$t('monitoring.history.error', { error })}
    </div>
  {:else if !history}
    <div class="history-message">{loading ? $t('monitoring.chart.loading') : ''}</div>
  {:else}
    <div class="history-tools">
      <div class="history-legend">
        {#each measured as s (s.key)}
          <button
            class="legend-item"
            class:off={hidden[s.key] ?? false}
            aria-pressed={!(hidden[s.key] ?? false)}
            onclick={() => toggle(s.key)}
          >
            <span class="swatch" style="background: {s.color}"></span>{s.label}
          </button>
        {/each}
      </div>
      {#each fullPills as f (f.series.key)}
        <span class="mon-pill {f.days != null && f.days < 14 ? 'pill-crit' : 'pill-warn'}"
          >{$t('monitoring.history.full', {
            mount: f.series.label,
            days: Math.max(1, Math.round(f.days ?? 0)),
          })}</span
        >
      {/each}
      <span class="history-spacer"></span>
      {#if tab !== 'latency'}
        <label class="history-prev">
          <input type="checkbox" bind:checked={showPrev} />
          {$t('monitoring.history.previous')}
        </label>
      {/if}
      {#if zoom}
        <button class="btn small" onclick={() => (zoom = null)}>
          {$t('monitoring.history.resetZoom')}
        </button>
      {/if}
      <button class="btn small" onclick={() => void exportCsv()} disabled={!anyData}>
        {$t('monitoring.history.csv')}
      </button>
    </div>

    {#if anyData}
      <TimeChart
        series={chartSeries}
        {times}
        {unit}
        yMax={unit === '%' ? 100 : undefined}
        {thresholds}
        {events}
        {bands}
        {zoom}
        onZoom={(range) => (zoom = range)}
        nowIndex={showsForecast ? gridLength - 1 : null}
        label={$t('monitoring.history.chartLabel', {
          tab: $t(`monitoring.history.tab.${tab}`),
          server: serverName,
        })}
      />
      <table class="history-stats">
        <thead>
          <tr>
            <th scope="col">{$t('monitoring.history.stat.series')}</th>
            <th scope="col">{$t('monitoring.history.stat.avg')}</th>
            <th scope="col">{$t('monitoring.history.stat.p95')}</th>
            <th scope="col">{$t('monitoring.history.stat.max')}</th>
            <th scope="col">{$t('monitoring.history.stat.cur')}</th>
          </tr>
        </thead>
        <tbody>
          {#each rows as r (r.series.key)}
            <tr>
              <th scope="row"
                ><span class="swatch" style="background: {r.series.color}"></span>{r.series
                  .label}</th
              >
              <td>{formatValue(r.stats?.avg, unit)}</td>
              <td>{formatValue(r.stats?.p95, unit)}</td>
              <td>{formatValue(r.stats?.max, unit)}</td>
              <td>{formatValue(r.stats?.cur, unit)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {:else}
      <div class="history-message">
        {loading ? $t('monitoring.chart.loading') : $t('monitoring.chart.noData')}
      </div>
    {/if}
    {#if exportMsg}
      <div class="history-export" role="status">{exportMsg}</div>
    {/if}
  {/if}
</section>

<style>
  .history-panel {
    padding: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .history-head,
  .history-tools {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
  }
  .history-title {
    margin: 0;
    margin-right: auto;
    font-size: var(--text-base);
    color: var(--text-strong);
  }
  .history-legend {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .legend-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 2px 8px;
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    background: transparent;
    color: var(--text);
    font-size: var(--text-sm);
    cursor: pointer;
  }
  .legend-item.off {
    color: var(--text-subtle);
    opacity: 0.6;
  }
  .swatch {
    display: inline-block;
    width: 10px;
    height: 3px;
    margin-right: 6px;
    border-radius: 2px;
    vertical-align: middle;
  }
  .legend-item .swatch {
    margin-right: 0;
  }
  .history-spacer {
    flex: 1;
  }
  .history-prev {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .history-message,
  .history-export {
    font-size: var(--text-sm);
    color: var(--text-muted);
    padding: var(--space-2) 0;
  }
  .history-stats {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  .history-stats th,
  .history-stats td {
    padding: 4px 8px;
    text-align: right;
    border-bottom: 1px solid var(--border-faint);
  }
  .history-stats td {
    font-family: var(--font-mono);
  }
  .history-stats th:first-child {
    text-align: left;
    font-weight: 500;
    color: var(--text);
  }
  .history-stats thead th {
    color: var(--text-subtle);
    font-weight: 500;
  }
</style>
