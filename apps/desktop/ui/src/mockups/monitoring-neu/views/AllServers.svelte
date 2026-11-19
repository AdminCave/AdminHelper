<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // "Alle Server", the start (Konzept §3.14, Kevin 2026-11-18: by server, not across; clearer at a
  // glance): one figure for the open problems and a bar of every rated object by state, whose
  // legend filters the page; the Lagekarte of every server by kind beside the newest problems;
  // then the problems per server, worst first. Compact (the start, Kevin 2026-11-18) shows each
  // server as a card with its worst problems; with metrics, each server lists its problems with
  // level 2. A silent host carries its stale objects, a module instance its parts.
  import { flip } from 'svelte/animate';
  import { cubicOut } from 'svelte/easing';
  import { Tween, prefersReducedMotion } from 'svelte/motion';
  import { fade } from 'svelte/transition';
  import Dot from '../../../components/ui/Dot.svelte';
  import EmptyState from '../../../components/ui/EmptyState.svelte';
  import Segmented from '../../../components/ui/Segmented.svelte';
  import ObjectRow from '../ObjectRow.svelte';
  import type { Kind, MonObject, Status } from '../model';
  import { STATUS_LABEL, isHidden, objectLabel, sinceText } from '../grammar';
  import Lagekarte from './Lagekarte.svelte';
  import { isProblem, lageOf, type LageEntry } from './lists';
  import StatusBar from './StatusBar.svelte';
  import { lageByServer, type ServerLage } from './servers';

  interface Props {
    objects: MonObject[];
    now: Date;
    selected?: string;
    onOpen: (key: string) => void;
    onServer: (server: string, kind?: Kind) => void;
  }

  let { objects, now, selected, onOpen, onServer }: Props = $props();

  /** Problem lines a card shows before "+n weitere". */
  const CARD_LINES = 4;
  /** Lines of "Neueste Probleme". */
  const RECENT_LINES = 12;
  /** Server cards (compact) or boxes (with metrics) before "weitere anzeigen"; each click adds
   * as many again, so hundreds of servers never draw at once (Kevin 2026-11-19). */
  const CARDS = 24;
  const BOXES = 8;
  /** A rest this small is shown rather than folded. */
  const SLACK = 4;
  const RATED: Status[] = ['critical', 'warning', 'unknown', 'stale', 'info', 'ok'];
  const FILTERS: ReadonlySet<Status> = new Set<Status>(['critical', 'warning', 'unknown', 'stale']);

  let density = $state('compact');
  const compact = $derived(density === 'compact');
  let filter = $state<Status | ''>('');
  let more = $state(0);
  // Hovering a legend entry previews its filter on the Lagekarte.
  let preview = $state<Status | ''>('');

  const lage = $derived(lageOf(objects));
  const grouped = $derived(lageByServer(objects));
  const shown = $derived(objects.filter((o) => !isHidden(o)));
  const counts = $derived(
    Object.fromEntries(
      (['critical', 'warning', 'unknown', 'stale', 'info', 'not-collected', 'ok'] as Status[]).map(
        (st) => [st, RATED.includes(st) ? shown.filter((o) => o.status === st).length : 0],
      ),
    ) as Record<Status, number>,
  );
  const critical = $derived(counts.critical > 0);

  function ms(n: number): number {
    return prefersReducedMotion.current ? 0 : n;
  }

  // The figure counts up to the number of open problems.
  const figure = new Tween(0, { duration: 900, easing: cubicOut });
  $effect(() => {
    void figure.set(lage.problems.length, { duration: ms(900) });
  });

  const stand = $derived(
    now.toLocaleTimeString('de-DE', {
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Europe/Berlin',
    }),
  );

  function matches(e: LageEntry, st: Status): boolean {
    return e.object.status === st || e.parts.some((p) => p.status === st);
  }

  // The filter narrows each server to the entries in that state; stale keeps the stale values.
  const attention = $derived(
    filter === ''
      ? grouped.attention
      : grouped.attention
          .map((g) =>
            filter === 'stale'
              ? { ...g, entries: g.entries.filter((e) => e.stale.length > 0) }
              : { ...g, entries: g.entries.filter((e) => matches(e, filter as Status)), stale: [] },
          )
          .filter((g) => g.entries.length > 0 || g.stale.length > 0),
  );
  const step = $derived(compact ? CARDS : BOXES);
  const limit = $derived(
    attention.length <= step * (more + 1) + SLACK ? attention.length : step * (more + 1),
  );

  const recent = $derived(
    (filter ? shown.filter((o) => o.status === filter) : objects.filter(isProblem))
      .slice()
      .sort((a, b) => b.since.localeCompare(a.since))
      .slice(0, RECENT_LINES),
  );

  function toggle(st: Status): void {
    filter = filter === st ? '' : st;
    more = 0;
  }

  function lines(g: ServerLage): MonObject[] {
    return [
      ...g.entries.map((e) => e.object),
      ...(filter === 'stale' ? g.entries.flatMap((e) => e.stale) : []),
      ...g.stale,
    ];
  }

  function folded(g: ServerLage): number {
    return g.entries.reduce((n, e) => n + e.stale.length, 0);
  }

  function footNote(rest: number, stale: number): string {
    return [rest > 0 ? `+${rest} weitere` : '', stale ? `${stale} Werte veraltet` : '']
      .filter(Boolean)
      .join(' · ');
  }

  function short(iso: string): string {
    return sinceText(iso, now).replace(/^seit /, '');
  }
