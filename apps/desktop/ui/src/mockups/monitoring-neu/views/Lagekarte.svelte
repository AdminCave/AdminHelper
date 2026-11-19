<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // The Lagekarte of "Alle Server" (Kevin 2026-11-18: clearer at a glance): every server a row,
  // worst first as in the server list, every kind a column, in four groups. A cell shows the worst
  // state of the server's objects of that kind: a full square for a problem (a number counts
  // several), a small one when all is well, an outline when nothing is collected or everything is
  // hidden, a point when the server has no such object. Hover or focus draws a crosshair and lists
  // the objects; a click opens the one object, or the server with that kind open. A large fleet
  // (Kevin 2026-11-19) gets a carpet above the map, one square per server, and the map shows the
  // worst servers until asked for all.
  import { fade } from 'svelte/transition';
  import { prefersReducedMotion } from 'svelte/motion';
  import Dot from '../../../components/ui/Dot.svelte';
  import type { Kind, MonObject, Status } from '../model';
  import { KIND_LABEL, STATUS_LABEL, isHidden, sortObjects } from '../grammar';
  import { isProblem } from './lists';
  import { needsLook, serverSummaries, type ServerSummary } from './servers';

  interface Props {
    objects: MonObject[];
    now: Date;
    /** The state the legend filters to; cells without it fade. */
    filter: Status | '';
    onOpen: (key: string) => void;
    onServer: (server: string, kind?: Kind) => void;
  }

  let { objects, now, filter, onOpen, onServer }: Props = $props();

  const GROUPS: { label: string; kinds: Kind[] }[] = [
    { label: 'System', kinds: ['host', 'cpu', 'memory', 'updates', 'reboot', 'clock', 'sensor'] },
    { label: 'Speicher', kinds: ['disk', 'mount', 'pool', 'guest-backup', 'backup-job'] },
    { label: 'Dienste', kinds: ['service', 'container', 'compose-project', 'module'] },
    { label: 'Netz', kinds: ['endpoint', 'certificate', 'domain'] },
  ];
  /** Objects the tooltip lists before "+n weitere". */
  const TIP_LINES = 4;
  /** A critical object this young pulses: it is new. */
  const FRESH_MS = 60 * 60 * 1000;
  /** Rows near the top show the tooltip below the cell. */
  const TIP_BELOW_ROWS = 3;
  /** Tooltip width; it stays inside the map. */
  const TIP_W = 320;
  /** From this many servers on, the carpet sums up the fleet and the map shows ROW_CAP rows. */
  const FLEET_MIN = 40;
  const ROW_CAP = 20;

  type CellState = Status | 'hidden' | 'none';
  interface Cell {
    list: MonObject[];
    state: CellState;
    problems: number;
    fresh: boolean;
  }
  const NONE: Cell = { list: [], state: 'none', problems: 0, fresh: false };

  const columns = $derived.by(() => {
    const present = new Set(objects.map((o) => o.kind));
    const known = new Set(GROUPS.flatMap((g) => g.kinds));
    return [...GROUPS, { label: 'Weitere', kinds: [...present].filter((k) => !known.has(k)) }]
      .map((g) => ({ label: g.label, kinds: g.kinds.filter((k) => present.has(k)) }))
      .filter((g) => g.kinds.length > 0);
  });
  const order = $derived(new Map(columns.flatMap((g) => g.kinds).map((k, i) => [k, i])));
  const summaries = $derived(serverSummaries(objects));
  const fleet = $derived(summaries.length >= FLEET_MIN);
  let all = $state(false);
  const rows = $derived(fleet && !all ? summaries.slice(0, ROW_CAP) : summaries);
  const troubled = $derived(summaries.filter(needsLook));
  const restTroubled = $derived(troubled.length - rows.filter(needsLook).length);
  const restQuiet = $derived(summaries.length - rows.length - restTroubled);
  // The carpet names the server under the pointer instead of a tooltip per square.
  let peek = $state<ServerSummary | undefined>(undefined);
  const cells = $derived.by(() => {
    const by: Record<string, MonObject[]> = {};
    for (const o of objects) (by[`${o.server}|${o.kind}`] ??= []).push(o);
    return new Map(Object.entries(by).map(([id, own]) => [id, cellOf(sortObjects(own))]));
  });

  function cellOf(list: MonObject[]): Cell {
    const rated = list.filter((o) => !isHidden(o));
    const reported = rated.filter((o) => o.status !== 'not-collected');
    return {
      list,
      state: reported.length ? reported[0].status : rated.length ? 'not-collected' : 'hidden',
      problems: list.filter(isProblem).length,
      fresh: rated.some(
        (o) => o.status === 'critical' && now.getTime() - new Date(o.since).getTime() < FRESH_MS,
      ),
    };
  }

  function cell(server: string, kind: Kind): Cell {
    return cells.get(`${server}|${kind}`) ?? NONE;
  }

  function matches(c: Cell): boolean {
    return !filter || c.list.some((o) => !isHidden(o) && o.status === filter);
  }

  function rowMatches(server: string): boolean {
    return (
      !filter ||
      columns.some((g) =>
        g.kinds.some((k) => matches(cell(server, k)) && cell(server, k).list.length > 0),
      )
    );
  }

  function tally(s: ServerSummary): string {
    if (s.worst === 'stale') return 'meldet sich nicht';
    const parts = [
      s.counts.critical ? `${s.counts.critical} kritisch` : '',
      s.counts.warning ? `${s.counts.warning} Warnung` : '',
      s.counts.unknown ? `${s.counts.unknown} unbekannt` : '',
    ].filter(Boolean);
    return parts.length ? parts.join(' · ') : 'alles in Ordnung';
  }

  function describe(server: string, kind: Kind, c: Cell): string {
    if (c.state === 'none') return `${server}, ${KIND_LABEL[kind]}: keine Objekte`;
    const state = c.state === 'hidden' ? 'ausgeblendet' : STATUS_LABEL[c.state];
    const n = c.list.length === 1 ? '1 Objekt' : `${c.list.length} Objekte`;
    return `${server}, ${KIND_LABEL[kind]}: ${state}, ${n}`;
  }

  function open(server: string, kind: Kind): void {
    const c = cell(server, kind);
    if (c.list.length === 1) onOpen(c.list[0].key);
    else onServer(server, kind);
  }

  // Crosshair and tooltip follow the pointer and the focus over the cells; leaving a cell for a
  // gap keeps them, leaving the map hides them.
  let grid = $state<HTMLElement | undefined>(undefined);
  let hover = $state<
    | {
        server: string;
        kind: Kind;
        row: number;
        x: number;
        y: number;
        w: number;
        h: number;
        rowY: number;
        rowH: number;
        gw: number;
      }
    | undefined
  >(undefined);
  const tip = $derived(hover ? cell(hover.server, hover.kind) : NONE);

  function track(e: Event): void {
    const el = (e.target as HTMLElement).closest<HTMLElement>('[data-cell]');
    const row = el?.closest<HTMLElement>('[data-row]');
    if (!el || !row || !grid) return;
    const g = grid.getBoundingClientRect();
    const c = el.getBoundingClientRect();
    const r = row.getBoundingClientRect();
    hover = {
      server: el.dataset.server ?? '',
      kind: el.dataset.kind as Kind,
      row: Number(row.dataset.row),
      x: c.left - g.left,
      y: c.top - g.top,
      w: c.width,
      h: c.height,
      rowY: r.top - g.top,
      rowH: r.height,
      gw: g.width,
    };
  }

  function leave(e: FocusEvent | PointerEvent): void {
    const next = (e as FocusEvent).relatedTarget as Node | null;
    if (e.type === 'focusout' && next && grid?.contains(next)) return;
    hover = undefined;
  }
