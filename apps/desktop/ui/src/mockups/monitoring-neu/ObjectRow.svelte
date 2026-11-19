<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // One object in a list: level 1 (badge, reason, since) and level 2 (at most four metrics). The
  // columns sit at the same place in every row, so a list reads like a table; the stripe on the
  // left carries the state for the eye, the badge for the reader.
  import Badge from '../../components/ui/Badge.svelte';
  import Dot from '../../components/ui/Dot.svelte';
  import Pill from '../../components/ui/Pill.svelte';
  import Meter from './Meter.svelte';
  import type { MonObject } from './model';
  import {
    MAX_METRICS,
    STATUS_LABEL,
    STATUS_TONE,
    badSinceText,
    exceptionText,
    formatValue,
    isHidden,
    sinceText,
    thresholdText,
  } from './grammar';
  import { ackText } from './views/lists';

  interface Props {
    object: MonObject;
    now: Date;
    /** Shows the server in the identity line (lists across servers). */
    showServer?: boolean;
    selected?: boolean;
    /** 1 for a module part under its instance. */
    depth?: number;
    /** Level 1 only: no identity, no metrics (the overview of all servers). */
    compact?: boolean;
    onOpen?: (key: string) => void;
  }

  let {
    object,
    now,
    showServer = false,
    selected = false,
    depth = 0,
    compact = false,
    onOpen,
  }: Props = $props();

  const hidden = $derived(isHidden(object));
  const identity = $derived(
    showServer
      ? [object.server, ...object.identity.filter((p) => p !== object.server)]
      : object.identity,
  );
  const exc = $derived(object.exception);
  const badSince = $derived(badSinceText(object, now));
</script>

<button
  type="button"
  class="row"
  class:is-hidden={hidden}
  class:selected
  class:part={depth > 0}
  class:compact
  data-key={object.key}
  data-status={hidden ? 'hidden' : object.status}
  onclick={() => onOpen?.(object.key)}
>
  <span class="badge">
    {#if hidden}
      <Badge>Ausgeblendet</Badge>
    {:else}
      <Badge tone={STATUS_TONE[object.status]} dot>{STATUS_LABEL[object.status]}</Badge>
    {/if}
  </span>
  <span class="name" title={object.name}>{object.name}</span>
  <span class="reason">{object.reason}</span>
  <span class="since"
    >{sinceText(object.since, now)}{#if badSince}<span class="bad-since">{` · ${badSince}`}</span
      >{/if}</span
  >
  {#if !compact}
    <span class="identity" title={identity.join(' · ')}>{identity.join(' · ')}</span>
  {/if}
  {#if !compact && object.metrics.length > 0}
    <span class="metrics">
      {#each object.metrics.slice(0, MAX_METRICS) as m (m.key)}
        <span class="metric" data-metric={m.key}>
          <span class="m-label">{m.label}</span>
          <Meter metric={m} />
          <span class="m-value">
            {#if m.status && m.status !== 'ok'}<Dot st={m.status} size={6} />{/if}
            {formatValue(m.value, m.unit)}
          </span>
          {#if m.threshold}<span class="m-threshold">({thresholdText(m.threshold)})</span>{/if}
          {#if m.note}<span class="m-note">{m.note}</span>{/if}
          {#if m.newData}<Pill tone="accent" title="Der Agent liefert diesen Wert noch nicht"
              >neue Agent-Daten</Pill
            >{/if}
        </span>
      {/each}
    </span>
  {/if}
  {#if exc}
    <span class="note exception">{hidden ? '' : 'Ausnahme: '}{exceptionText(exc)}</span>
  {/if}
  {#if object.ack}
    <span class="note ack" data-ack={object.key}>{ackText(object.ack)}</span>
  {/if}
</button>

<style>
  .row {
    --stripe: transparent;
    display: grid;
    grid-template-columns: 104px minmax(140px, 220px) minmax(0, 1fr) auto;
    column-gap: var(--space-4);
    row-gap: 2px;
    align-items: baseline;
    width: 100%;
    padding: var(--space-2) var(--space-4);
    border: 0;
    border-bottom: 1px solid var(--border-faint);
    background: transparent;
    box-shadow: inset 3px 0 0 var(--stripe);
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .row[data-status='critical'] {
    --stripe: var(--danger);
  }
  .row[data-status='warning'] {
    --stripe: var(--warning);
  }
  .row[data-status='unknown'],
  .row[data-status='stale'] {
    --stripe: var(--border-strong);
  }
  .row:hover {
    background: var(--surface-hover);
  }
  .row.selected {
    background: var(--surface-active);
  }
  .row.is-hidden {
    opacity: 0.6;
  }
  .badge {
    grid-column: 1;
  }
  .name {
    grid-column: 2;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 600;
    color: var(--text-strong);
  }
  .reason {
    grid-column: 3;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text);
  }
  .since {
    grid-column: 4;
    color: var(--text-subtle);
    font-size: var(--text-sm);
    white-space: nowrap;
    text-align: right;
  }
  .identity {
    grid-column: 2;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--text-xs);
    color: var(--text-subtle);
  }
  .part .name,
  .part .identity {
    padding-left: var(--space-5);
  }
  .part .name::before {
    content: '↳';
    margin: 0 var(--space-2) 0 calc(-1 * var(--space-5));
    font-weight: 400;
    color: var(--text-subtle);
  }
  .metrics {
    grid-column: 3 / 5;
    display: flex;
    flex-wrap: wrap;
    gap: 2px var(--space-5);
    font-size: var(--text-sm);
  }
  .metric {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
  }
  .m-label {
    color: var(--text-subtle);
  }
  .m-value {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-family: var(--font-mono);
    color: var(--text-strong);
  }
  .m-threshold,
  .m-note {
    font-size: var(--text-xs);
    color: var(--text-subtle);
  }
  .note {
    grid-column: 3 / 5;
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .exception {
    font-style: italic;
  }
  /* Phone: state and age on top, then name, reason and the rest under each other. */
  @media (max-width: 760px) {
    .row {
      grid-template-columns: minmax(0, 1fr) auto;
      padding: var(--space-2) var(--space-3);
    }
    .badge {
      grid-column: 1;
      grid-row: 1;
    }
    .since {
      grid-column: 2;
      grid-row: 1;
    }
    .name,
    .reason,
    .identity,
    .metrics,
    .note {
      grid-column: 1 / -1;
    }
    .reason {
      white-space: normal;
    }
    /* One metric per line; its threshold and note wrap below as a whole, never word by word. */
    .metrics {
      flex-direction: column;
      gap: 4px;
    }
    .metric {
      flex-wrap: wrap;
      row-gap: 0;
    }
    .m-threshold,
    .m-note {
      white-space: nowrap;
    }
  }
</style>
