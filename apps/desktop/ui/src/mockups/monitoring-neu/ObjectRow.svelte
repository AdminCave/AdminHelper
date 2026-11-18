<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // One object in a list: level 1 (badge, reason, since) and level 2 (at most four metrics).
  import Badge from '../../components/ui/Badge.svelte';
  import Dot from '../../components/ui/Dot.svelte';
  import Pill from '../../components/ui/Pill.svelte';
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

  interface Props {
    object: MonObject;
    now: Date;
    /** Shows the server in the identity line (lists across servers). */
    showServer?: boolean;
    selected?: boolean;
    onOpen?: (key: string) => void;
  }

  let { object, now, showServer = false, selected = false, onOpen }: Props = $props();

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
  class:hidden
  class:selected
  data-key={object.key}
  data-status={object.status}
  onclick={() => onOpen?.(object.key)}
>
  <span class="l1">
    <span class="badge">
      {#if hidden}
        <Badge>Ausgeblendet</Badge>
      {:else}
        <Badge tone={STATUS_TONE[object.status]} dot>{STATUS_LABEL[object.status]}</Badge>
      {/if}
    </span>
    <span class="name">{object.name}</span>
    <span class="reason">{object.reason}</span>
    <span class="since"
      >{sinceText(object.since, now)}{#if badSince}<span class="bad-since">{` · ${badSince}`}</span
        >{/if}</span
    >
  </span>
  <span class="identity">{identity.join(' · ')}</span>
  {#if object.metrics.length > 0}
    <span class="metrics">
      {#each object.metrics.slice(0, MAX_METRICS) as m (m.key)}
        <span class="metric" data-metric={m.key}>
          <span class="m-label">{m.label}</span>
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
    <span class="exception">{hidden ? '' : 'Ausnahme: '}{exceptionText(exc)}</span>
  {/if}
</button>

<style>
  .row {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    width: 100%;
    padding: var(--space-3) var(--space-4);
    border: 0;
    border-bottom: 1px solid var(--border-faint);
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .row:hover {
    background: var(--surface-hover);
  }
  .row.selected {
    background: var(--surface-active);
  }
  .row.hidden {
    opacity: 0.6;
  }
  .l1 {
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
    min-width: 0;
  }
  .badge {
    flex: none;
    width: 112px;
  }
  .name {
    flex: none;
    font-weight: 600;
    color: var(--text-strong);
  }
  .reason {
    flex: 1;
    min-width: 0;
    color: var(--text-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .since {
    flex: none;
    color: var(--text-subtle);
    font-size: var(--text-sm);
  }
  .identity,
  .metrics,
  .exception {
    padding-left: calc(112px + var(--space-3));
    font-size: var(--text-sm);
  }
  .identity {
    color: var(--text-subtle);
  }
  .metrics {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-5);
  }
  .metric {
    display: inline-flex;
    align-items: baseline;
    gap: var(--space-1);
  }
  .m-label {
    color: var(--text-subtle);
  }
  .m-value {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-family: var(--font-mono);
    color: var(--text);
  }
  .m-threshold,
  .m-note {
    color: var(--text-subtle);
  }
  .exception {
    color: var(--text-subtle);
    font-style: italic;
  }
</style>
