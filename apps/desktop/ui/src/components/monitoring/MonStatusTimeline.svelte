<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitoringMetricSeries } from '$lib/api/types';

  interface Props {
    statusHistory: MonitoringMetricSeries[] | null | undefined;
  }
  let { statusHistory }: Props = $props();

  interface Segment {
    widthPct: number;
    color: string;
  }

  const STATUS_COLORS: Record<number, string> = {
    0: 'var(--mon-ok-bg, #22c55e)',
    1: 'var(--mon-warn-bg, #f59e0b)',
    2: 'var(--mon-crit-bg, #ef4444)',
    3: 'var(--mon-unknown-bg, #94a3b8)',
  };

  let segments = $derived.by<Segment[]>(() => {
    const results = statusHistory ?? [];
    if (results.length === 0 || !results[0]?.values?.length) return [];
    const values = results[0].values;
    const total = values.length;
    const out: Segment[] = [];
    let segStart = 0;
    let segStatus = Math.round(parseFloat(values[0][1]));
    for (let i = 1; i <= total; i++) {
      const curStatus = i < total ? Math.round(parseFloat(values[i][1])) : -1;
      if (curStatus !== segStatus) {
        out.push({
          widthPct: ((i - segStart) / total) * 100,
          color: STATUS_COLORS[segStatus] ?? STATUS_COLORS[3],
        });
        segStart = i;
        segStatus = curStatus;
      }
    }
    return out;
  });
</script>

{#if segments.length > 0}
  <div class="mon-status-timeline">
    <div class="mon-timeline-bar">
      {#each segments as s}
        <div
          class="mon-timeline-seg"
          style="width: {s.widthPct}%; background-color: {s.color};"
        ></div>
      {/each}
    </div>
  </div>
{/if}
