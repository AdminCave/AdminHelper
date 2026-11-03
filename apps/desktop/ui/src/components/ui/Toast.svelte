<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '$lib/i18n';

  type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

  interface Props {
    title: string;
    description?: string;
    tone?: Tone;
    action?: Snippet;
    onDismiss?: () => void;
    dismissLabel?: string;
  }

  let { title, description, tone = 'neutral', action, onDismiss, dismissLabel }: Props = $props();

  // Failures interrupt; everything else waits for the reader.
  const role = $derived(tone === 'danger' ? 'alert' : 'status');
</script>

<div class="toast toast-{tone}" {role}>
  <span class="dot" aria-hidden="true"></span>
  <div class="body">
    <div class="title">{title}</div>
    {#if description}<div class="desc">{description}</div>{/if}
    {#if action}<div class="action">{@render action()}</div>{/if}
  </div>
  {#if onDismiss}
    <button
      type="button"
      class="dismiss"
      aria-label={dismissLabel ?? $t('action.close')}
      onclick={onDismiss}>×</button
    >
  {/if}
</div>

<style>
  .toast {
    --dot: var(--text-muted);
    display: flex;
    align-items: flex-start;
    gap: 12px;
    box-sizing: border-box;
    width: 360px;
    max-width: 90vw;
    padding: 14px 14px 14px 16px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-md);
    background: var(--surface-raised);
    box-shadow: var(--shadow-pop);
  }
  .toast-success {
    --dot: var(--success);
  }
  .toast-warning {
    --dot: var(--warning);
  }
  .toast-danger {
    --dot: var(--danger);
  }
  .toast-info {
    --dot: var(--accent);
  }
  .dot {
    flex: 0 0 auto;
    width: 8px;
    height: 8px;
    margin-top: 6px;
    border-radius: var(--radius-pill);
    background: var(--dot);
  }
  .body {
    flex: 1;
    min-width: 0;
  }
  .title {
    color: var(--text-strong);
    font-size: var(--text-base);
    font-weight: 600;
  }
  .desc {
    margin-top: 3px;
    color: var(--text-muted);
    font-size: var(--text-sm);
    line-height: 1.45;
  }
  .action {
    margin-top: 10px;
  }
  .dismiss {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 auto;
    width: 24px;
    height: 24px;
    padding: 0;
    border: 0;
    border-radius: var(--radius-pill);
    background: transparent;
    color: var(--text-subtle);
    font-size: 16px;
    cursor: pointer;
  }
  .dismiss:hover {
    color: var(--text);
  }
</style>
