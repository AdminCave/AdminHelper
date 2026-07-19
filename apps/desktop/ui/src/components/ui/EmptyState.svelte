<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    message: string;
    children?: Snippet;
  }

  let { message, children }: Props = $props();
</script>

<div class="empty-state">
  <p class="empty-message">{message}</p>
  {#if children}
    {@render children()}
  {/if}
</div>

<style>
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-6) var(--sp-4);
    color: var(--text-muted);
    text-align: center;
  }
  .empty-message {
    margin: 0;
    font-size: 13px;
  }
</style>
