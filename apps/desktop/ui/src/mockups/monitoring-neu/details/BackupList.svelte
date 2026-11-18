<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Backups of one guest, newest first: time, size, storage, verification, protection.
  import Dot from '../../../components/ui/Dot.svelte';
  import { dateText } from '../grammar';
  import type { BackupDetail } from '../model';

  interface Props {
    detail: BackupDetail;
  }

  let { detail }: Props = $props();

  const VERIFY: Record<'ok' | 'failed' | 'none', string> = {
    ok: 'verifiziert',
    failed: 'Verifizierung fehlgeschlagen',
    none: 'nicht verifiziert',
  };
</script>

<table class="tbl">
  <thead>
    <tr>
      <th>Zeitpunkt</th>
      <th class="num">Größe</th>
      <th>Ablage</th>
      <th>Prüfung</th>
    </tr>
  </thead>
  <tbody>
    {#each detail.rows as b (b.at)}
      <tr>
        <td class="mono">{dateText(b.at)}</td>
        <td class="mono num">{b.size}</td>
        <td>{b.storage}{b.protected ? ' · geschützt' : ''}</td>
        <td>
          {#if b.status && b.status !== 'ok'}<Dot st={b.status} size={6} />{/if}
          {VERIFY[b.verify]}
        </td>
      </tr>
    {/each}
  </tbody>
</table>
{#if detail.retention}
  <p class="muted">Aufbewahrung: {detail.retention}</p>
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
  .num {
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
