<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { tunnel, reconnectNow } from '$lib/stores/tunnel';
  import { sessionStore } from '$lib/stores/session';
  import { t } from '$lib/i18n';

  let visible = $derived(
    $sessionStore.settings?.mode === 'server' && $sessionStore.session !== null,
  );
  let label = $derived.by(() => {
    const tn = $tunnel;
    if (tn.ui === 'connecting') return $t('tunnel.connecting');
    if (tn.ui === 'connected') {
      return tn.status?.visitorName
        ? $t('tunnel.activeNamed', { name: tn.status.visitorName })
        : $t('tunnel.active');
    }
    if (tn.ui === 'disconnected') return $t('tunnel.disconnected');
    return $t('tunnel.inactive');
  });
  // Only while disconnected: a click on a connected tunnel would drop its sessions.
  let disconnected = $derived($tunnel.ui === 'disconnected');

  // A click waits for its reconnection (up to two runs); until then a second one starts
  // nothing. The button going away ends the wait, so it is clickable whenever it shows.
  let busy = $state(false);
  let clicks = 0;
  $effect(() => {
    if (!disconnected) busy = false;
  });

  async function reconnect(): Promise<void> {
    if (busy) return;
    busy = true;
    const click = ++clicks;
    try {
      await reconnectNow();
    } finally {
      // A later click owns the wait now.
      if (click === clicks) busy = false;
    }
  }
</script>

{#if visible}
  <div class="tunnel-indicator" data-status={$tunnel.ui} title={label}>
    <span class="tunnel-dot"></span>
    <span class="tunnel-label">{label}</span>
    {#if disconnected}
      <button
        type="button"
        class="btn ghost small tunnel-reconnect"
        onclick={reconnect}
        disabled={busy}
        aria-busy={busy}>{$t('tunnel.reconnect')}</button
      >
    {/if}
  </div>
{/if}

<style>
  .tunnel-indicator {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--sp-2);
    padding: var(--sp-2) var(--sp-3);
    font-size: 12px;
    color: var(--text-muted);
    border-top: 1px solid var(--border);
  }
  .tunnel-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--text-muted);
  }
  .tunnel-indicator[data-status='connected'] .tunnel-dot {
    background: var(--success);
  }
  .tunnel-indicator[data-status='connecting'] .tunnel-dot {
    background: var(--warning);
  }
  .tunnel-indicator[data-status='disconnected'] .tunnel-dot {
    background: var(--danger);
  }
  /* The collapsed sidebar hides the label and has no room for the button either. */
  :global(.app-shell.sidebar-collapsed) .tunnel-reconnect {
    display: none;
  }
</style>
