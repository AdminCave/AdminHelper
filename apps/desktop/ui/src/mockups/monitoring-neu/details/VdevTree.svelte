<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Layout of a ZFS pool as a tree: pool, vdevs, devices with their state and error counters.
  import Dot from '../../../components/ui/Dot.svelte';
  import type { VdevDetail, VdevNode } from '../model';

  interface Props {
    detail: VdevDetail;
  }

  let { detail }: Props = $props();
</script>

{#snippet node(n: VdevNode, depth: number)}
  <tr data-vdev={n.name}>
    <td class="mono" style:padding-left="calc(var(--space-4) * {depth})">{n.name}</td>
    <td><Dot st={n.status} size={6} /> {n.state}</td>
    <td class="mono num">{n.read}</td>
    <td class="mono num">{n.write}</td>
    <td class="mono num">{n.cksum}</td>
    <td class="muted">{n.note ?? ''}</td>
  </tr>
  {#each n.children ?? [] as c (c.name)}
    {@render node(c, depth + 1)}
  {/each}
{/snippet}

<table class="tbl">
  <thead>
    <tr>
      <th>Name</th>
      <th>Zustand</th>
      <th class="num">Lesen</th>
      <th class="num">Schreiben</th>
      <th class="num">Prüfsumme</th>
      <th></th>
    </tr>
  </thead>
  <tbody>
    {@render node(detail.root, 0)}
  </tbody>
</table>

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
  .num {
    text-align: right;
  }
  .mono {
    font-family: var(--font-mono);
  }
  .muted {
    color: var(--text-subtle);
  }
</style>
