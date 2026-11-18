<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // A metric's history as a plain SVG line with its warning and critical limits as dashed lines;
  // colours come from the tokens so both themes work.
  import { dateText, formatValue, thresholdText } from '../grammar';
  import type { TrendDetail } from '../model';

  interface Props {
    detail: TrendDetail;
  }

  let { detail }: Props = $props();

  const W = 480;
  const H = 120;
  const PAD = 6;

  const times = $derived(detail.points.map((p) => new Date(p.at).getTime()));
  const values = $derived(detail.points.map((p) => p.value));
  const limits = $derived(
    (['warn', 'crit'] as const)
      .filter((k) => detail.threshold?.[k] !== undefined)
      .map((k) => ({ kind: k, value: detail.threshold![k]! })),
  );
  const lo = $derived(Math.min(0, ...values));
  const hi = $derived(Math.max(...values, ...limits.map((l) => l.value)) * 1.1 || 1);
  const t0 = $derived(Math.min(...times));
  const t1 = $derived(Math.max(...times));

  function x(t: number): number {
    return t1 === t0 ? W / 2 : PAD + ((t - t0) / (t1 - t0)) * (W - 2 * PAD);
  }
  function y(v: number): number {
    return H - PAD - ((v - lo) / (hi - lo)) * (H - 2 * PAD);
  }

  const line = $derived(
    detail.points.map((p, i) => `${x(times[i]).toFixed(1)},${y(p.value).toFixed(1)}`).join(' '),
  );
  const last = $derived(detail.points[detail.points.length - 1]);
</script>

<svg
  viewBox="0 0 {W} {H}"
  role="img"
  aria-label="{detail.title}: zuletzt {formatValue(last.value, detail.unit)}"
>
  {#each limits as l (l.kind)}
    <line
      class="limit {l.kind}"
      data-limit={l.kind}
      x1={PAD}
      x2={W - PAD}
      y1={y(l.value)}
      y2={y(l.value)}
    />
  {/each}
  <polyline class="series" points={line} />
</svg>
<p class="caption">
  {dateText(detail.points[0].at)} bis {dateText(last.at)} · zuletzt
  {formatValue(last.value, detail.unit)}{#if detail.threshold}
    · {thresholdText(detail.threshold)}{/if}
</p>

<style>
  svg {
    width: 100%;
    height: auto;
    display: block;
    border: 1px solid var(--border-faint);
    border-radius: var(--radius-md);
    background: var(--surface);
  }
  .series {
    fill: none;
    stroke: var(--accent);
    stroke-width: 2;
    vector-effect: non-scaling-stroke;
  }
  .limit {
    stroke-width: 1;
    stroke-dasharray: 4 4;
    vector-effect: non-scaling-stroke;
  }
  .limit.warn {
    stroke: var(--warning);
  }
  .limit.crit {
    stroke: var(--danger);
  }
  .caption {
    margin: var(--space-1) 0 0;
    font-size: var(--text-sm);
    color: var(--text-subtle);
  }
</style>
