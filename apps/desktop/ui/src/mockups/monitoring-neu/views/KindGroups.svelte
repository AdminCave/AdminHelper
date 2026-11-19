<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Objects grouped by kind, groups with problems first. A group starts closed and shows its
  // objects as dots and its worst state in words, so a long list fits on one screen; module
  // parts sit under their instance once it is open. A big group (hundreds of objects across a
  // fleet) shows a bar instead of dots and draws its rows only when open, a page at a time.
  import { prefersReducedMotion } from 'svelte/motion';
  import { SvelteMap } from 'svelte/reactivity';
  import ObjectRow from '../ObjectRow.svelte';
  import type { Kind, MonObject, Status } from '../model';
  import { KIND_LABEL, STATUS_LABEL, isHidden, sortObjects, statusRank } from '../grammar';
  import { nestParts } from './lists';
  import StatusBar from './StatusBar.svelte';

  interface Props {
    objects: MonObject[];
    now: Date;
    selected?: string;
    /** Opens every group (the "Alle aufklappen" switch of the caller). */
    open?: boolean;
    /** Shows the server in each row (lists across servers). */
    showServer?: boolean;
    /** A kind to open, highlight and scroll to (a Lagekarte cell). */
    focus?: Kind | '';
    onOpen: (key: string) => void;
  }

  let {
    objects,
    now,
    selected,
    open = false,
    showServer = false,
    focus = '',
    onOpen,
  }: Props = $props();

  let box = $state<HTMLElement | undefined>(undefined);
  $effect(() => {
    if (!focus || !box) return;
    box.querySelector(`[data-kind="${focus}"]`)?.scrollIntoView({
      block: 'center',
      behavior: prefersReducedMotion.current ? 'auto' : 'smooth',
    });
  });

  const CALM: ReadonlySet<Status> = new Set<Status>(['ok', 'info', 'not-collected']);
  /** Up to this many objects a group shows as dots; more as a bar. */
  const DOTS = 42;
  /** Rows an open group draws before "weitere anzeigen". */
  const PAGE = 60;

  /** Groups the user opened, with the rows they asked to see. */
  const shown = new SvelteMap<Kind, number>();

  function toggled(kind: Kind, e: Event): void {
    if ((e.currentTarget as HTMLDetailsElement).open) {
      if (!shown.has(kind)) shown.set(kind, PAGE);
    } else shown.delete(kind);
  }

  function counts(list: readonly MonObject[]): Record<Status, number> {
    const c = {
      critical: 0,
      warning: 0,
      unknown: 0,
      stale: 0,
      info: 0,
      'not-collected': 0,
      ok: 0,
    } as Record<Status, number>;
    for (const o of list) if (!isHidden(o)) c[o.status] += 1;
    return c;
  }

  const groups = $derived(
    [...new Set<Kind>(objects.map((o) => o.kind))]
      .map((kind) => {
        const list = sortObjects(objects.filter((o) => o.kind === kind));
        const rated = list.filter((o) => !isHidden(o));
        const worst: Status = rated.length ? rated[0].status : 'ok';
        return { kind, list, worst, rows: nestParts(list) };
      })
      .sort(
        (a, b) =>
          statusRank(a.worst) - statusRank(b.worst) ||
          KIND_LABEL[a.kind].localeCompare(KIND_LABEL[b.kind], 'de'),
      ),
  );

  function groupText(list: readonly MonObject[]): string {
    const bad = (['critical', 'warning', 'unknown', 'stale'] as Status[])
      .map((st) => [st, list.filter((o) => !isHidden(o) && o.status === st).length] as const)
      .filter(([, n]) => n > 0)
      .map(([st, n]) => `${n} ${STATUS_LABEL[st].toLocaleLowerCase('de')}`);
    const hidden = list.filter(isHidden).length;
    const text = bad.length ? bad.join(' · ') : 'alles in Ordnung';
    return hidden ? `${text} · ${hidden} ausgeblendet` : text;
  }
</script>

