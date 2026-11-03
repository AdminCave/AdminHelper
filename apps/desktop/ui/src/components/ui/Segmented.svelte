<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Component } from 'svelte';
  import { nextIndex } from './roving';

  interface Option {
    value: string;
    label?: string;
    icon?: Component<{ size?: number }>;
    // Needed for icon-only options: becomes the accessible name.
    title?: string;
  }

  interface Props {
    options: Option[];
    value?: string;
    size?: 'sm' | 'md';
    label?: string;
    onChange?: (value: string) => void;
  }

  let { options, value = $bindable(''), size = 'sm', label, onChange }: Props = $props();

  let buttons: HTMLButtonElement[] = $state([]);
  const current = $derived(
    Math.max(
      0,
      options.findIndex((o) => o.value === value),
    ),
  );

  function select(v: string) {
    value = v;
    onChange?.(v);
  }

  function onkeydown(e: KeyboardEvent, i: number) {
    const to = nextIndex(e.key, i, options.length);
    if (to === undefined) return;
    e.preventDefault();
    select(options[to].value);
    buttons[to]?.focus();
  }
</script>

<div class="seg seg-{size}" role="radiogroup" aria-label={label}>
  {#each options as o, i (o.value)}
    <button
      bind:this={buttons[i]}
      type="button"
      role="radio"
      class="opt"
      class:icon-only={!o.label}
      aria-checked={o.value === value}
      aria-label={o.label ? undefined : o.title}
      title={o.title ?? o.label}
      tabindex={i === current ? 0 : -1}
      onclick={() => select(o.value)}
      onkeydown={(e) => onkeydown(e, i)}
    >
      {#if o.icon}<o.icon size={14} />{/if}
      {o.label ?? ''}
    </button>
  {/each}
</div>

<style>
  .seg {
    display: inline-flex;
    gap: 2px;
    padding: 2px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-pill);
    background: var(--surface-inset);
  }
  .opt {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 0 11px;
    border: 0;
    border-radius: var(--radius-pill);
    background: transparent;
    color: var(--text-muted);
    font: inherit;
    font-size: 12.5px;
    font-weight: 500;
    white-space: nowrap;
    cursor: pointer;
  }
  .seg-sm .opt {
    height: 22px;
  }
  .seg-md .opt {
    height: 28px;
  }
  .icon-only {
    padding: 0 7px;
  }
  .opt[aria-checked='true'] {
    background: var(--surface-active);
    color: var(--text-strong);
    font-weight: 600;
  }
</style>
