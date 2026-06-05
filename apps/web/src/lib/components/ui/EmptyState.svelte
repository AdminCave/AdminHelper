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
  <p>{message}</p>
  {#if children}
    {@render children()}
  {/if}
</div>
