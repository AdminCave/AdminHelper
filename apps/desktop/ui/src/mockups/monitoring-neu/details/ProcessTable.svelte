<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Top processes of a host at the last report, sorted by CPU or memory.
  import Pill from '../../../components/ui/Pill.svelte';
  import { formatValue } from '../grammar';
  import type { ProcessDetail } from '../model';

  interface Props {
    detail: ProcessDetail;
  }

  let { detail }: Props = $props();
</script>

<table class="tbl">
  <thead>
    <tr>
      <th class="num">PID</th>
      <th>Prozess</th>
      <th>Benutzer</th>
      <th class="num" class:sorted={detail.sortedBy === 'cpu'}>CPU</th>
      <th class="num" class:sorted={detail.sortedBy === 'mem'}>RAM</th>
    </tr>
  </thead>
  <tbody>
    {#each detail.rows as p (p.pid)}
      <tr data-pid={p.pid}>
        <td class="mono num">{p.pid}</td>
        <td class="mono">{p.name}</td>
        <td>{p.user}</td>
        <td class="mono num">{formatValue(p.cpu, '%')}</td>
        <td class="mono num">{formatValue(p.memMb, 'MB')}</td>
      </tr>
    {/each}
  </tbody>
</table>
<p class="muted">
  Sortiert nach {detail.sortedBy === 'cpu' ? 'CPU' : 'RAM'}, Stand der letzten Meldung{#if detail.newData}
    <Pill tone="accent" title="Der Agent liefert die Prozessliste noch nicht">neue Agent-Daten</Pill
    >{/if}
</p>

<style>
  .tbl {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  .tbl th,
  .tbl td {
    padding: var(--space-1) var(--space-2) var(--space-1) 0;
    border-bottom: 1px solid var(--border-faint);
    text-align: left;
  }
  .tbl th {
    font-weight: 500;
    color: var(--text-muted);
  }
  .tbl th.sorted {
    color: var(--text-strong);
  }
  .num {
    text-align: right;
  }
  .tbl th.num {
    text-align: right;
  }
  .mono {
    font-family: var(--font-mono);
  }
  .muted {
    margin: var(--space-2) 0 0;
    font-size: var(--text-sm);
    color: var(--text-subtle);
  }
</style>