<div class="groups" bind:this={box}>
  {#each groups as g (g.kind)}
    <details
      class="group"
      class:flash={g.kind === focus}
      data-kind={g.kind}
      data-worst={g.worst}
      open={open || g.kind === focus}
      ontoggle={(e) => toggled(g.kind, e)}
    >
      <summary>
        <span class="chev" aria-hidden="true">›</span>
        <span class="g-name" class:calm={CALM.has(g.worst)}>{KIND_LABEL[g.kind]}</span>
        <span class="g-count">{g.list.length}</span>
        {#if g.list.length > DOTS}
          <span class="dots bar">
            <StatusBar
              counts={counts(g.list)}
              hidden={g.list.filter(isHidden).length}
              height={9}
              grow
            />
          </span>
        {:else}
          <span class="dots" aria-hidden="true">
            {#each g.list as o, i (o.key)}
              <span
                class="dot"
                data-status={isHidden(o) ? 'hidden' : o.status}
                title={o.name}
                style:--i={i}
              ></span>
            {/each}
          </span>
        {/if}
        <span class="g-text">{groupText(g.list)}</span>
      </summary>
      {#if open || g.kind === focus || shown.has(g.kind)}
        {@const limit = shown.get(g.kind) ?? PAGE}
        <div class="rows">
          {#each g.rows.slice(0, limit) as r (r.object.key)}
            <ObjectRow
              object={r.object}
              {now}
              {showServer}
              depth={r.depth}
              selected={selected === r.object.key}
              {onOpen}
            />
          {/each}
          {#if g.rows.length > limit}
            <p class="page">
              <span>{limit} von {g.rows.length}</span>
              <button type="button" class="page-btn" onclick={() => shown.set(g.kind, limit + PAGE)}
                >{Math.min(PAGE, g.rows.length - limit)} weitere anzeigen</button
              >
            </p>
          {/if}
        </div>
      {/if}
    </details>
  {/each}
</div>

<style>
  .groups {
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
    overflow: hidden;
  }
  .group {
    --stripe: transparent;
    border-bottom: 1px solid var(--border);
  }
  .group:last-child {
    border-bottom: 0;
  }
  .group[data-worst='critical'] {
    --stripe: var(--danger);
  }
  .group[data-worst='warning'] {
    --stripe: var(--warning);
  }
  .group[data-worst='unknown'],
  .group[data-worst='stale'] {
    --stripe: var(--border-strong);
  }
  summary {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-4);
    box-shadow: inset 3px 0 0 var(--stripe);
    list-style: none;
    cursor: pointer;
    transition: background var(--dur-fast) var(--ease-standard);
  }
  summary::-webkit-details-marker {
    display: none;
  }
  summary:hover {
    background: var(--surface-hover);
  }
  summary:focus-visible {
    outline: none;
    box-shadow:
      inset 3px 0 0 var(--stripe),
      var(--ring-shadow);
  }
  .group[open] summary {
    background: var(--surface-raised);
  }
  .chev {
    display: inline-block;
    width: 12px;
    color: var(--text-subtle);
    transition: transform var(--dur-fast) var(--ease-standard);
  }
  .group[open] .chev {
    transform: rotate(90deg);
  }
  .g-name {
    width: 160px;
    font-weight: 600;
    color: var(--text-strong);
  }
  .g-name.calm {
    font-weight: 500;
    color: var(--text-muted);
  }
  .g-count {
    width: 28px;
    font-size: var(--text-sm);
    font-variant-numeric: tabular-nums;
    color: var(--text-subtle);
  }
  .dots {
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
    width: 168px;
  }
  .dots.bar {
    align-self: center;
  }
  .dot {
    width: 9px;
    height: 9px;
    border-radius: 2px;
    background: var(--success);
    opacity: 0.55;
    animation: pop 320ms var(--ease-out) backwards;
    animation-delay: calc(min(var(--i), 30) * 10ms + 120ms);
  }
  .dot[data-status='critical'] {
    background: var(--danger);
    opacity: 1;
  }
  .dot[data-status='warning'] {
    background: var(--warning);
    opacity: 1;
  }
  .dot[data-status='unknown'],
  .dot[data-status='stale'],
  .dot[data-status='not-collected'] {
    background: var(--text-subtle);
  }
  .dot[data-status='info'] {
    background: var(--info);
  }
  .dot[data-status='hidden'] {
    background: transparent;
    box-shadow: inset 0 0 0 1px var(--border-strong);
  }
  .g-text {
    flex: 1;
    font-size: var(--text-sm);
    color: var(--text-subtle);
  }
  .group[data-worst='critical'] .g-text {
    color: var(--danger);
  }
  .group[data-worst='warning'] .g-text {
    color: var(--warning);
  }
  .rows {
    border-top: 1px solid var(--border-faint);
  }
  .page {
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
    margin: 0;
    padding: var(--space-2) var(--space-4);
    font-size: var(--text-sm);
    color: var(--text-subtle);
  }
  .page-btn {
    padding: 0;
    border: 0;
    background: none;
    color: var(--accent);
    font: inherit;
    cursor: pointer;
  }
  .page-btn:hover {
    text-decoration: underline;
  }
  /* Phone: name and count on the first line, dots and words on the second. */
  @media (max-width: 760px) {
    summary {
      display: grid;
      grid-template-columns: 12px auto minmax(0, 1fr) auto;
      grid-template-areas:
        'chev name name count'
        '. dots text text';
      column-gap: var(--space-2);
      row-gap: 2px;
      padding: var(--space-2) var(--space-3);
    }
    .chev {
      grid-area: chev;
    }
    .g-name {
      grid-area: name;
      width: auto;
    }
    .g-count {
      grid-area: count;
      width: auto;
      text-align: right;
    }
    .dots {
      grid-area: dots;
      width: auto;
      max-width: 132px;
    }
    .dots.bar {
      width: 112px;
    }
    .g-text {
      grid-area: text;
      min-width: 0;
    }
  }
  .group[open] .rows {
    animation: reveal 260ms var(--ease-out);
  }
  /* The kind a Lagekarte cell asked for lights up once. */
  .group.flash summary {
    animation: flash 1.6s var(--ease-out) 250ms backwards;
  }
  @keyframes reveal {
    from {
      opacity: 0;
      transform: translateY(-6px);
    }
  }
  @keyframes pop {
    from {
      opacity: 0;
      transform: scale(0.3);
    }
  }
  @keyframes flash {
    from {
      background: color-mix(in srgb, var(--accent) 28%, transparent);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .dot,
    .group[open] .rows,
    .group.flash summary {
      animation: none;
    }
  }
  .rows :global(.row:last-child) {
    border-bottom: 0;
  }
</style>
