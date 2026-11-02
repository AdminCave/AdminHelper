<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Component, Snippet } from 'svelte';

  type Tone = 'info' | 'success' | 'warning' | 'danger' | 'neutral';

  interface Props {
    title?: string;
    tone?: Tone;
    icon?: Component<{ size?: number }>;
    action?: Snippet;
    children?: Snippet;
  }

  let { title, tone = 'info', icon: Icon, action, children }: Props = $props();
</script>

<!-- An inline banner, not a live region: it is part of the page, not an event. -->
<div class="callout callout-{tone}">
  {#if Icon}<span class="icon" aria-hidden="true"><Icon size={18} /></span>{/if}
  <div class="body">
    {#if title}<div class="title" class:spaced={!!children}>{title}</div>{/if}
    {#if children}<div class="text">{@render children()}</div>{/if}
  </div>
  {#if action}<div class="action">{@render action()}</div>{/if}
</div>

<style>
  .callout {
    --fg: var(--info);
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 14px 16px;
    background: var(--info-bg);
    border: 1px solid var(--info-border);
    border-radius: var(--radius-md);
  }
  .callout-success {
    --fg: var(--success);
    background: var(--success-bg);
    border-color: var(--success-border);
  }
  .callout-warning {
    --fg: var(--warning);
    background: var(--warning-bg);
    border-color: var(--warning-border);
  }
  .callout-danger {
    --fg: var(--danger);
    background: var(--danger-bg);
    border-color: var(--danger-border);
  }
  .callout-neutral {
    --fg: var(--text-muted);
    background: var(--surface);
    border-color: var(--border);
  }
  .icon {
    display: inline-flex;
    flex: 0 0 auto;
    margin-top: 1px;
    color: var(--fg);
  }
  .body {
    flex: 1;
    min-width: 0;
  }
  .title {
    font-size: var(--text-base);
    font-weight: 600;
    color: var(--text-strong);
  }
  .title.spaced {
    margin-bottom: 3px;
  }
  .text {
    font-size: var(--text-sm);
    color: var(--text-muted);
    line-height: 1.5;
  }
  .action {
    flex: 0 0 auto;
  }
</style>
