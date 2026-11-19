<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Every object over all servers as one table, with filters (kind, status, server, hidden) and a
  // search over name, server, reason, key and identity. Thousands of objects draw a page at a time.
  import Badge from '../../../components/ui/Badge.svelte';
  import EmptyState from '../../../components/ui/EmptyState.svelte';
  import SearchField from '../../../components/ui/SearchField.svelte';
  import Select from '../../../components/ui/Select.svelte';
  import Switch from '../../../components/ui/Switch.svelte';
  import type { Kind, MonObject, Status } from '../model';
  import {
    KIND_LABEL,
    STATUS_LABEL,
    STATUS_TONE,
    exceptionText,
    isHidden,
    sinceText,
  } from '../grammar';
  import { type ObjectFilter, NO_FILTER, filterObjects, serversOf } from './lists';

  interface Props {
    objects: MonObject[];
    now: Date;
    selected?: string;
    onOpen: (key: string) => void;
  }

  let { objects, now, selected, onOpen }: Props = $props();

  // Select shows a disabled placeholder for an empty value, so "all" needs a value of its own.
  const ALL = 'all';
  const PAGE = 200;

  let filter = $state<ObjectFilter>({ ...NO_FILTER });

  const kinds = $derived(
    [...new Set<Kind>(objects.map((o) => o.kind))].map((k) => ({ value: k, label: KIND_LABEL[k] })),
  );
  const statuses = (Object.keys(STATUS_LABEL) as Status[]).map((s) => ({
    value: s,
    label: STATUS_LABEL[s],
  }));
  const list = $derived(filterObjects(objects, filter));
  let pages = $state(1);
  const limit = $derived(PAGE * pages);
  // A new filter starts at the first page again.
  $effect(() => {
    void filter.kind;
    void filter.status;
    void filter.server;
    void filter.query;
    void filter.showHidden;
    pages = 1;
  });
</script>

<div class="filters">
  <label class="f">
    <span>Art</span>
    <Select
      value={filter.kind || ALL}
      options={[{ value: ALL, label: 'Alle Arten' }, ...kinds]}
      onChange={(v) => (filter.kind = v === ALL ? '' : (v as Kind))}
    />
  </label>
  <label class="f">
    <span>Zustand</span>
    <Select
      value={filter.status || ALL}
      options={[
        { value: ALL, label: 'Alle' },
        { value: 'problems', label: 'Nur Probleme' },
        ...statuses,
      ]}
      onChange={(v) => (filter.status = v === ALL ? '' : (v as ObjectFilter['status']))}
    />
  </label>
  <label class="f">
    <span>Server</span>
    <Select
      value={filter.server || ALL}
      options={[{ value: ALL, label: 'Alle Server' }, ...serversOf(objects)]}
      onChange={(v) => (filter.server = v === ALL ? '' : v)}
    />
  </label>
  <Switch
    checked={filter.showHidden}
    label="Ausgeblendete zeigen"
    onChange={(c) => (filter.showHidden = c)}
  />
  <SearchField
    bind:value={filter.query}
    placeholder="Suchen"
    label="Objekte durchsuchen"
    shortcut=""
  />
</div>

<p class="count" data-testid="objects-count">
  {list.length} von {objects.length} Objekten{#if list.length > limit}, die ersten {limit} gezeigt{/if}
</p>

{#if list.length === 0}
  <EmptyState title="Keine Treffer" description="Kein Objekt passt zu Filter und Suche." />
{:else}
  <div class="wrap">
    <table class="tbl">
      <thead>
        <tr>
          <th>Zustand</th>
          <th>Objekt</th>
          <th>Art</th>
          <th>Server</th>
          <th>Seit</th>
        </tr>
      </thead>
      <tbody>
        {#each list.slice(0, limit) as o (o.key)}
          {@const hidden = isHidden(o)}
          <tr
            data-key={o.key}
            data-status={o.status}
            class:is-hidden={hidden}
            class:selected={selected === o.key}
          >
            <td class="st">
              {#if hidden}
                <Badge>Ausgeblendet</Badge>
              {:else}
                <Badge tone={STATUS_TONE[o.status]} dot>{STATUS_LABEL[o.status]}</Badge>
              {/if}
            </td>
            <td>
              <button type="button" class="open" onclick={() => onOpen(o.key)}>{o.name}</button>
              <span class="reason">
                {hidden && o.exception ? exceptionText(o.exception) : o.reason}
              </span>
            </td>
            <td>{KIND_LABEL[o.kind]}</td>
            <td>{o.server}</td>
            <td class="since">{sinceText(o.since, now)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  {#if list.length > limit}
    <p class="page">
      <button type="button" class="page-btn" onclick={() => (pages += 1)}
        >{Math.min(PAGE, list.length - limit)} weitere anzeigen</button
      >
      <span>noch {list.length - limit}</span>
    </p>
  {/if}
{/if}

<style>
  .filters {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3) var(--space-5);
    margin-bottom: var(--space-3);
  }
  .f {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .count {
    margin: 0 0 var(--space-3);
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .tbl {
    width: 100%;
    border-collapse: collapse;
    border: 1px solid var(--border);
    background: var(--surface);
    font-size: var(--text-sm);
  }
  th {
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--border);
    color: var(--text-subtle);
    font-weight: 500;
    text-align: left;
  }
  td {
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--border-faint);
    vertical-align: top;
  }
  tbody tr:hover {
    background: var(--surface-hover);
  }
  tr.selected {
    background: var(--surface-active);
  }
  tr.is-hidden {
    opacity: 0.6;
  }
  .st {
    width: 120px;
  }
  .open {
    display: block;
    padding: 0;
    border: 0;
    background: none;
    color: var(--text-strong);
    font: inherit;
    font-weight: 600;
    text-align: left;
    cursor: pointer;
  }
  .reason {
    color: var(--text-muted);
  }
  .since {
    color: var(--text-subtle);
    white-space: nowrap;
  }
  .wrap {
    overflow-x: auto;
  }
  .page {
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
    margin: var(--space-3) 0 0;
    font-size: var(--text-sm);
    color: var(--text-subtle);
  }
  .page-btn {
    padding: var(--space-1) var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    background: var(--surface);
    color: var(--text-strong);
    font: inherit;
    cursor: pointer;
  }
  .page-btn:hover {
    background: var(--surface-hover);
  }
  /* Phone: the kind goes, the rest wraps inside the cells. */
  @media (max-width: 760px) {
    .filters {
      gap: var(--space-2) var(--space-3);
    }
    th:nth-child(3),
    td:nth-child(3) {
      display: none;
    }
    th,
    td {
      padding: var(--space-2);
    }
    .st {
      width: auto;
    }
  }
</style>
