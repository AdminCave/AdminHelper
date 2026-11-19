<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // One server: identity, a bar of its objects by state and its coverage, its vital objects as
  // tiles, its open problems, then every object grouped by kind, groups with problems first. The
  // groups start closed and show their objects as dots, so the server fits on one screen.
  import Badge from '../../../components/ui/Badge.svelte';
  import Dot from '../../../components/ui/Dot.svelte';
  import Meter from '../Meter.svelte';
  import ObjectRow from '../ObjectRow.svelte';
  import type { Kind, MonObject } from '../model';
  import {
    KIND_LABEL,
    STATUS_LABEL,
    STATUS_TONE,
    formatValue,
    isHidden,
    sortObjects,
  } from '../grammar';
  import KindGroups from './KindGroups.svelte';
  import { isProblem, nestParts } from './lists';
  import StatusBar from './StatusBar.svelte';
  import { serverSummaries } from './servers';

  interface Props {
    objects: MonObject[];
    now: Date;
    selected?: string;
    server: string;
    /** The kind to open and highlight, from a Lagekarte cell. */
    focusKind?: Kind | '';
    onOpen: (key: string) => void;
  }

  let { objects, now, selected, server, focusKind = '', onOpen }: Props = $props();

  // The kinds a tile shows, in this order, when the server has them.
  const VITAL: Kind[] = ['host', 'cpu', 'memory', 'updates', 'reboot'];

  const own = $derived(objects.filter((o) => o.server === server));
  const host = $derived(own.find((o) => o.kind === 'host'));
  const vitals = $derived(
    VITAL.flatMap((k) => own.filter((o) => o.kind === k && !isHidden(o)).slice(0, 1)),
  );
  const problems = $derived(nestParts(sortObjects(own.filter(isProblem))));
  const summary = $derived(serverSummaries(own)[0]);
  const coverage = $derived({
    watched: own.filter((o) => !isHidden(o) && o.status !== 'not-collected').length,
    hidden: own.filter(isHidden).length,
    notCollected: own.filter((o) => !isHidden(o) && o.status === 'not-collected').length,
  });

  let allOpen = $state(false);
</script>

