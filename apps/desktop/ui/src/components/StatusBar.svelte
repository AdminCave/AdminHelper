<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { toasts, dismissStatus } from '$lib/stores/statusBar';
  import Toast from './ui/Toast.svelte';
</script>

{#if $toasts.length > 0}
  <div class="toast-stack">
    {#each $toasts as m (m.id)}
      <Toast
        title={m.text}
        tone={m.isError ? 'danger' : 'neutral'}
        onDismiss={() => dismissStatus(m.id)}
      />
    {/each}
  </div>
{/if}

<style>
  /* Bottom right, above the status footer; the newest toast is the lowest. */
  .toast-stack {
    position: fixed;
    right: var(--space-4);
    bottom: 44px;
    z-index: 80;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    align-items: flex-end;
  }
</style>
