<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // The server list on the left (Kevin 2026-11-18: as in today's monitoring): "Alle Server" first,
  // then every server worst first, one line each with its open problems, so two dozen servers fit
  // without scrolling. The selection glides to the chosen server. Arrow keys move through the list
  // like the list of today's monitoring; "/" jumps to the search. With many servers the quiet ones
  // fold into one line (Kevin 2026-11-19: hundreds of servers must still read well).
  import Dot from '../../../components/ui/Dot.svelte';
  import Pill from '../../../components/ui/Pill.svelte';
  import SearchField from '../../../components/ui/SearchField.svelte';
  import { STATUS_LABEL } from '../grammar';
  import type { ServerSummary } from './servers';

  interface Props {
    summaries: ServerSummary[];
    /** The selected server; empty for "Alle Server". */
    server: string;
    onSelect: (server: string) => void;
  }

  let { summaries, server, onSelect }: Props = $props();

  /** Up to this many quiet servers stay listed; more fold behind one line. */
  const QUIET_OPEN = 24;

  let query = $state('');
  let search = $state<HTMLInputElement | undefined>(undefined);
  let list = $state<HTMLElement | undefined>(undefined);
  // The selection marker: where the selected item sits; it glides only after the first placement.
  let markY = $state(0);
  let markH = $state(0);
  let ready = $state(false);
  const shown = $derived(
    summaries.filter((s) =>
      s.server.toLocaleLowerCase('de').includes(query.toLocaleLowerCase('de')),
    ),
  );
  const troubled = $derived(shown.filter((s) => s.problems > 0 || s.worst === 'stale'));
  const quiet = $derived(shown.filter((s) => !troubled.includes(s)));
  let showQuiet = $state(false);
  // A search or a quiet selected server always lists them.
  const quietOpen = $derived(
    showQuiet ||
      query !== '' ||
      quiet.length <= QUIET_OPEN ||
      quiet.some((s) => s.server === server),
  );
  const totals = $derived({
    critical: summaries.reduce((n, s) => n + s.counts.critical, 0),
    warning: summaries.reduce((n, s) => n + s.counts.warning, 0),
    troubled: summaries.filter((s) => s.problems > 0).length,
  });

  $effect(() => {
    void server;
    void query;
    void quietOpen;
    const el = list?.querySelector<HTMLElement>('.item.selected');
    markY = el?.offsetTop ?? 0;
    markH = el?.offsetHeight ?? 0;
  });
  $effect(() => {
    if (markH && !ready) requestAnimationFrame(() => (ready = true));
  });

  function slash(e: KeyboardEvent): void {
    const t = e.target as HTMLElement;
    if (e.key !== '/' || t.closest('input, textarea, select, [contenteditable]')) return;
    e.preventDefault();
    search?.focus();
  }

  function move(e: KeyboardEvent): void {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const items = [
      ...(e.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('.item'),
    ];
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      items[Math.min(items.length - 1, Math.max(0, at + (e.key === 'ArrowDown' ? 1 : -1)))];
    if (!next) return;
    e.preventDefault();
    next.focus();
    next.click();
  }
</script>

{#snippet item(s: ServerSummary)}
  <button
    type="button"
    class="item"
    class:selected={server === s.server}
    aria-current={server === s.server ? 'true' : undefined}
    data-server={s.server}
    onclick={() => onSelect(s.server)}
  >
    <Dot st={s.worst} label={STATUS_LABEL[s.worst]} />
    <span class="name">{s.server}</span>
    <span class="pills">
      {#if s.counts.critical}<Pill tone="crit">{s.counts.critical}</Pill>{/if}
      {#if s.counts.warning}<Pill tone="warn">{s.counts.warning}</Pill>{/if}
    </span>
  </button>
{/snippet}

<svelte:window onkeydown={slash} />

<nav class="nav" aria-label="Server">
  <div class="search">
    <SearchField
      bind:value={query}
      bind:input={search}
      placeholder="Server suchen"
      size="sm"
      label="Server suchen"
      shortcut="/"
    />
  </div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="items" bind:this={list} onkeydown={move}>
    <span
      class="marker"
      class:ready
      aria-hidden="true"
      style:transform="translateY({markY}px)"
      style:height="{markH}px"
      style:opacity={markH ? 1 : 0}
    ></span>
    <button
      type="button"
      class="item all"
      class:selected={server === ''}
      aria-current={server === '' ? 'true' : undefined}
      data-server=""
      onclick={() => onSelect('')}
    >
      <span class="all-icon" aria-hidden="true">▦</span>
      <span class="all-text">
        <span class="name">Alle Server</span>
        <span class="sub">{totals.troubled} von {summaries.length} mit Problemen</span>
      </span>
      <span class="pills">
        {#if totals.critical}<Pill tone="crit">{totals.critical}</Pill>{/if}
        {#if totals.warning}<Pill tone="warn">{totals.warning}</Pill>{/if}
      </span>
    </button>

    {#if troubled.length}
      <h2>Mit Problemen <span class="count">{troubled.length}</span></h2>
      {#each troubled as s (s.server)}{@render item(s)}{/each}
    {/if}
    {#if quiet.length}
      <h2>Ohne Probleme <span class="count">{quiet.length}</span></h2>
      {#if quietOpen}
        {#each quiet as s (s.server)}{@render item(s)}{/each}
      {:else}
        <button type="button" class="fold" aria-expanded="false" onclick={() => (showQuiet = true)}>
          <span class="fold-dots" aria-hidden="true"></span>
          {quiet.length} Server ohne Probleme zeigen
        </button>
      {/if}
    {/if}
    {#if shown.length === 0}
      <p class="none">Kein Server passt zu „{query}“.</p>
    {/if}
  </div>
</nav>

<style>
  .nav {
    display: flex;
    flex-direction: column;
    min-height: 0;
    height: 100%;
    border-right: 1px solid var(--border);
    background: var(--bg-sidebar);
  }
  .search {
    padding: var(--space-3);
    border-bottom: 1px solid var(--border-faint);
  }
  .items {
    position: relative;
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: var(--space-2);
  }
  .marker {
    position: absolute;
    top: 0;
    left: var(--space-2);
    right: var(--space-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface-active);
    pointer-events: none;
  }
  .marker::before {
    content: '';
    position: absolute;
    top: 6px;
    bottom: 6px;
    left: -1px;
    width: 3px;
    border-radius: 2px;
    background: var(--accent);
  }
  .marker.ready {
    transition:
      transform 300ms var(--ease-out),
      height 300ms var(--ease-out),
      opacity var(--dur-fast) var(--ease-standard);
  }
  @media (prefers-reduced-motion: reduce) {
    .marker.ready {
      transition: none;
    }
  }
  h2 {
    margin: var(--space-3) var(--space-3) var(--space-1);
    font-size: var(--text-xs);
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--text-subtle);
  }
  .count {
    font-weight: 400;
  }
  .item {
    display: grid;
    grid-template-columns: 8px minmax(0, 1fr) auto;
    align-items: center;
    column-gap: var(--space-2);
    width: 100%;
    min-height: 30px;
    padding: 3px var(--space-3);
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text);
    font: inherit;
    font-size: var(--text-sm);
    text-align: left;
    cursor: pointer;
    position: relative;
    transition: background var(--dur-fast) var(--ease-standard);
  }
  .item:hover:not(.selected) {
    background: var(--surface-hover);
  }
  .item:focus-visible {
    outline: none;
    box-shadow: var(--ring-shadow);
  }
  .item.all {
    grid-template-columns: 24px minmax(0, 1fr) auto;
    min-height: 44px;
    margin-bottom: var(--space-1);
  }
  .all-icon {
    display: grid;
    place-items: center;
    width: 24px;
    height: 24px;
    border-radius: var(--radius-md);
    background: var(--surface-raised);
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .all-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 500;
    color: var(--text-strong);
  }
  .all .name {
    font-weight: 600;
  }
  .sub {
    font-size: var(--text-xs);
    color: var(--text-subtle);
  }
  .pills {
    display: inline-flex;
    gap: var(--space-1);
  }
  .none {
    margin: var(--space-3) var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .fold {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    width: 100%;
    min-height: 32px;
    padding: 3px var(--space-3);
    border: 1px dashed var(--border);
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text-muted);
    font: inherit;
    font-size: var(--text-sm);
    text-align: left;
    cursor: pointer;
    transition:
      background var(--dur-fast) var(--ease-standard),
      color var(--dur-fast) var(--ease-standard);
  }
  .fold:hover {
    background: var(--surface-hover);
    color: var(--text);
  }
  .fold:focus-visible {
    outline: none;
    box-shadow: var(--ring-shadow);
  }
  .fold-dots {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--success);
    opacity: 0.6;
  }
  /* Phone: finger-sized lines. */
  @media (max-width: 760px) {
    .item {
      min-height: 40px;
    }
    .fold {
      min-height: 40px;
    }
  }
</style>
