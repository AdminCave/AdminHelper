<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { toasts, overflow, dismissStatus, type StatusMessage } from '$lib/stores/statusBar';
  import { t } from '$lib/i18n';
  import Toast from './ui/Toast.svelte';

  function open(m: StatusMessage): void {
    dismissStatus(m.id);
    m.onOpen?.();
  }
</script>

{#if $toasts.length > 0}
  <div class="toast-stack">
    {#if $overflow > 0}
      <div class="toast-overflow">{$t('notifications.more', { count: $overflow })}</div>
    {/if}
    {#each $toasts as m (m.id)}
      {#if m.onOpen}
        <Toast
          title={m.text}
          description={m.body}
          tone={m.tone}
          onDismiss={() => dismissStatus(m.id)}
        >
          {#snippet action()}
            <button type="button" class="toast-open" onclick={() => open(m)}
              >{$t('notifications.open')}</button
            >
          {/snippet}
        </Toast>
      {:else}
        <Toast
          title={m.text}
          description={m.body}
          tone={m.tone}
          onDismiss={() => dismissStatus(m.id)}
        />
      {/if}
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
  .toast-overflow {
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .toast-open {
    padding: 0;
    border: 0;
    background: none;
    color: var(--accent);
    font: inherit;
    cursor: pointer;
  }
</style>
