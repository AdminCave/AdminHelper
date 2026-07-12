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
    start: number;
    widthPct: number;
    color: string;
  }

  // Semantic tokens (defined in app.css :root + :root[data-theme=light]); used inline,
  // so var() resolves live per theme — the timeline flips with the toggle, no re-render.
  const STATUS_COLORS: Record<number, string> = {
    0: 'var(--success)',
    1: 'var(--warning)',
    2: 'var(--danger)',
    3: 'var(--text-muted)',
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
          start: segStart,
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
      {#each segments as s (s.start)}
        <div
          class="mon-timeline-seg"
          style="width: {s.widthPct}%; background-color: {s.color};"
        ></div>
      {/each}
    </div>
  </div>
{/if}
