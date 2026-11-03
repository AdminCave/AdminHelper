<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Snippet } from 'svelte';

  type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

  interface Props {
    tone?: Tone;
    dot?: boolean;
    children: Snippet;
  }

  let { tone = 'neutral', dot = false, children }: Props = $props();
</script>

<span class="badge badge-{tone}">
  {#if dot}<span class="dot" aria-hidden="true"></span>{/if}
  {@render children()}
</span>

<style>
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 22px;
    padding: 0 var(--space-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    background: var(--surface-raised);
    color: var(--text-muted);
    font-size: var(--text-xs);
    font-weight: 500;
    white-space: nowrap;
  }
  .dot {
    width: 6px;
    height: 6px;
    border-radius: var(--radius-pill);
    background: currentColor;
  }
  .badge-success {
    background: var(--success-bg);
    border-color: var(--success-border);
    color: var(--success);
  }
  .badge-warning {
    background: var(--warning-bg);
    border-color: var(--warning-border);
    color: var(--warning);
  }
  .badge-danger {
    background: var(--danger-bg);
    border-color: var(--danger-border);
    color: var(--danger);
  }
  .badge-info {
    background: var(--info-bg);
    border-color: var(--info-border);
    color: var(--info);
  }
</style>
