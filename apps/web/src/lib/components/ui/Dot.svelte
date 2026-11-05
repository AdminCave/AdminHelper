<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  // Status names of the DS kit (ui_kits/adminhelper/kit.jsx); anything else is subtle.
  const COLORS: Record<string, string> = {
    ok: 'var(--success)',
    info: 'var(--info)',
    warning: 'var(--warning)',
    warn: 'var(--warning)',
    critical: 'var(--danger)',
    crit: 'var(--danger)',
    connected: 'var(--success)',
    connecting: 'var(--warning)',
    disconnected: 'var(--danger)',
    running: 'var(--success)',
    failed: 'var(--danger)',
  };

  export function statusColor(st: string): string {
    return COLORS[st] ?? 'var(--text-subtle)';
  }
</script>

<script lang="ts">
  interface Props {
    st: string;
    size?: number;
    ring?: boolean;
    label?: string;
  }

  let { st, size = 8, ring = false, label }: Props = $props();
  const color = $derived(statusColor(st));
</script>

<span
  class="dot"
  role={label ? 'img' : undefined}
  aria-label={label}
  aria-hidden={label ? undefined : 'true'}
  style:width="{size}px"
  style:height="{size}px"
  style:background={color}
  style:box-shadow={ring ? `0 0 0 3px color-mix(in srgb, ${color} 22%, transparent)` : undefined}
></span>

<style>
  .dot {
    display: inline-block;
    flex: 0 0 auto;
    border-radius: var(--radius-pill);
  }
</style>