</script>

<header class="head">
  <h2>Alle Server</h2>
  <span class="live" title="Die Werte kommen laufend herein">
    <span class="live-dot" aria-hidden="true"></span>
    Stand {stand}
  </span>
</header>

<section class="hero" aria-label="Lage auf einen Blick">
  <div class="hero-figure">
    <span class="hero-n" class:critical aria-hidden="true">{Math.round(figure.current)}</span>
    <span class="hero-text">
      <span class="hero-label">
        <span class="sr-only">{lage.problems.length}</span>
        {lage.problems.length === 1 ? 'offenes Problem' : 'offene Probleme'}
      </span>
      <span class="hero-sub" data-testid="lage-summary"
        >auf {grouped.attention.length} von {lage.servers} Servern</span
      >
    </span>
  </div>
  <div class="hero-chart">
    <StatusBar {counts} height={24} label="Bewertete Objekte nach Zustand" grow />
    <div class="legend" role="group" aria-label="Nach Zustand filtern">
      {#each RATED as st, i (st)}
        {#if FILTERS.has(st)}
          <button
            type="button"
            class="lg-item"
            class:zero={counts[st] === 0}
            data-tile={st}
            aria-pressed={filter === st}
            disabled={counts[st] === 0}
            style:--i={i}
            onclick={() => toggle(st)}
            onpointerenter={() => (preview = st)}
            onpointerleave={() => (preview = '')}
          >
            <span class="sw" data-st={st}></span>
            <span class="lg-n">{counts[st]}</span>
            <span class="lg-label">{STATUS_LABEL[st]}</span>
          </button>
        {:else}
          <span class="lg-item static" data-tile={st} style:--i={i}>
            <span class="sw" data-st={st}></span>
            <span class="lg-n">{counts[st]}</span>
            <span class="lg-label">{STATUS_LABEL[st]}</span>
          </span>
        {/if}
      {/each}
      <span class="lg-rest">
        {lage.notCollected} nicht erhoben · {lage.hidden} ausgeblendet
      </span>
    </div>
  </div>
</section>

<div class="overview">
  <section class="panel map" aria-label="Lagekarte">
    <header class="panel-head">
      <h3>Lagekarte</h3>
      <span class="panel-sub">Jede Zeile ein Server, jede Spalte eine Objektart</span>
    </header>
    <Lagekarte {objects} {now} filter={filter || preview} {onOpen} {onServer} />
  </section>

  <section class="panel recent" aria-label="Neueste Probleme">
    <header class="panel-head">
      <h3>{filter ? `Neueste: ${STATUS_LABEL[filter]}` : 'Neueste Probleme'}</h3>
    </header>
    {#if recent.length === 0}
      <p class="none">Nichts in diesem Zustand.</p>
    {:else}
      <ol class="rc-list">
        {#each recent as o, i (o.key)}
          <li animate:flip={{ duration: ms(260) }} out:fade={{ duration: ms(120) }} style:--i={i}>
            <button
              type="button"
              class="rc-item"
              class:selected={selected === o.key}
              data-key={o.key}
              data-status={o.status}
              onclick={() => onOpen(o.key)}
            >
              <Dot st={o.status} size={8} label={STATUS_LABEL[o.status]} />
              <span class="rc-name" title={objectLabel(o)}>{o.name}</span>
              <span class="rc-since">{short(o.since)}</span>
              <span class="rc-meta"><strong>{o.server}</strong> · {o.reason}</span>
            </button>
          </li>
        {/each}
      </ol>
    {/if}
  </section>
</div>

<section class="detail" aria-label="Probleme je Server">
  <header class="detail-head">
    <h3>Probleme je Server <span class="count">{attention.length}</span></h3>
    {#if filter}
      <p class="filter-note">
        <span>Nur <strong>{STATUS_LABEL[filter]}</strong></span>
        <button type="button" class="link" onclick={() => (filter = '')}>Filter aufheben</button>
      </p>
    {/if}
    <span class="spacer"></span>
    <Segmented
      options={[
        { value: 'compact', label: 'Kompakt' },
        { value: 'full', label: 'Mit Kennzahlen' },
      ]}
      bind:value={density}
      label="Dichte"
    />
  </header>

  {#if grouped.attention.length === 0}
    <EmptyState
      title="Keine offenen Probleme"
      description="Alles, was bewertet wird, ist in Ordnung."
    />
  {/if}

  {#if compact}
    <div class="board">
      {#each attention.slice(0, limit) as g, i (g.summary.server)}
        {@const all = lines(g)}
        {@const rest = all.length - CARD_LINES}
        {@const stale = folded(g)}
        <section
          class="server-card board-card"
          data-server={g.summary.server}
          data-worst={g.summary.worst}
          aria-label={g.summary.server}
          style:--i={i}
          animate:flip={{ duration: ms(320), easing: cubicOut }}
          out:fade={{ duration: ms(140) }}
        >
          <header class="card-head">
            <Dot st={g.summary.worst} label={STATUS_LABEL[g.summary.worst]} />
            <button type="button" class="server" onclick={() => onServer(g.summary.server)}
              >{g.summary.server}</button
            >
            <span class="tally">
              {#if g.summary.counts.critical}<span class="t" data-st="critical"
                  >{g.summary.counts.critical} kritisch</span
                >{/if}
              {#if g.summary.counts.warning}<span class="t" data-st="warning"
                  >{g.summary.counts.warning} Warnung</span
                >{/if}
            </span>
          </header>
          <ul class="p-lines">
            {#each all.slice(0, CARD_LINES) as o (o.key)}
              {@const parts = g.entries.find((e) => e.object.key === o.key)?.parts.length ?? 0}
              <li>
                <button
                  type="button"
                  class="p-line"
                  class:selected={selected === o.key}
                  data-key={o.key}
                  data-status={o.status}
                  onclick={() => onOpen(o.key)}
                >
                  <Dot st={o.status} size={7} label={STATUS_LABEL[o.status]} />
                  <span class="p-name" title={objectLabel(o)}
                    >{o.name}{#if parts}<span class="p-parts"> +{parts}</span>{/if}</span
                  >
                  <span class="p-reason" title={o.reason}>{o.reason}</span>
                  <span class="p-since">{short(o.since)}</span>
                </button>
              </li>
            {/each}
          </ul>
          <footer class="card-foot">
            <span class="more">{footNote(rest, stale)}</span>
            <button type="button" class="open" onclick={() => onServer(g.summary.server)}
              >Server öffnen →</button
            >
          </footer>
        </section>
      {/each}
    </div>
  {:else}
    {#each attention.slice(0, limit) as g, i (g.summary.server)}
      <section
        class="server-card wide-card"
        data-server={g.summary.server}
        aria-label={g.summary.server}
        style:--i={i}
        animate:flip={{ duration: ms(320), easing: cubicOut }}
        out:fade={{ duration: ms(140) }}
      >
        <header class="card-head wide">
          <Dot st={g.summary.worst} label={STATUS_LABEL[g.summary.worst]} />
          <button type="button" class="server" onclick={() => onServer(g.summary.server)}
            >{g.summary.server}</button
          >
          <span class="wide-identity">{g.summary.identity.join(' · ') || 'ohne Agent'}</span>
          <span class="tally">
            {#if g.summary.counts.critical}<span class="t" data-st="critical"
                >{g.summary.counts.critical} kritisch</span
              >{/if}
            {#if g.summary.counts.warning}<span class="t" data-st="warning"
                >{g.summary.counts.warning} Warnung</span
              >{/if}
          </span>
          <button type="button" class="open" onclick={() => onServer(g.summary.server)}
            >Server öffnen →</button
          >
        </header>
        {#each g.entries as e (e.object.key)}
          <div class="entry" data-entry={e.object.key}>
            <ObjectRow object={e.object} {now} selected={selected === e.object.key} {onOpen} />
            {#if e.stale.length > 0}
              <p class="folded" data-folded={e.object.key}>
                Veraltet mit diesem Host:
                {#each e.stale as s, j (s.key)}
                  <button
                    type="button"
                    class="link"
                    data-stale-key={s.key}
                    onclick={() => onOpen(s.key)}>{objectLabel(s)}</button
                  >{j < e.stale.length - 1 ? ', ' : ''}
                {/each}
              </p>
            {/if}
            {#each e.parts as p (p.key)}
              <ObjectRow object={p} {now} depth={1} selected={selected === p.key} {onOpen} />
            {/each}
          </div>
        {/each}
        {#if g.stale.length > 0}
          <p class="folded stale" data-stale-server={g.summary.server}>
            Veraltete Werte:
            {#each g.stale as s, j (s.key)}
              <button
                type="button"
                class="link"
                data-stale-key={s.key}
                onclick={() => onOpen(s.key)}>{objectLabel(s)}</button
              >{j < g.stale.length - 1 ? ', ' : ''}
            {/each}
          </p>
        {/if}
      </section>
    {/each}
  {/if}
  {#if attention.length > limit}
    {@const rest = attention.slice(limit)}
    <div class="more-servers">
      <span class="more-dots" aria-hidden="true">
        {#each rest.slice(0, 40) as g (g.summary.server)}
          <span class="md" data-st={g.summary.worst}></span>
        {/each}
      </span>
      <button type="button" class="more-btn" onclick={() => (more += 1)}>
        {rest.length <= step + SLACK ? rest.length : step} weitere Server zeigen
      </button>
      <span class="more-of">noch {rest.length} mit Problemen</span>
    </div>
  {/if}
</section>

<style>
  .head {
    display: flex;
    align-items: center;
    gap: var(--space-4);
    margin-bottom: var(--space-4);
  }
  h2 {
    margin: 0;
    font-size: var(--text-xl);
    color: var(--text-strong);
  }
  .live {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-subtle);
  }
  .live-dot {
    position: relative;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--success);
  }
  .live-dot::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: var(--success);
    animation: ping 2.4s var(--ease-out) infinite;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }

  /* The one figure of the page and the bar of every rated object. */
  .hero {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: var(--space-8);
    margin-bottom: var(--space-5);
    padding: var(--space-5) var(--space-6);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
    animation: rise 420ms var(--ease-out) backwards;
  }
  .hero-figure {
    display: flex;
    align-items: center;
    gap: var(--space-4);
  }
  .hero-n {
    min-width: 2ch;
    font-size: 52px;
    font-weight: 600;
    line-height: 1;
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
    color: var(--text-strong);
  }
  .hero-n.critical {
    color: var(--danger);
  }
  .hero-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .hero-label {
    font-size: var(--text-lg);
    font-weight: 600;
    color: var(--text-strong);
  }
  .hero-sub {
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .hero-chart {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    min-width: 0;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
  }
  .lg-item {
    display: inline-flex;
    align-items: baseline;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-3);
    border: 1px solid transparent;
    border-radius: var(--radius-pill);
    background: transparent;
    color: var(--text);
    font: inherit;
    font-size: var(--text-sm);
    animation: rise 360ms var(--ease-out) backwards;
    animation-delay: calc(500ms + var(--i) * 60ms);
  }
  button.lg-item {
    border-color: var(--border);
    cursor: pointer;
    transition:
      background var(--dur-fast) var(--ease-standard),
      border-color var(--dur-fast) var(--ease-standard),
      transform var(--dur-fast) var(--ease-out);
  }
  button.lg-item:hover:not(:disabled) {
    border-color: var(--border-hover);
    background: var(--surface-hover);
    transform: translateY(-1px);
  }
  button.lg-item:focus-visible {
    outline: none;
    box-shadow: var(--ring-shadow);
  }
  button.lg-item[aria-pressed='true'] {
    border-color: var(--text-muted);
    background: var(--surface-active);
  }
  button.lg-item:disabled {
    cursor: default;
    opacity: 0.5;
  }
  .lg-item.static {
    padding-left: var(--space-2);
  }
  .sw,
  .t::before {
    align-self: center;
    width: 10px;
    height: 10px;
    border-radius: 3px;
    background: var(--border-strong);
  }
  .sw[data-st='critical'],
  .t[data-st='critical']::before {
    background: var(--danger);
  }
  .sw[data-st='warning'],
  .t[data-st='warning']::before {
    background: var(--warning);
  }
  .sw[data-st='unknown'],
  .sw[data-st='stale'] {
    background: var(--text-subtle);
  }
  .sw[data-st='info'] {
    background: var(--info);
  }
  .sw[data-st='ok'] {
    background: var(--success);
    opacity: 0.55;
  }
  .lg-n {
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--text-strong);
  }
  .lg-label {
    color: var(--text-muted);
  }
  .lg-rest {
    margin-left: auto;
    font-size: var(--text-xs);
    color: var(--text-subtle);
  }

  /* Overview: the Lagekarte and the newest problems. */
  .overview {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    gap: var(--space-5);
    margin-bottom: var(--space-8);
  }
  .panel {
    padding: var(--space-4) var(--space-5) var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
    animation: rise 460ms var(--ease-out) backwards;
  }
  .map {
    flex: 0 1 auto;
    min-width: 0;
    animation-delay: 120ms;
  }
  .recent {
    flex: 1 1 300px;
    align-self: stretch;
    min-width: 280px;
    animation-delay: 220ms;
  }
  .panel-head {
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
    margin-bottom: var(--space-3);
  }
  .panel-sub {
    font-size: var(--text-xs);
    color: var(--text-subtle);
  }
  h3 {
    margin: 0;
    font-size: var(--text-base);
    font-weight: 600;
    color: var(--text-strong);
  }
  .count {
    font-weight: 400;
    color: var(--text-subtle);
  }
  .none {
    margin: 0;
    color: var(--text-muted);
  }
  .rc-list {
    display: flex;
    flex-direction: column;
    margin: 0 calc(-1 * var(--space-2));
    padding: 0;
    list-style: none;
  }
  .rc-list > li {
    animation: slide-in 380ms var(--ease-out) backwards;
    animation-delay: calc(420ms + var(--i) * 55ms);
  }
  .rc-item {
    display: grid;
    grid-template-columns: 10px minmax(0, 1fr) auto;
    grid-template-areas:
      'dot name since'
      '. meta meta';
    column-gap: var(--space-2);
    row-gap: 1px;
    align-items: center;
    width: 100%;
    padding: 7px var(--space-2);
    border: 0;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
    transition:
      background var(--dur-fast) var(--ease-standard),
      transform var(--dur-fast) var(--ease-out);
  }
  .rc-item:hover {
    background: var(--surface-hover);
    transform: translateX(3px);
  }
  .rc-item.selected {
    background: var(--surface-active);
  }
  .rc-item:focus-visible {
    outline: none;
    box-shadow: var(--ring-shadow);
  }
  .rc-name {
    grid-area: name;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-strong);
  }
  .rc-since {
    grid-area: since;
    font-size: var(--text-xs);
    font-variant-numeric: tabular-nums;
    color: var(--text-subtle);
  }
  .rc-meta {
    grid-area: meta;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--text-xs);
    color: var(--text-muted);
  }
  .rc-meta strong {
    font-weight: 500;
    color: var(--text);
  }

  /* Problems per server. */
  .detail-head {
    display: flex;
    align-items: center;
    gap: var(--space-4);
    margin-bottom: var(--space-4);
  }
  .spacer {
    flex: 1;
  }
  .filter-note {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    margin: 0;
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .board {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: var(--space-4);
  }
  .server-card {
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
    animation: rise 420ms var(--ease-out) backwards;
    animation-delay: calc(min(var(--i), 12) * 40ms + 300ms);
  }
  .board-card {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4) var(--space-2);
    transition:
      border-color var(--dur-fast) var(--ease-standard),
      box-shadow var(--dur-base) var(--ease-out),
      transform var(--dur-base) var(--ease-out);
  }
  .board-card:hover {
    border-color: var(--border-hover);
    box-shadow: var(--shadow-md);
    transform: translateY(-2px);
  }
  .card-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .card-head.wide {
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border);
  }
  .server {
    padding: 0;
    border: 0;
    background: none;
    font: inherit;
    font-size: var(--text-base);
    font-weight: 600;
    color: var(--text-strong);
    cursor: pointer;
  }
  .server:hover {
    text-decoration: underline;
  }
  .tally {
    display: inline-flex;
    gap: var(--space-3);
    margin-left: auto;
    font-size: var(--text-xs);
    color: var(--text-muted);
  }
  .card-head.wide .tally {
    margin-left: 0;
  }
  .t {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
  }
  .t::before {
    content: '';
    width: 8px;
    height: 8px;
    border-radius: 2px;
  }
  .wide-identity {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--text-sm);
    color: var(--text-subtle);
  }
  .p-lines {
    flex: 1;
    margin: 0 calc(-1 * var(--space-2));
    padding: 0;
    list-style: none;
  }
  .p-line {
    display: grid;
    grid-template-columns: 10px minmax(0, max-content) minmax(0, 1fr) auto;
    column-gap: var(--space-2);
    align-items: center;
    width: 100%;
    padding: 5px var(--space-2);
    border: 0;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
    transition: background var(--dur-fast) var(--ease-standard);
  }
  .p-line:hover {
    background: var(--surface-hover);
  }
  .p-line.selected {
    background: var(--surface-active);
  }
  .p-line:focus-visible {
    outline: none;
    box-shadow: var(--ring-shadow);
  }
  .p-name {
    max-width: 170px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-strong);
  }
  .p-parts {
    font-weight: 400;
    color: var(--text-subtle);
  }
  .p-reason {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .p-since {
    font-size: var(--text-xs);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
    color: var(--text-subtle);
  }
  .card-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding-top: var(--space-2);
    border-top: 1px solid var(--border-faint);
  }
  .more {
    font-size: var(--text-xs);
    color: var(--text-subtle);
  }
  .open {
    padding: 0;
    border: 0;
    background: none;
    font: inherit;
    font-size: var(--text-sm);
    color: var(--accent);
    cursor: pointer;
    transition: transform var(--dur-fast) var(--ease-out);
  }
  .open:hover {
    text-decoration: underline;
    transform: translateX(2px);
  }

  /* With metrics: one wide box per server. */
  .wide-card {
    margin-bottom: var(--space-4);
    overflow: hidden;
  }
  .entry:last-child :global(.row:last-child) {
    border-bottom: 0;
  }
  .folded {
    margin: 0;
    padding: var(--space-1) var(--space-4) var(--space-2) calc(104px + 2 * var(--space-4));
    border-bottom: 1px solid var(--border-faint);
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .folded.stale {
    padding-left: var(--space-4);
    border-bottom: 0;
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

  .more-servers {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-4);
    margin-top: var(--space-4);
    padding: var(--space-3) var(--space-4);
    border: 1px dashed var(--border);
    border-radius: var(--radius-lg);
  }
  .more-dots {
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
    max-width: 260px;
  }
  .md {
    width: 8px;
    height: 8px;
    border-radius: 2px;
    background: var(--text-subtle);
  }
  .md[data-st='critical'] {
    background: var(--danger);
  }
  .md[data-st='warning'] {
    background: var(--warning);
  }
  .more-btn {
    padding: var(--space-1) var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    background: var(--surface);
    color: var(--text-strong);
    font: inherit;
    font-size: var(--text-sm);
    cursor: pointer;
    transition:
      background var(--dur-fast) var(--ease-standard),
      border-color var(--dur-fast) var(--ease-standard);
  }
  .more-btn:hover {
    border-color: var(--border-hover);
    background: var(--surface-hover);
  }
  .more-btn:focus-visible {
    outline: none;
    box-shadow: var(--ring-shadow);
  }
  .more-of {
    font-size: var(--text-sm);
    color: var(--text-subtle);
  }

  /* Phone: one column; the figure above the bar, the map above the newest problems. */
  @media (max-width: 760px) {
    .hero {
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-4);
      padding: var(--space-4);
    }
    .hero-n {
      font-size: 44px;
    }
    .lg-rest {
      margin-left: 0;
    }
    /* A grid, not a wrapping flex column: a wrapping line takes the width of its widest item. */
    .overview {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-4);
      margin-bottom: var(--space-6);
    }
    .panel {
      padding: var(--space-3) var(--space-4);
    }
    .map,
    .recent {
      flex: none;
      min-width: 0;
    }
    .panel-head {
      flex-wrap: wrap;
    }
    .detail-head {
      flex-wrap: wrap;
      gap: var(--space-2) var(--space-3);
    }
    .board {
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-3);
    }
    .p-name {
      max-width: 120px;
    }
    .card-head.wide {
      flex-wrap: wrap;
    }
    .wide-identity {
      flex-basis: 100%;
      order: 5;
    }
    .folded {
      padding-left: var(--space-4);
    }
  }

  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(10px);
    }
  }
  @keyframes slide-in {
    from {
      opacity: 0;
      transform: translateX(14px);
    }
  }
  @keyframes ping {
    from {
      opacity: 0.7;
      transform: scale(1);
    }
    to {
      opacity: 0;
      transform: scale(2.6);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .hero,
    .lg-item,
    .panel,
    .rc-list > li,
    .server-card,
    .live-dot::after {
      animation: none;
    }
  }
</style>
