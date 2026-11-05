<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    children: Snippet;
  }

  let { children }: Props = $props();
</script>

<kbd class="kbd">{@render children()}</kbd>

<style>
  .kbd {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 20px;
    height: 20px;
    padding: 0 5px;
    border: 1px solid var(--border-strong);
    border-bottom-width: 2px;
    border-radius: var(--radius-xs);
    background: var(--surface-raised);
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 11px;
    line-height: 1;
  }
</style>
