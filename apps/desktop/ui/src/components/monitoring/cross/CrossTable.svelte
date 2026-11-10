<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  import type { Snippet } from 'svelte';

  export type SortValue = number | string | null;
  export type SortDir = 'asc' | 'desc';

  export interface CrossColumn<R> {
    key: string;
    label: string;
    /** The cell as text; the filter searches it. */
    text: (row: R) => string;
    /** Sort key, else the text; null sorts last in both directions. */
    sort?: (row: R) => SortValue;
    /** A richer cell than the text, e.g. a status pill. */
    cell?: Snippet<[R]>;
    numeric?: boolean;
  }
</script>

<script lang="ts" generics="R">
  import ArrowDown from '@lucide/svelte/icons/arrow-down';
  import ArrowUp from '@lucide/svelte/icons/arrow-up';
  import { currentLocale, t } from '$lib/i18n';
  import EmptyState from '../../ui/EmptyState.svelte';
  import SearchField from '../../ui/SearchField.svelte';

  interface Props {
    rows: R[];
    columns: CrossColumn<R>[];
    rowKey: (row: R) => string;
    /** Names the table for assistive tech. */
    label: string;
    /** Shown when there is no row at all. */
    emptyText: string;
    sortKey?: string;
    sortDir?: SortDir;
  }

  let { rows, columns, rowKey, label, emptyText, sortKey, sortDir = 'asc' }: Props = $props();

  let query = $state('');
  let chosen = $state<{ key: string; dir: SortDir } | null>(null);
  const sort = $derived(chosen ?? (sortKey ? { key: sortKey, dir: sortDir } : null));

  const needle = $derived(query.trim().toLocaleLowerCase());
  const filtered = $derived(
    needle
      ? rows.filter((row) =>
          columns.some((col) => col.text(row).toLocaleLowerCase().includes(needle)),
        )
      : rows,
  );

  function compare(a: SortValue, b: SortValue, sign: number): number {
    if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
    if (typeof a === 'number' && typeof b === 'number') return sign * (a - b);
    return sign * String(a).localeCompare(String(b), currentLocale(), { numeric: true });
  }

  const shown = $derived.by(() => {
    const col = sort && columns.find((c) => c.key === sort.key);
    if (!sort || !col) return filtered;
    const value = col.sort ?? col.text;
    const sign = sort.dir === 'asc' ? 1 : -1;
    return filtered
      .map((row) => ({ row, v: value(row) }))
      .sort((a, b) => compare(a.v, b.v, sign))
      .map((e) => e.row);
  });

  function sortBy(key: string): void {
    chosen = { key, dir: sort?.key === key && sort.dir === 'asc' ? 'desc' : 'asc' };
  }

  function ariaSort(key: string): 'ascending' | 'descending' | 'none' {
    if (sort?.key !== key) return 'none';
    return sort.dir === 'asc' ? 'ascending' : 'descending';
  }
</script>

{#if rows.length === 0}
  <EmptyState framed={false} message={emptyText} />
{:else}
  <div class="cross">
    <div class="cross-tools">
      <SearchField
        bind:value={query}
        size="sm"
        fullWidth={false}
        label={$t('monitoring.cross.filter')}
        placeholder={$t('monitoring.cross.filter')}
      />
      {#if needle}
        <span class="cross-count">
          {$t('monitoring.cross.count', { shown: shown.length, total: rows.length })}
        </span>
      {/if}
    </div>
    {#if shown.length === 0}
      <EmptyState
        framed={false}
        message={$t('monitoring.cross.noMatch', { query: query.trim() })}
      />
    {:else}
      <div class="cross-scroll">
        <table class="cross-table" aria-label={label}>
          <thead>
            <tr>
              {#each columns as col (col.key)}
                <th scope="col" class:numeric={col.numeric} aria-sort={ariaSort(col.key)}>
                  <button type="button" class="cross-sort" onclick={() => sortBy(col.key)}>
                    {col.label}
                    {#if sort?.key === col.key}
                      <span class="cross-arrow" aria-hidden="true">
                        {#if sort.dir === 'asc'}
                          <ArrowUp size={12} />
                        {:else}
                          <ArrowDown size={12} />
                        {/if}
                      </span>
                    {/if}
                  </button>
                </th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each shown as row (rowKey(row))}
              <tr>
                {#each columns as col (col.key)}
                  <td class:numeric={col.numeric}>
                    {#if col.cell}{@render col.cell(row)}{:else}{col.text(row)}{/if}
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </div>
{/if}

<style>
  .cross {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    min-width: 0;
  }
  .cross-tools {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  .cross-count {
    color: var(--text-subtle);
    font-size: var(--text-xs);
  }
  .cross-scroll {
    overflow-x: auto;
  }
  .cross-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  .cross-table th,
  .cross-table td {
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--border-faint);
    text-align: left;
    vertical-align: middle;
  }
  .cross-table .numeric {
    font-family: var(--font-mono);
    text-align: right;
  }
  .cross-table thead th {
    color: var(--text-subtle);
    font-weight: 500;
    white-space: nowrap;
  }
  .cross-table tbody tr:hover {
    background: var(--surface-hover);
  }
  .cross-sort {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    padding: 0;
    border: 0;
    background: none;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }
  .cross-sort:focus-visible {
    outline: var(--ring-width) solid var(--accent);
    outline-offset: 2px;
  }
  .cross-arrow {
    display: inline-flex;
  }
</style>
