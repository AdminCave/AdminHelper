<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Snippet } from 'svelte';

  type Kind =
    | 'default'
    | 'success'
    | 'warning'
    | 'error'
    | 'info'
    | 'ok'
    | 'critical'
    | 'unknown'
    | 'pending';

  interface Props {
    kind?: Kind;
    children: Snippet;
    class?: string;
  }

  let { kind = 'default', children, class: extraClass = '' }: Props = $props();

  const cls = $derived(
    ['badge', kind !== 'default' ? `badge-${kind}` : '', extraClass].filter(Boolean).join(' '),
  );
</script>

<span class={cls}>{@render children()}</span>
