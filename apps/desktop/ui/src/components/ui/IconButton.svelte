<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Component } from 'svelte';
  import type { HTMLButtonAttributes } from 'svelte/elements';

  type Variant = 'ghost' | 'secondary' | 'solid';
  type Size = 'sm' | 'md' | 'lg';

  interface Props extends Omit<HTMLButtonAttributes, 'children'> {
    icon: Component<{ size?: number }>;
    // Required: an icon-only button has no other accessible name.
    label: string;
    variant?: Variant;
    size?: Size;
  }

  let {
    icon: Icon,
    label,
    variant = 'ghost',
    size = 'md',
    type = 'button',
    class: cls = '',
    ...rest
  }: Props = $props();

  const iconSize = $derived(size === 'sm' ? 15 : size === 'lg' ? 20 : 17);
</script>

<button
  {...rest}
  {type}
  class={['icon-btn', `icon-btn-${variant}`, `icon-btn-${size}`, cls]}
  aria-label={label}
  title={label}
>
  <Icon size={iconSize} />
</button>

<style>
  .icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 auto;
    padding: 0;
    border: 1px solid transparent;
    border-radius: var(--radius-pill);
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    transition:
      background var(--dur-fast) var(--ease-standard),
      color var(--dur-fast) var(--ease-standard),
      transform var(--dur-instant) var(--ease-standard);
  }
  .icon-btn:hover:not(:disabled) {
    background: var(--surface-hover);
    color: var(--text);
  }
  .icon-btn:active:not(:disabled) {
    transform: scale(0.92);
  }
  .icon-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .icon-btn-sm {
    width: 30px;
    height: 30px;
  }
  .icon-btn-md {
    width: 38px;
    height: 38px;
  }
  .icon-btn-lg {
    width: 46px;
    height: 46px;
  }
  .icon-btn-secondary {
    border-color: var(--border-strong);
  }
  .icon-btn-solid {
    background: var(--fill-solid);
    color: var(--fill-solid-text);
  }
  .icon-btn-solid:hover:not(:disabled) {
    background: var(--fill-solid-hover);
    color: var(--fill-solid-text);
  }
</style>
