<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { nextIndex } from './roving';

  type Tab = { id: string; label: string; count?: number } | string;

  interface Props {
    tabs: Tab[];
    // Active tab id; the first tab when unset.
    value?: string;
    label?: string;
    onChange?: (id: string) => void;
  }

  let { tabs, value = $bindable(), label, onChange }: Props = $props();

  const norm = $derived(tabs.map((t) => (typeof t === 'string' ? { id: t, label: t } : t)));
  // An unknown value still leaves one tab in the tab order.
  const active = $derived(norm.some((t) => t.id === value) ? value : norm[0]?.id);
  let buttons: HTMLButtonElement[] = $state([]);

  function select(id: string) {
    value = id;
    onChange?.(id);
  }

  // Automatic activation: the arrow keys move focus and selection together.
  function onkeydown(e: KeyboardEvent, i: number) {
    const to = nextIndex(e.key, i, norm.length);
    if (to === undefined) return;
    e.preventDefault();
    select(norm[to].id);
    buttons[to]?.focus();
  }
</script>

<div class="tabs" role="tablist" aria-label={label}>
  {#each norm as t, i (t.id)}
    <button
      bind:this={buttons[i]}
      type="button"
      role="tab"
      class="tab"
      aria-selected={t.id === active}
      tabindex={t.id === active ? 0 : -1}
      onclick={() => select(t.id)}
      onkeydown={(e) => onkeydown(e, i)}
    >
      {t.label}
      {#if t.count != null}<span class="count">{t.count}</span>{/if}
    </button>
  {/each}
</div>

<style>
  .tabs {
    display: flex;
    gap: var(--space-6);
    border-bottom: 1px solid var(--border);
  }
  .tab {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 0 2px 12px;
    border: 0;
    background: transparent;
    color: var(--text-muted);
    font: inherit;
    font-size: var(--text-base);
    font-weight: 500;
    cursor: pointer;
    transition: color var(--dur-fast);
  }
  .tab:hover {
    color: var(--text);
  }
  .tab::after {
    content: '';
    position: absolute;
    left: 0;
    right: 0;
    bottom: -1px;
    height: 2px;
    border-radius: var(--radius-pill);
    background: transparent;
    transition: background var(--dur-fast);
  }
  .tab[aria-selected='true'] {
    color: var(--text-strong);
    font-weight: 600;
  }
  .tab[aria-selected='true']::after {
    background: var(--text-strong);
  }
  .count {
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 11px;
  }
  .tab[aria-selected='true'] .count {
    color: var(--text-muted);
  }
</style>
