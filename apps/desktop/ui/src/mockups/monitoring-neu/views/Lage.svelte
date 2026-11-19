<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // The start view (Konzept §3.14): only open problems, worst first; everything green in one line.
  // A silent host carries its stale objects, a module instance its named parts with problems.
  import EmptyState from '../../../components/ui/EmptyState.svelte';
  import ObjectRow from '../ObjectRow.svelte';
  import type { MonObject } from '../model';
  import { KIND_LABEL } from '../grammar';
  import { ackText, lageOf } from './lists';

  interface Props {
    objects: MonObject[];
    now: Date;
    selected?: string;
    onOpen: (key: string) => void;
  }

  let { objects, now, selected, onOpen }: Props = $props();

  const lage = $derived(lageOf(objects));
</script>

<p class="summary" data-testid="lage-summary">
  {lage.problems.length === 1 ? '1 offenes Problem' : `${lage.problems.length} offene Probleme`} ·
  <span class="ok">{lage.ok} ok</span> · {lage.info} Hinweise · {lage.notCollected} nicht erhoben ·
  {lage.hidden} ausgeblendet · {lage.servers} Server
</p>

{#if lage.problems.length === 0}
  <EmptyState
    title="Keine offenen Probleme"
    description="Alles, was bewertet wird, ist in Ordnung."
  />
{:else}
  <div class="list" aria-label="Offene Probleme">
    {#each lage.problems as e (e.object.key)}
      <div class="entry" data-entry={e.object.key}>
        <ObjectRow
          object={e.object}
          {now}
          showServer
          selected={selected === e.object.key}
          {onOpen}
        />
        {#if e.object.ack}
          <p class="ack" data-ack={e.object.key}>{ackText(e.object.ack)}</p>
        {/if}
        {#if e.stale.length > 0}
          <p class="folded" data-folded={e.object.key}>
            Veraltet mit diesem Host:
            {#each e.stale as s, i (s.key)}
              <button
                type="button"
                class="link"
                data-stale-key={s.key}
                onclick={() => onOpen(s.key)}>{KIND_LABEL[s.kind]} {s.name}</button
              >{i < e.stale.length - 1 ? ', ' : ''}
            {/each}
          </p>
        {/if}
        {#if e.parts.length > 0}
          <div class="parts" aria-label="Teile von {e.object.name}">
            {#each e.parts as p (p.key)}
              <ObjectRow object={p} {now} selected={selected === p.key} {onOpen} />
              {#if p.ack}
                <p class="ack" data-ack={p.key}>{ackText(p.ack)}</p>
              {/if}
            {/each}
          </div>
        {/if}
      </div>
    {/each}
  </div>
{/if}

{#if lage.staleLeft.length > 0}
  <section class="stale" aria-label="Veraltete Werte ohne Host-Problem">
    <h2>Veraltete Werte</h2>
    {#each lage.staleLeft as g (g.server)}
      <p class="folded">
        {g.server}:
        {#each g.objects as s, i (s.key)}
          <button type="button" class="link" data-stale-key={s.key} onclick={() => onOpen(s.key)}
            >{KIND_LABEL[s.kind]} {s.name}</button
          >{i < g.objects.length - 1 ? ', ' : ''}
        {/each}
      </p>
    {/each}
  </section>
{/if}

<style>
  .summary {
    margin: 0 0 var(--space-4);
    color: var(--text-muted);
  }
  .ok {
    color: var(--text-strong);
  }
  .list {
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
    overflow: hidden;
  }
  .entry {
    border-bottom: 1px solid var(--border);
  }
  .entry:last-child {
    border-bottom: 0;
  }
  .ack,
  .folded {
    margin: 0;
    padding: 0 var(--space-4) var(--space-3) calc(112px + var(--space-4) + var(--space-3));
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .parts {
    margin-left: var(--space-8);
    border-left: 2px solid var(--border);
  }
  .link {
    padding: 0;
    border: 0;
    background: none;
    color: var(--accent);
    font: inherit;
    cursor: pointer;
  }
  .link:hover {
    text-decoration: underline;
  }
  .stale {
    margin-top: var(--space-6);
  }
  h2 {
    margin: 0 0 var(--space-2);
    font-size: var(--text-base);
    color: var(--text-strong);
  }
</style>
