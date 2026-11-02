<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Snippet } from 'svelte';

  type Tone = 'ok' | 'warn' | 'crit' | 'accent' | 'muted';

  interface Props {
    tone?: Tone;
    title?: string;
    children: Snippet;
  }

  let { tone = 'muted', title, children }: Props = $props();
</script>

<span class="pill pill-{tone}" {title}>{@render children()}</span>

<style>
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    height: 20px;
    padding: 0 7px;
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 11px;
    white-space: nowrap;
  }
  .pill-ok {
    background: var(--success-bg);
    border-color: var(--success-border);
    color: var(--success);
  }
  .pill-warn {
    background: var(--warning-bg);
    border-color: var(--warning-border);
    color: var(--warning);
  }
  .pill-crit {
    background: var(--danger-bg);
    border-color: var(--danger-border);
    color: var(--danger);
  }
  .pill-accent {
    background: var(--accent-muted);
    border-color: var(--accent-border);
    color: var(--accent);
  }
</style>
