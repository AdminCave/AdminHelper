<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Component, Snippet } from 'svelte';
  import type { HTMLButtonAttributes } from 'svelte/elements';
  import Spinner from './Spinner.svelte';

  type Variant = 'primary' | 'secondary' | 'ghost' | 'accent' | 'danger';
  type Size = 'sm' | 'md' | 'lg';

  interface Props extends Omit<HTMLButtonAttributes, 'children'> {
    variant?: Variant;
    size?: Size;
    loading?: boolean;
    fullWidth?: boolean;
    iconLeft?: Component<{ size?: number }>;
    iconRight?: Component<{ size?: number }>;
    children?: Snippet;
  }

  let {
    variant = 'primary',
    size = 'md',
    loading = false,
    fullWidth = false,
    disabled = false,
    type = 'button',
    iconLeft: IconLeft,
    iconRight: IconRight,
    children,
    class: cls = '',
    ...rest
  }: Props = $props();

  const iconSize = $derived(size === 'sm' ? 14 : size === 'lg' ? 18 : 16);
</script>

<button
  {...rest}
  {type}
  class={['ui-btn', `ui-btn-${variant}`, `ui-btn-${size}`, cls]}
  class:full={fullWidth}
  disabled={disabled || loading}
  aria-busy={loading || undefined}
>
  {#if loading}
    <Spinner size={iconSize} />
  {:else if IconLeft}
    <IconLeft size={iconSize} />
  {/if}
  {#if children}<span class="label">{@render children()}</span>{/if}
  {#if IconRight && !loading}
    <IconRight size={iconSize} />
  {/if}
</button>

<style>
  .ui-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    border: 1px solid transparent;
    border-radius: var(--radius-pill);
    font: inherit;
    font-weight: 500;
    white-space: nowrap;
    cursor: pointer;
    transition:
      background var(--dur-fast) var(--ease-standard),
      border-color var(--dur-fast) var(--ease-standard),
      color var(--dur-fast) var(--ease-standard),
      transform var(--dur-instant) var(--ease-standard);
  }
  .ui-btn:active:not(:disabled) {
    transform: scale(0.97);
  }
  .ui-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .full {
    width: 100%;
  }
  .ui-btn-sm {
    height: 32px;
    padding: 0 14px;
    font-size: var(--text-xs);
  }
  .ui-btn-md {
    height: 40px;
    padding: 0 18px;
    font-size: var(--text-sm);
  }
  .ui-btn-lg {
    height: 48px;
    padding: 0 24px;
    font-size: var(--text-base);
  }
  .ui-btn-primary {
    background: var(--fill-solid);
    color: var(--fill-solid-text);
  }
  .ui-btn-primary:hover:not(:disabled) {
    background: var(--fill-solid-hover);
  }
  .ui-btn-secondary {
    background: transparent;
    border-color: var(--border-strong);
    color: var(--text);
  }
  .ui-btn-secondary:hover:not(:disabled) {
    background: var(--surface-hover);
  }
  .ui-btn-ghost {
    background: transparent;
    color: var(--text);
  }
  .ui-btn-ghost:hover:not(:disabled) {
    background: var(--surface-hover);
  }
  .ui-btn-accent {
    background: var(--accent);
    color: var(--text-inverse);
  }
  .ui-btn-accent:hover:not(:disabled) {
    background: var(--accent-hover);
  }
  .ui-btn-danger {
    background: var(--danger-bg);
    border-color: var(--danger-border);
    color: var(--danger);
  }
  .ui-btn-danger:hover:not(:disabled) {
    border-color: var(--danger);
  }
</style>
