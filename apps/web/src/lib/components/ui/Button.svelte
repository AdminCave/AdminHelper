<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Snippet } from 'svelte';

  type Variant = 'primary' | 'ghost' | 'danger';
  type Size = 'normal' | 'small';
  type ButtonType = 'button' | 'submit' | 'reset';

  interface Props {
    variant?: Variant;
    size?: Size;
    type?: ButtonType;
    disabled?: boolean;
    title?: string;
    onclick?: (e: MouseEvent) => void;
    children: Snippet;
    class?: string;
  }

  let {
    variant = 'primary',
    size = 'normal',
    type = 'button',
    disabled = false,
    title = '',
    onclick,
    children,
    class: extraClass = '',
  }: Props = $props();

  const cls = $derived(
    ['btn', variant, size === 'small' ? 'small' : '', extraClass].filter(Boolean).join(' '),
  );
</script>

<button {type} class={cls} {disabled} {title} {onclick}>
  {@render children()}
</button>
