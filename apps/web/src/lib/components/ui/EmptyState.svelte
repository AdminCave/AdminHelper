<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Component, Snippet } from 'svelte';

  interface Props {
    title?: string;
    description?: string;
    icon?: Component<{ size?: number }>;
    action?: Snippet;
    // Dashed frame around the state.
    framed?: boolean;
    // Older form: a single line of text and the call to action as children.
    message?: string;
    children?: Snippet;
  }

  let {
    title,
    description,
    icon: Icon,
    action,
    framed = true,
    message,
    children,
  }: Props = $props();

  const cta = $derived(action ?? children);
</script>

<div class="empty-state" class:framed>
  {#if Icon}<span class="icon" aria-hidden="true"><Icon size={22} /></span>{/if}
  {#if title}<h3 class="title">{title}</h3>{/if}
  {#if description}<p class="desc">{description}</p>{/if}
  {#if message}<p class="empty-message">{message}</p>{/if}
  {#if cta}<div class="action">{@render cta()}</div>{/if}
</div>

<style>
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: var(--space-16) var(--space-8);
    color: var(--text-muted);
    text-align: center;
    border-radius: var(--radius-2xl);
  }
  .framed {
    border: 1px dashed var(--border-strong);
  }
  .icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 48px;
    height: 48px;
    margin-bottom: var(--space-5);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface-inset);
  }
  .title {
    margin: 0;
    font-size: var(--text-xl);
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--text-strong);
  }
  .desc {
    max-width: 380px;
    margin: 8px 0 0;
    font-size: var(--text-base);
    line-height: 1.5;
  }
  .empty-message {
    margin: 0;
    font-size: var(--text-sm);
  }
  .action {
    margin-top: var(--space-6);
  }
</style>