<header class="head" data-server={server} data-worst={summary?.worst}>
  <div class="title">
    {#if summary}<Dot st={summary.worst} size={12} ring label={STATUS_LABEL[summary.worst]} />{/if}
    <h2>{server}</h2>
    {#if host}
      <Badge tone={STATUS_TONE[host.status]} dot>{host.reason}</Badge>
    {/if}
  </div>
  <p class="identity">
    {host ? host.identity.join(' · ') : 'Kein Agent: nur zentrale Prüfungen und Module'}
  </p>
  {#if summary}
    <div class="sv-bar">
      <StatusBar counts={summary.counts} hidden={summary.hidden} height={8} grow />
    </div>
  {/if}
  <p class="coverage" data-testid="coverage">
    {coverage.watched} überwacht · {coverage.hidden} ausgeblendet · {coverage.notCollected} nicht erhoben
  </p>
</header>

{#if vitals.length > 0}
  <div class="vitals">
    {#each vitals as v, i (v.key)}
      {@const m = v.metrics[0]}
      <button
        type="button"
        class="vital"
        data-status={v.status}
        data-vital={v.kind}
        style:--i={i}
        class:selected={selected === v.key}
        onclick={() => onOpen(v.key)}
      >
        <span class="v-head">
          <Dot st={v.status} size={6} label={STATUS_LABEL[v.status]} />
          {KIND_LABEL[v.kind]}
        </span>
        {#if m}
          <span class="v-value">{formatValue(m.value, m.unit)}</span>
          <span class="v-meta">
            <span class="v-label">{m.label}</span>
            <Meter metric={m} width={72} />
          </span>
        {:else}
          <span class="v-value">{STATUS_LABEL[v.status]}</span>
        {/if}
        <span class="v-reason">{v.reason}</span>
      </button>
    {/each}
  </div>
{/if}

<section class="block" aria-label="Probleme">
  <h3>Probleme <span class="count">{problems.length}</span></h3>
  {#if problems.length === 0}
    <p class="none">Keine offenen Probleme auf {server}.</p>
  {:else}
    <div class="list-box">
      {#each problems as r (r.object.key)}
        <ObjectRow
          object={r.object}
          {now}
          depth={r.depth}
          selected={selected === r.object.key}
          {onOpen}
        />
      {/each}
    </div>
  {/if}
</section>

<section class="block" aria-label="Objekte">
  <div class="objects-head">
    <h3>Objekte <span class="count">{own.length}</span></h3>
    <button type="button" class="toggle" onclick={() => (allOpen = !allOpen)}
      >{allOpen ? 'Alle zuklappen' : 'Alle aufklappen'}</button
    >
  </div>
  <KindGroups objects={own} {now} {selected} open={allOpen} focus={focusKind} {onOpen} />
</section>

<style>
  .head {
    margin-bottom: var(--space-5);
    padding: var(--space-4) var(--space-5);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
  }
  .head[data-worst='critical'] {
    border-color: var(--danger-border);
    box-shadow: inset 0 3px 0 var(--danger);
  }
  .head[data-worst='warning'] {
    border-color: var(--warning-border);
    box-shadow: inset 0 3px 0 var(--warning);
  }
  .sv-bar {
    max-width: 480px;
    margin-top: var(--space-3);
  }
  .title {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  h2 {
    margin: 0;
    font-size: var(--text-2xl);
    color: var(--text-strong);
  }
  .identity,
  .coverage {
    margin: var(--space-1) 0 0;
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .coverage {
    color: var(--text-subtle);
  }
  .vitals {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: var(--space-3);
    margin-bottom: var(--space-6);
  }
  .vital {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
    animation: rise 380ms var(--ease-out) backwards;
    animation-delay: calc(80ms + var(--i) * 60ms);
    transition:
      border-color var(--dur-fast) var(--ease-standard),
      box-shadow var(--dur-base) var(--ease-out),
      transform var(--dur-base) var(--ease-out);
  }
  .vital:hover {
    border-color: var(--border-hover);
    box-shadow: var(--shadow-md);
    transform: translateY(-2px);
  }
  .vital.selected {
    background: var(--surface-active);
  }
  .vital[data-status='critical'] {
    border-color: var(--danger-border);
    background: var(--danger-bg);
  }
  .vital[data-status='warning'] {
    border-color: var(--warning-border);
    background: var(--warning-bg);
  }
  .v-head {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .v-value {
    font-size: var(--text-2xl);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--text-strong);
  }
  .v-meta {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-xs);
    color: var(--text-subtle);
  }
  .v-reason {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--text-xs);
    color: var(--text-subtle);
  }
  .block {
    margin-bottom: var(--space-6);
  }
  h3 {
    margin: 0 0 var(--space-2);
    font-size: var(--text-base);
    color: var(--text-strong);
  }
  .count {
    color: var(--text-subtle);
    font-weight: 400;
  }
  .none {
    margin: 0;
    color: var(--text-muted);
  }
  .list-box {
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
    overflow: hidden;
  }
  .objects-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
  }
  .toggle {
    padding: 0;
    border: 0;
    background: none;
    font: inherit;
    font-size: var(--text-sm);
    color: var(--accent);
    cursor: pointer;
  }
  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(10px);
    }
  }
  /* Phone: two vitals per line, the title wraps under its badge. */
  @media (max-width: 760px) {
    .head {
      padding: var(--space-3) var(--space-4);
    }
    .title {
      flex-wrap: wrap;
      row-gap: var(--space-1);
    }
    h2 {
      font-size: var(--text-xl);
    }
    .vitals {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: var(--space-2);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .vital {
      animation: none;
    }
  }
</style>
