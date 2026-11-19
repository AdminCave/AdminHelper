<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Journal excerpt of a service or the kernel: newest last, priority as a dot, the source unit
  // and where the full log is.
  import Dot from '../../../components/ui/Dot.svelte';
  import type { LogDetail, LogLine, Status } from '../model';

  interface Props {
    detail: LogDetail;
  }

  let { detail }: Props = $props();

  const DOT: Record<LogLine['priority'], Status | null> = {
    err: 'critical',
    warning: 'warning',
    notice: 'info',
    info: null,
  };

  function time(iso: string): string {
    return new Date(iso).toLocaleTimeString('de-DE', { timeZone: 'UTC' });
  }
</script>

<ol class="log">
  {#each detail.lines as l, i (i)}
    {@const st = DOT[l.priority]}
    <li data-priority={l.priority}>
      <span class="dot"
        >{#if st}<Dot {st} size={6} />{/if}</span
      >
      <span class="at">{time(l.at)}</span>
      <span class="src">{l.source}</span>
      <span class="text">{l.text}</span>
    </li>
  {/each}
</ol>
{#if detail.more}
  <p class="more">Mehr Log: <code>{detail.more}</code></p>
{/if}

<style>
  .log {
    margin: 0;
    padding: var(--space-2);
    list-style: none;
    border: 1px solid var(--border-faint);
    border-radius: var(--radius-md);
    background: var(--surface);
    font-family: var(--font-mono);
    font-size: var(--text-xs);
  }
  li {
    display: flex;
    gap: var(--space-2);
    align-items: baseline;
    padding: 1px 0;
  }
  .dot {
    flex: none;
    width: 8px;
  }
  .at,
  .src {
    flex: none;
    color: var(--text-subtle);
  }
  .text {
    min-width: 0;
    overflow-wrap: anywhere;
  }
  li[data-priority='err'] .text {
    color: var(--text-strong);
  }
  .more {
    margin: var(--space-2) 0 0;
    font-size: var(--text-sm);
    color: var(--text-subtle);
  }
</style>
