<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // SMART attributes as smartctl reports them (raw, normalised, threshold, when_failed) and the
  // set bits of its exit code in plain words.
  import Dot from '../../../components/ui/Dot.svelte';
  import type { SmartDetail } from '../model';

  interface Props {
    detail: SmartDetail;
  }

  let { detail }: Props = $props();

  const hex = (bit: number) => `0x${(1 << bit).toString(16).padStart(2, '0')}`;
</script>

<table class="tbl">
  <thead>
    <tr>
      <th>ID</th>
      <th>Attribut</th>
      <th>Roh</th>
      <th>Normiert</th>
      <th>Schwelle</th>
      <th>Fehlgeschlagen</th>
    </tr>
  </thead>
  <tbody>
    {#each detail.rows as r (r.name)}
      <tr data-attr={r.name}>
        <td class="mono">{r.id ?? '—'}</td>
        <td>
          {#if r.status && r.status !== 'ok'}<Dot st={r.status} size={6} />{/if}
          {r.name}
        </td>
        <td class="mono">{r.raw}</td>
        <td class="mono">{r.normalized ?? '—'}</td>
        <td class="mono">{r.threshold ?? '—'}</td>
        <td>{r.whenFailed ?? '—'}</td>
      </tr>
    {/each}
  </tbody>
</table>
{#if detail.exitBits.length > 0}
  <ul class="bits" aria-label="smartctl-Exit-Code">
    {#each detail.exitBits as b (b.bit)}
      <li><code>{hex(b.bit)}</code> {b.text}</li>
    {/each}
  </ul>
{/if}

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
  .mono,
  code {
    font-family: var(--font-mono);
  }
  .bits {
    margin: var(--space-2) 0 0;
    padding-left: var(--space-4);
    font-size: var(--text-sm);
  }
</style>
