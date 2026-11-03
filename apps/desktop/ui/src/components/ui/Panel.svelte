<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Component, Snippet } from 'svelte';

  interface Props {
    title?: string;
    icon?: Component<{ size?: number }>;
    action?: Snippet;
    pad?: number;
    children: Snippet;
  }

  let { title, icon: Icon, action, pad = 16, children }: Props = $props();
</script>

<section class="panel">
  {#if title || action}
    <header class="head">
      {#if Icon}<span class="icon"><Icon size={15} /></span>{/if}
      {#if title}<h3 class="title">{title}</h3>{/if}
      {#if action}<div class="action">{@render action()}</div>{/if}
    </header>
  {/if}
  <div class="body" style:padding="{pad}px">{@render children()}</div>
</section>

<style>
  .panel {
    display: flex;
    flex-direction: column;
    min-width: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
  }
  .head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border-faint);
  }
  .icon {
    display: inline-flex;
    color: var(--text-muted);
  }
  .title {
    margin: 0;
    color: var(--text);
    font-size: var(--text-sm);
    font-weight: 600;
  }
  .action {
    margin-left: auto;
  }
  .body {
    min-width: 0;
  }
</style>
