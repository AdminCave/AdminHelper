<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Level 3: the drawer of one object — every metric, attribute and kind-specific block, the
  // status history, the rules with their thresholds, the exception and the raw data.
  import X from '@lucide/svelte/icons/x';
  import Badge from '../../components/ui/Badge.svelte';
  import Button from '../../components/ui/Button.svelte';
  import CodeBlock from '../../components/ui/CodeBlock.svelte';
  import Dot from '../../components/ui/Dot.svelte';
  import IconButton from '../../components/ui/IconButton.svelte';
  import MetaList from '../../components/ui/MetaList.svelte';
  import Pill from '../../components/ui/Pill.svelte';
  import type { MonObject } from './model';
  import { ackText } from './views/lists';
  import BackupList from './details/BackupList.svelte';
  import LogLines from './details/LogLines.svelte';
  import ProcessTable from './details/ProcessTable.svelte';
  import SmartAttributes from './details/SmartAttributes.svelte';
  import TrendChart from './details/TrendChart.svelte';
  import VdevTree from './details/VdevTree.svelte';
  import {
    KIND_LABEL,
    STATUS_LABEL,
    STATUS_TONE,
    dateText,
    exceptionText,
    formatValue,
    isHidden,
    badSinceText,
    sinceText,
    thresholdText,
  } from './grammar';

  interface Props {
    object: MonObject;
    now: Date;
    onClose: () => void;
    onException?: (key: string) => void;
  }

  let { object, now, onClose, onException }: Props = $props();

  const hidden = $derived(isHidden(object));
  const badSince = $derived(badSinceText(object, now));

  function onKey(e: KeyboardEvent): void {
    if (e.key === 'Escape') onClose();
  }
</script>

<svelte:window onkeydown={onKey} />

<aside class="drawer" aria-label="Details {object.name}" data-key={object.key}>
  <header class="head">
    <div class="title">
      {#if hidden}
        <Badge>Ausgeblendet</Badge>
      {:else}
        <Badge tone={STATUS_TONE[object.status]} dot>{STATUS_LABEL[object.status]}</Badge>
      {/if}
      <h2>{object.name}</h2>
      <IconButton icon={X} label="Schließen" size="sm" onclick={onClose} />
    </div>
    <p class="identity">{KIND_LABEL[object.kind]} · {object.identity.join(' · ')}</p>
    <p class="reason">
      {object.reason}
      <span class="since"
        >{sinceText(object.since, now)}{#if badSince}<span class="bad-since"
            >{` · ${badSince}`}</span
          >{/if}</span
      >
    </p>
    {#if object.ack}
      <p class="ack" data-ack={object.key}>{ackText(object.ack)}</p>
    {/if}
    <p class="key">Schlüssel <code>{object.key}</code></p>
  </header>

  {#if object.metrics.length > 0}
    <section>
      <h3>Kennzahlen</h3>
      <table class="tbl">
        <tbody>
          {#each object.metrics as m (m.key)}
            <tr>
              <th scope="row">{m.label}</th>
              <td class="mono">
                {#if m.status}<Dot st={m.status} size={6} />{/if}
                {formatValue(m.value, m.unit)}
              </td>
              <td class="muted">
                {m.threshold ? thresholdText(m.threshold) : 'ohne Schwelle'}
                {#if m.note}· {m.note}{/if}
                {#if m.newData}<Pill tone="accent">neue Agent-Daten</Pill>{/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </section>
  {/if}

  {#each object.details ?? [] as d, i (i)}
    <section>
      <h3>{d.title}</h3>
      {#if d.type === 'note'}
        <p class="note">{d.text}</p>
      {:else if d.type === 'smart'}
        <SmartAttributes detail={d} />
      {:else if d.type === 'vdev'}
        <VdevTree detail={d} />
      {:else if d.type === 'backups'}
        <BackupList detail={d} />
      {:else if d.type === 'trend'}
        <TrendChart detail={d} />
      {:else if d.type === 'log'}
        <LogLines detail={d} />
      {:else if d.type === 'processes'}
        <ProcessTable detail={d} />
      {/if}
    </section>
  {/each}

  {#if object.attributes?.length}
    <section>
      <h3>Alle Attribute</h3>
      <MetaList rows={object.attributes} />
    </section>
  {/if}

  {#if object.history?.length}
    <section>
      <h3>Verlauf</h3>
      <ol class="history">
        {#each object.history as h, i (i)}
          <li>
            <Dot st={h.status} size={8} />
            <span class="mono muted">{dateText(h.at)}</span>
            <span>{h.text}</span>
          </li>
        {/each}
      </ol>
    </section>
  {/if}

  {#if object.rules?.length}
    <section>
      <h3>Regeln</h3>
      <table class="tbl">
        <tbody>
          {#each object.rules as r (r.key)}
            <tr class:off={!r.enabled}>
              <td>
                {#if r.firing}<Dot st={r.level} size={8} />{/if}
                {r.text}
              </td>
              <td class="muted">{r.level === 'critical' ? 'kritisch' : 'Warnung'}</td>
              <td class="muted">{r.source}{r.enabled ? '' : ' · aus'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </section>
  {/if}

  <section>
    <h3>Ausnahme</h3>
    {#if object.exception}
      <p class="note">{exceptionText(object.exception)}</p>
      <p class="muted small">angelegt {dateText(object.exception.at)}</p>
    {:else}
      <p class="muted small">Keine Ausnahme.</p>
    {/if}
    {#if onException}
      <div class="actions">
        <Button size="sm" variant="secondary" onclick={() => onException?.(object.key)}>
          {object.exception ? 'Ausnahme ändern …' : 'Ausnahme anlegen …'}
        </Button>
      </div>
    {/if}
  </section>

  {#if object.raw}
    <section>
      <h3>Rohdaten</h3>
      <CodeBlock code={object.raw} lang="text" copyable={false} />
    </section>
  {/if}
</aside>

<style>
  .drawer {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(560px, 100vw);
    overflow-y: auto;
    padding: var(--space-5);
    border-left: 1px solid var(--border);
    background: var(--surface-raised);
    box-shadow: var(--shadow-lg);
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
    z-index: 10;
  }
  .head p {
    margin: var(--space-1) 0 0;
  }
  .title {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  h2 {
    flex: 1;
    margin: 0;
    font-size: var(--text-lg);
    color: var(--text-strong);
  }
  h3 {
    margin: 0 0 var(--space-2);
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-muted);
  }
  .identity,
  .key,
  .muted,
  .since {
    color: var(--text-subtle);
  }
  .identity,
  .key,
  .small {
    font-size: var(--text-sm);
  }
  .reason {
    color: var(--text);
  }
  .ack {
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .tbl {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  .tbl th,
  .tbl td {
    padding: var(--space-1) var(--space-2) var(--space-1) 0;
    border-bottom: 1px solid var(--border-faint);
    text-align: left;
    vertical-align: baseline;
  }
  .tbl th {
    font-weight: 500;
    color: var(--text-muted);
  }
  .tbl tr.off td {
    color: var(--text-subtle);
    text-decoration: line-through;
  }
  .mono,
  code {
    font-family: var(--font-mono);
  }
  .history {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    font-size: var(--text-sm);
  }
  .history li {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .note {
    margin: 0;
    font-size: var(--text-sm);
  }
  .actions {
    margin-top: var(--space-2);
  }
</style>