</script>

{#if fleet}
  <div class="lk-fleet-box">
    <p class="lk-fleet-head" aria-live="polite">
      {#if peek}
        <Dot st={peek.worst} size={7} label={STATUS_LABEL[peek.worst]} />
        <strong>{peek.server}</strong>
        <span>{tally(peek)}</span>
      {:else}
        <strong>{summaries.length} Server</strong>
        <span>{troubled.length} mit Problemen · ein Feld je Server, schlimmste zuerst</span>
      {/if}
    </p>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="lk-fleet" onpointerleave={() => (peek = undefined)}>
      {#each summaries as s, i (s.server)}
        <button
          type="button"
          class="lk-f"
          class:off={!rowMatches(s.server)}
          data-state={s.worst}
          data-server={s.server}
          aria-label="{s.server}: {tally(s)}"
          style:--i={i}
          onpointerenter={() => (peek = s)}
          onfocus={() => (peek = s)}
          onblur={() => (peek = undefined)}
          onclick={() => onServer(s.server)}
        ></button>
      {/each}
    </div>
  </div>
{/if}

<div class="lk-scroll">
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="lk-grid"
    class:hovering={hover !== undefined}
    bind:this={grid}
    onpointerover={track}
    onfocusin={track}
    onpointerleave={leave}
    onfocusout={leave}
  >
    <span
      class="lk-band lk-band-row"
      style:transform="translateY({hover?.rowY ?? 0}px)"
      style:height="{hover?.rowH ?? 0}px"
    ></span>
    <span
      class="lk-band lk-band-col"
      style:transform="translateX({(hover?.x ?? 0) - 3}px)"
      style:width="{(hover?.w ?? 0) + 6}px"
    ></span>

    <div class="lk-head" aria-hidden="true">
      <span class="lk-corner"></span>
      {#each columns as g (g.label)}
        <span class="lk-ghead">
          <span class="lk-glabel">{g.label}</span>
          <span class="lk-kinds">
            {#each g.kinds as k (k)}
              <span class="lk-kind" class:hot={hover?.kind === k}><span>{KIND_LABEL[k]}</span></span
              >
            {/each}
          </span>
        </span>
      {/each}
    </div>

    {#each rows as s, r (s.server)}
      <div
        class="lk-row"
        class:hot={hover?.server === s.server}
        class:off={!rowMatches(s.server)}
        data-row={r}
      >
        <button
          type="button"
          class="lk-server"
          data-server={s.server}
          title={s.identity.join(' · ') || 'ohne Agent'}
          onclick={() => onServer(s.server)}
        >
          <Dot st={s.worst} size={7} label={STATUS_LABEL[s.worst]} />
          <span class="lk-sname">{s.server}</span>
        </button>
        {#each columns as g (g.label)}
          <span class="lk-cells">
            {#each g.kinds as k (k)}
              {@const c = cell(s.server, k)}
              {#if c.state === 'none'}
                <span
                  class="lk-cell"
                  data-cell
                  data-server={s.server}
                  data-kind={k}
                  data-state="none"
                  class:off={filter !== ''}
                  style:--r={r}
                  style:--c={order.get(k) ?? 0}
                >
                  <span class="lk-sq"></span>
                </span>
              {:else}
                <button
                  type="button"
                  class="lk-cell"
                  data-cell
                  data-server={s.server}
                  data-kind={k}
                  data-state={c.state}
                  class:off={!matches(c)}
                  class:fresh={c.fresh}
                  style:--r={r}
                  style:--c={order.get(k) ?? 0}
                  aria-label={describe(s.server, k, c)}
                  onclick={() => open(s.server, k)}
                >
                  <span class="lk-sq">{c.problems > 1 ? c.problems : ''}</span>
                </button>
              {/if}
            {/each}
          </span>
        {/each}
      </div>
    {/each}

    {#if hover && tip.state !== 'none'}
      <div
        class="lk-tip"
        class:below={hover.row < TIP_BELOW_ROWS}
        role="tooltip"
        style:left="{Math.min(Math.max(hover.x + hover.w / 2, TIP_W / 2), hover.gw - TIP_W / 2)}px"
        style:top="{hover.row < TIP_BELOW_ROWS ? hover.y + hover.h + 10 : hover.y - 10}px"
        transition:fade={{ duration: prefersReducedMotion.current ? 0 : 120 }}
      >
        <p class="lk-tip-head">
          <strong>{hover.server}</strong>
          <span>{KIND_LABEL[hover.kind]} · {tip.list.length}</span>
        </p>
        <ul>
          {#each tip.list.slice(0, TIP_LINES) as o (o.key)}
            <li>
              <Dot st={isHidden(o) ? 'hidden' : o.status} size={7} />
              <span class="lk-tname">{o.name}</span>
              <span class="lk-treason">{isHidden(o) ? 'ausgeblendet' : o.reason}</span>
            </li>
          {/each}
        </ul>
        {#if tip.list.length > TIP_LINES}
          <p class="lk-tip-more">+{tip.list.length - TIP_LINES} weitere</p>
        {/if}
        <p class="lk-tip-hint">
          {tip.list.length === 1 ? 'Klick öffnet die Details' : 'Klick öffnet den Server'}
        </p>
      </div>
    {/if}
  </div>
</div>

{#if fleet}
  <p class="lk-more">
    {#if all}
      <span>Alle {summaries.length} Server</span>
      <button type="button" class="lk-link" onclick={() => (all = false)}
        >nur die {ROW_CAP} schlimmsten zeigen</button
      >
    {:else}
      <span
        >+{summaries.length - rows.length} weitere{#if restTroubled}, davon {restTroubled} mit Problemen{/if}{#if restQuiet}{restTroubled
            ? ' und'
            : ','}
          {restQuiet} ohne{/if}</span
      >
      <button type="button" class="lk-link" onclick={() => (all = true)}>alle zeigen</button>
    {/if}
  </p>
{/if}

<p class="lk-key">
  <span><span class="lk-demo" data-state="critical"></span>Problem (Zahl: mehrere)</span>
  <span><span class="lk-demo" data-state="ok"></span>in Ordnung</span>
  <span><span class="lk-demo" data-state="info"></span>Hinweis</span>
  <span><span class="lk-demo" data-state="not-collected"></span>nicht erhoben</span>
  <span><span class="lk-demo" data-state="hidden"></span>ausgeblendet</span>
  <span><span class="lk-demo" data-state="none"></span>keine Objekte</span>
</p>

<style>
  .lk-grid {
    --cell: 20px;
    --gap: 5px;
    position: relative;
    display: flex;
    flex-direction: column;
    padding-right: 48px;
  }

  /* The crosshair: two bands that glide to the hovered row and column. */
  .lk-band {
    position: absolute;
    z-index: 0;
    border-radius: var(--radius-md);
    background: var(--surface-hover);
    opacity: 0;
    pointer-events: none;
    transition:
      transform var(--dur-base) var(--ease-out),
      height var(--dur-base) var(--ease-out),
      width var(--dur-base) var(--ease-out),
      opacity var(--dur-fast) var(--ease-standard);
  }
  .lk-band-row {
    top: 0;
    left: -8px;
    right: 40px;
  }
  .lk-band-col {
    top: 18px;
    bottom: 0;
    left: 0;
  }
  .hovering .lk-band {
    opacity: 1;
  }

  .lk-head,
  .lk-row {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: flex-end;
    gap: 14px;
  }
  .lk-corner,
  .lk-server {
    flex: 0 0 132px;
  }
  .lk-ghead {
    display: flex;
    flex-direction: column;
  }
  .lk-glabel {
    margin-bottom: 4px;
    padding-bottom: 3px;
    border-bottom: 1px solid var(--border);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--text-subtle);
  }
  .lk-kinds,
  .lk-cells {
    display: flex;
    gap: var(--gap);
  }
  .lk-kind {
    position: relative;
    width: var(--cell);
    height: 78px;
  }
  .lk-kind > span {
    position: absolute;
    bottom: 4px;
    left: 9px;
    transform: rotate(-52deg);
    transform-origin: 0 100%;
    white-space: nowrap;
    font-size: var(--text-xs);
    color: var(--text-muted);
    transition: color var(--dur-fast) var(--ease-standard);
  }
  .lk-kind.hot > span {
    color: var(--text-strong);
    font-weight: 600;
  }

  .lk-row {
    align-items: center;
    height: 24px;
  }
  .lk-server {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
    padding: 0;
    border: 0;
    background: none;
    color: var(--text);
    font: inherit;
    font-size: var(--text-sm);
    text-align: left;
    cursor: pointer;
    transition: opacity var(--dur-base) var(--ease-standard);
  }
  .lk-sname {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .lk-server:hover .lk-sname,
  .lk-row.hot .lk-sname {
    color: var(--text-strong);
    font-weight: 600;
  }
  .lk-server:focus-visible {
    outline: none;
    border-radius: var(--radius-md);
    box-shadow: var(--ring-shadow);
  }
  .lk-row.off .lk-server {
    opacity: 0.35;
  }

  .lk-cell {
    display: grid;
    place-items: center;
    width: var(--cell);
    height: var(--cell);
    padding: 0;
    border: 0;
    border-radius: 5px;
    background: none;
    transition: opacity var(--dur-base) var(--ease-standard);
  }
  button.lk-cell {
    cursor: pointer;
  }
  button.lk-cell:focus-visible {
    outline: none;
    box-shadow: var(--ring-shadow);
  }
  .lk-cell.off {
    opacity: 0.12;
  }

  /* The square: size says problem or not, colour says which state. */
  .lk-sq,
  .lk-demo {
    position: relative;
    display: grid;
    place-items: center;
    width: 8px;
    height: 8px;
    border-radius: 2px;
    background: var(--success);
    font-size: 10px;
    font-weight: 700;
    line-height: 1;
    font-variant-numeric: tabular-nums;
    color: var(--text-inverse);
  }
  .lk-sq {
    animation: lk-in 460ms var(--ease-out) backwards;
    animation-delay: calc((min(var(--r), 24) + var(--c)) * 16ms);
    transition: transform var(--dur-fast) var(--ease-out);
  }
  button.lk-cell:hover .lk-sq {
    transform: scale(1.18);
  }
  [data-state='ok'] > .lk-sq,
  .lk-demo[data-state='ok'] {
    opacity: 0.7;
  }
  [data-state='critical'] > .lk-sq,
  [data-state='warning'] > .lk-sq,
  [data-state='unknown'] > .lk-sq,
  .lk-demo[data-state='critical'] {
    width: 16px;
    height: 16px;
    border-radius: 4px;
  }
  [data-state='critical'] > .lk-sq,
  .lk-demo[data-state='critical'] {
    background: var(--danger);
  }
  [data-state='warning'] > .lk-sq {
    background: var(--warning);
  }
  [data-state='unknown'] > .lk-sq {
    background: var(--text-subtle);
  }
  [data-state='stale'] > .lk-sq {
    width: 12px;
    height: 12px;
    border-radius: 3px;
    background: var(--text-subtle);
  }
  [data-state='info'] > .lk-sq,
  .lk-demo[data-state='info'] {
    width: 10px;
    height: 10px;
    background: var(--info);
  }
  [data-state='not-collected'] > .lk-sq,
  .lk-demo[data-state='not-collected'] {
    background: transparent;
    box-shadow: inset 0 0 0 1.5px var(--border-strong);
  }
  [data-state='hidden'] > .lk-sq,
  .lk-demo[data-state='hidden'] {
    background: transparent;
    outline: 1.5px dashed var(--border-strong);
    outline-offset: -1.5px;
  }
  [data-state='none'] > .lk-sq,
  .lk-demo[data-state='none'] {
    width: 3px;
    height: 3px;
    border-radius: 50%;
    background: var(--border-strong);
  }

  /* A new critical problem keeps calling. */
  .lk-cell.fresh .lk-sq::after {
    content: '';
    position: absolute;
    inset: -3px;
    border: 2px solid var(--danger);
    border-radius: 6px;
    animation: lk-ping 1.8s var(--ease-out) infinite;
  }

  .lk-tip {
    position: absolute;
    z-index: 3;
    width: 320px;
    padding: var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface-raised);
    box-shadow: var(--shadow-pop);
    transform: translate(-50%, -100%);
    pointer-events: none;
    transition:
      left var(--dur-base) var(--ease-out),
      top var(--dur-base) var(--ease-out);
  }
  .lk-tip.below {
    transform: translate(-50%, 0);
  }
  .lk-tip p {
    margin: 0;
  }
  .lk-tip-head {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    margin-bottom: var(--space-2) !important;
    font-size: var(--text-sm);
    color: var(--text-strong);
  }
  .lk-tip-head span {
    color: var(--text-subtle);
  }
  .lk-tip ul {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .lk-tip li {
    display: grid;
    grid-template-columns: 8px minmax(0, 1fr);
    grid-template-areas:
      'dot name'
      '. reason';
    column-gap: var(--space-2);
    align-items: center;
  }
  .lk-tname {
    grid-area: name;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-strong);
  }
  .lk-treason {
    grid-area: reason;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--text-xs);
    color: var(--text-muted);
  }
  .lk-tip-more,
  .lk-tip-hint {
    margin-top: var(--space-2) !important;
    font-size: var(--text-xs);
    color: var(--text-subtle);
  }
  .lk-tip-hint {
    padding-top: var(--space-2);
    border-top: 1px solid var(--border-faint);
  }

  /* The carpet: the whole fleet at a glance, one square per server. */
  .lk-fleet-box {
    margin-bottom: var(--space-4);
    padding-bottom: var(--space-4);
    border-bottom: 1px solid var(--border-faint);
  }
  .lk-fleet-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 20px;
    margin: 0 0 var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-strong);
  }
  .lk-fleet-head span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-subtle);
  }
  .lk-fleet {
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
    /* Wraps at the width of the map instead of widening it. */
    contain: inline-size;
  }
  .lk-f {
    width: 11px;
    height: 11px;
    padding: 0;
    border: 0;
    border-radius: 2px;
    background: var(--success);
    opacity: 0.55;
    cursor: pointer;
    animation: lk-in 360ms var(--ease-out) backwards;
    animation-delay: calc(min(var(--i), 160) * 3ms + 80ms);
    transition:
      transform var(--dur-fast) var(--ease-out),
      opacity var(--dur-base) var(--ease-standard);
  }
  .lk-f[data-state='critical'] {
    background: var(--danger);
    opacity: 1;
  }
  .lk-f[data-state='warning'] {
    background: var(--warning);
    opacity: 1;
  }
  .lk-f[data-state='unknown'],
  .lk-f[data-state='stale'] {
    background: var(--text-subtle);
    opacity: 1;
  }
  .lk-f[data-state='info'] {
    background: var(--info);
    opacity: 0.8;
  }
  .lk-f:hover,
  .lk-f:focus-visible {
    outline: none;
    transform: scale(1.45);
    box-shadow: 0 0 0 2px var(--surface);
  }
  .lk-f.off {
    opacity: 0.12;
  }

  .lk-scroll {
    min-width: 0;
  }
  .lk-more {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-1) var(--space-3);
    margin: var(--space-3) 0 0;
    padding-left: 146px;
    font-size: var(--text-sm);
    color: var(--text-subtle);
  }
  .lk-link {
    padding: 0;
    border: 0;
    background: none;
    color: var(--accent);
    font: inherit;
    cursor: pointer;
  }
  .lk-link:hover {
    text-decoration: underline;
  }

  .lk-key {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-4);
    margin: var(--space-4) 0 0;
    font-size: var(--text-xs);
    color: var(--text-subtle);
  }
  .lk-key > span {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .lk-demo[data-state='critical'] {
    width: 12px;
    height: 12px;
    border-radius: 3px;
  }

  @keyframes lk-in {
    from {
      opacity: 0;
      transform: scale(0.2);
    }
  }
  @keyframes lk-ping {
    from {
      opacity: 0.9;
      transform: scale(0.85);
    }
    to {
      opacity: 0;
      transform: scale(1.7);
    }
  }
  /* Phone: the map scrolls sideways, the server names stay put. */
  @media (max-width: 760px) {
    .lk-scroll {
      overflow-x: auto;
    }
    .lk-grid {
      width: max-content;
      padding-right: var(--space-6);
    }
    .lk-head,
    .lk-row {
      gap: 10px;
    }
    .lk-corner,
    .lk-server {
      flex-basis: 92px;
    }
    .lk-server {
      position: sticky;
      left: 0;
      z-index: 2;
      align-self: stretch;
      background: var(--surface);
    }
    .lk-band {
      display: none;
    }
    .lk-more {
      padding-left: 0;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .lk-sq,
    .lk-f,
    .lk-cell.fresh .lk-sq::after {
      animation: none;
    }
  }
</style>
