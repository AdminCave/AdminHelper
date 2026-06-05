<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { toasts, dismissToast } from '$lib/stores/notifications';
</script>

<div class="toast-stack" aria-live="polite" aria-atomic="false">
  {#each $toasts as t (t.id)}
    <button class="toast show {t.kind}" type="button" onclick={() => dismissToast(t.id)}>
      {t.message}
    </button>
  {/each}
</div>

<style>
  .toast-stack {
    position: fixed;
    right: 20px;
    bottom: 20px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    z-index: 9999;
    pointer-events: none;
  }
  .toast-stack :global(.toast) {
    pointer-events: auto;
    cursor: pointer;
  }
</style>
