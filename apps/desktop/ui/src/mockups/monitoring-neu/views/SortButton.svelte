<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // The head of a sortable column: the title as a button, an arrow on the active column. The
  // table's <th> carries aria-sort (ariaSort in sorting.ts), so a screen reader hears the order.
  import { type Dir, type Sort, nextSort } from './sorting';

  interface Props {
    title: string;
    col: string;
    sort: Sort;
    /** The direction of the first click on this column. */
    first?: Dir;
    onSort: (sort: Sort) => void;
  }

  let { title, col, sort, first = 'asc', onSort }: Props = $props();

  const active = $derived(sort.col === col);
</script>

<button
  type="button"
  class="sort-btn"
  class:active
  data-col={col}
  onclick={() => onSort(nextSort(sort, col, first))}
  >{title}<span class="arrow" aria-hidden="true"
    >{active ? (sort.dir === 'asc' ? '↑' : '↓') : '↕'}</span
  ></button
>

<style>
  .sort-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    padding: 0;
    border: 0;
    border-radius: var(--radius-xs);
    background: none;
    color: inherit;
    font: inherit;
    white-space: nowrap;
    cursor: pointer;
  }
  .sort-btn:hover,
  .sort-btn.active {
    color: var(--text-strong);
  }
  .sort-btn:focus-visible {
    outline: none;
    box-shadow: var(--ring-shadow);
  }
  .arrow {
    color: var(--text-faint);
    font-size: var(--text-xs);
  }
  .active .arrow {
    color: var(--text-strong);
  }
</style>
