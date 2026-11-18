<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // The cross views (Konzept §5): one table per question over all servers. The first column is
  // always Zustand with reason and since; a hidden object stays grey with its exception.
  import Badge from '../../../components/ui/Badge.svelte';
  import Dot from '../../../components/ui/Dot.svelte';
  import EmptyState from '../../../components/ui/EmptyState.svelte';
  import Pill from '../../../components/ui/Pill.svelte';
  import Segmented from '../../../components/ui/Segmented.svelte';
  import type { MonObject } from '../model';
  import { STATUS_LABEL, STATUS_TONE, exceptionText, isHidden, sinceText } from '../grammar';
  import { CROSS_VIEWS } from './cross';

  interface Props {
    objects: MonObject[];
    now: Date;
    selected?: string;
    view?: string;
    onOpen: (key: string) => void;
  }

  let { objects, now, selected, view = $bindable(CROSS_VIEWS[0].id), onOpen }: Props = $props();

  const current = $derived(CROSS_VIEWS.find((v) => v.id === view) ?? CROSS_VIEWS[0]);
  const rows = $derived(current.rows(objects));
</script>

<Segmented
  options={CROSS_VIEWS.map((v) => ({ value: v.id, label: v.title }))}
  value={current.id}
  label="Querschnitt"
  onChange={(v) => (view = v)}
/>

<p class="hint">{current.hint}</p>

{#if rows.length === 0}
  <EmptyState title="Nichts zu zeigen" description="Kein Objekt gehört in diesen Querschnitt." />
{:else}
  <div class="wrap">
    <table class="tbl" data-view={current.id}>
      <thead>
        <tr>
          <th>Zustand</th>
          {#each current.columns as c (c.key)}
            <th data-col={c.key}>{c.title}</th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each rows as r (r.object.key)}
          {@const hidden = isHidden(r.object)}
          <tr
            data-key={r.object.key}
            data-status={r.object.status}
            class:hidden
            class:selected={selected === r.object.key}
          >
            <td class="state">
              {#if hidden}
                <Badge>Ausgeblendet</Badge>
              {:else}
                <Badge tone={STATUS_TONE[r.object.status]} dot
                  >{STATUS_LABEL[r.object.status]}</Badge
                >
              {/if}
              <button type="button" class="open" onclick={() => onOpen(r.object.key)}
                >{hidden && r.object.exception
                  ? exceptionText(r.object.exception)
                  : r.object.reason}</button
              >
              {#if !hidden}<span class="since">{sinceText(r.object.since, now)}</span>{/if}
            </td>
            {#each r.cells as cell, i (current.columns[i].key)}
              <td class:mono={cell.mono}>
                <span class="val">
                  {#if cell.status && cell.status !== 'ok'}<Dot st={cell.status} size={6} />{/if}
                  {cell.text}
                  {#if cell.newData}<Pill
                      tone="accent"
                      title="Der Agent liefert diesen Wert noch nicht">neue Agent-Daten</Pill
                    >{/if}
                </span>
                {#if cell.sub}<span class="sub">{cell.sub}</span>{/if}
              </td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  .hint {
    margin: var(--space-3) 0;
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .wrap {
    overflow-x: auto;
  }
  .tbl {
    width: 100%;
    border-collapse: collapse;
    border: 1px solid var(--border);
    background: var(--surface);
    font-size: var(--text-sm);
  }
  th {
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--border);
    color: var(--text-subtle);
    font-weight: 500;
    text-align: left;
    white-space: nowrap;
  }
  td {
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--border-faint);
    vertical-align: top;
  }
  tbody tr:hover {
    background: var(--surface-hover);
  }
  tr.selected {
    background: var(--surface-active);
  }
  tr.hidden {
    opacity: 0.6;
  }
  .state {
    min-width: 220px;
  }
  .open {
    display: block;
    margin-top: var(--space-1);
    padding: 0;
    border: 0;
    background: none;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .since,
  .sub {
    display: block;
    color: var(--text-subtle);
    font-size: var(--text-xs);
  }
  .val {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
  .mono {
    font-family: var(--font-mono);
  }
</style>
