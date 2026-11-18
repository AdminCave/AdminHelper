<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // One server: identity, its open problems, then every object grouped by kind with module parts
  // under their instance, and a short coverage line (what is watched, hidden, not collected).
  import Select from '../../../components/ui/Select.svelte';
  import ObjectRow from '../ObjectRow.svelte';
  import type { Kind, MonObject } from '../model';
  import { KIND_LABEL, isHidden, sortObjects } from '../grammar';
  import { isProblem, nestParts, serversOf } from './lists';

  interface Props {
    objects: MonObject[];
    now: Date;
    selected?: string;
    server?: string;
    onOpen: (key: string) => void;
  }

  let { objects, now, selected, server = $bindable(''), onOpen }: Props = $props();

  const servers = $derived(serversOf(objects));
  const current = $derived(server || servers[0]);
  const own = $derived(objects.filter((o) => o.server === current));
  const host = $derived(own.find((o) => o.kind === 'host'));
  const problems = $derived(sortObjects(own.filter(isProblem)));
  const groups = $derived(
    [...new Set<Kind>(own.map((o) => o.kind))].map((kind) => ({
      kind,
      rows: nestParts(sortObjects(own.filter((o) => o.kind === kind))),
    })),
  );
  const coverage = $derived({
    watched: own.filter((o) => !isHidden(o) && o.status !== 'not-collected').length,
    hidden: own.filter(isHidden).length,
    notCollected: own.filter((o) => !isHidden(o) && o.status === 'not-collected').length,
  });
</script>

<div class="bar">
  <label class="pick">
    <span>Server</span>
    <Select value={current} options={servers} onChange={(v) => (server = v)} />
  </label>
</div>

<header class="head" data-server={current}>
  <h2>{current}</h2>
  <p class="identity">
    {host ? host.identity.join(' · ') : 'Kein Agent: nur zentrale Prüfungen und Module'}
  </p>
  <p class="coverage" data-testid="coverage">
    {coverage.watched} überwacht · {coverage.hidden} ausgeblendet · {coverage.notCollected} nicht erhoben
  </p>
</header>

<section aria-label="Probleme">
  <h3>Probleme <span class="count">{problems.length}</span></h3>
  {#if problems.length === 0}
    <p class="none">Keine offenen Probleme auf {current}.</p>
  {:else}
    <div class="list">
      {#each problems as o (o.key)}
        <ObjectRow object={o} {now} selected={selected === o.key} {onOpen} />
      {/each}
    </div>
  {/if}
</section>

{#each groups as g (g.kind)}
  <section class="group" aria-label={KIND_LABEL[g.kind]} data-kind={g.kind}>
    <h3>{KIND_LABEL[g.kind]} <span class="count">{g.rows.length}</span></h3>
    <div class="list">
      {#each g.rows as r (r.object.key)}
        <div class:part={r.depth === 1}>
          <ObjectRow object={r.object} {now} selected={selected === r.object.key} {onOpen} />
        </div>
      {/each}
    </div>
  </section>
{/each}

<style>
  .bar {
    margin-bottom: var(--space-4);
  }
  .pick {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .head {
    margin-bottom: var(--space-5);
  }
  h2 {
    margin: 0;
    font-size: var(--text-lg);
    color: var(--text-strong);
  }
  .identity,
  .coverage {
    margin: var(--space-1) 0 0;
    font-size: var(--text-sm);
    color: var(--text-muted);
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
  section {
    margin-bottom: var(--space-6);
  }
  .none {
    margin: 0;
    color: var(--text-muted);
  }
  .list {
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
    overflow: hidden;
  }
  .part {
    margin-left: var(--space-8);
    border-left: 2px solid var(--border);
  }
</style>
