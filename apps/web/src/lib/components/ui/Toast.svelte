<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { toasts, dismissToast } from '$lib/stores/notifications';
</script>

<!-- The web panel keeps its own stack (a click dismisses); the look follows the desktop
     Toast: raised surface, a dot in the tone of the message. -->
<div class="toast-stack" aria-live="polite" aria-atomic="false">
  {#each $toasts as t (t.id)}
    <button class="toast {t.kind}" type="button" onclick={() => dismissToast(t.id)}>
      <span class="dot" aria-hidden="true"></span>
      <span class="msg">{t.message}</span>
    </button>
  {/each}
</div>

<style>
  .toast-stack {
    position: fixed;
    right: var(--space-4);
    bottom: var(--space-4);
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: var(--space-2);
    z-index: 9999;
    pointer-events: none;
  }
  .toast {
    --dot: var(--text-muted);
    display: flex;
    align-items: flex-start;
    gap: 12px;
    box-sizing: border-box;
    width: 360px;
    max-width: 90vw;
    padding: 14px 16px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-md);
    background: var(--surface-raised);
    box-shadow: var(--shadow-pop);
    color: var(--text-strong);
    font: inherit;
    font-size: var(--text-base);
    text-align: left;
    pointer-events: auto;
    cursor: pointer;
  }
  .toast.success {
    --dot: var(--success);
  }
  .toast.error {
    --dot: var(--danger);
  }
  .toast.info {
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
  .msg {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }
</style>
