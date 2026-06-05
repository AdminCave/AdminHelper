<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Snippet } from 'svelte';

  export type MonStatus = 'ok' | 'warning' | 'critical' | 'unknown' | 'pending';

  interface Props {
    status: MonStatus;
    children?: Snippet;
    label?: string;
  }

  let { status, children, label }: Props = $props();
</script>

<span class="status-pill mon-{status}">
  {#if children}
    {@render children()}
  {:else if label}
    {label}
  {:else}
    {status}
  {/if}
</span>
