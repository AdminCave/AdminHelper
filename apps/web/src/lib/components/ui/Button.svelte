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
    // Associates a type="submit" button with a form by id, so a footer button
    // outside the <form> submits it natively — no document.getElementById (2.139).
    form?: string;
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
    form,
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

<button {type} {form} class={cls} {disabled} {title} {onclick}>
  {@render children()}
</button>
