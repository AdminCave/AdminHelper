<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { tunnel } from '$lib/stores/tunnel';
  import { sessionStore } from '$lib/stores/session';

  let visible = $derived(
    $sessionStore.settings?.mode === 'server' && $sessionStore.session !== null,
  );
  let label = $derived.by(() => {
    const t = $tunnel;
    if (t.ui === 'connecting') return 'Tunnel verbindet…';
    if (t.ui === 'connected') {
      return t.status?.visitorName ? `Tunnel: ${t.status.visitorName}` : 'Tunnel aktiv';
    }
    if (t.ui === 'disconnected') return 'Tunnel getrennt';
    return 'Tunnel inaktiv';
  });
</script>

{#if visible}
  <div class="tunnel-indicator" data-status={$tunnel.ui} title={label}>
    <span class="tunnel-dot"></span>
    <span class="tunnel-label">{label}</span>
  </div>
{/if}

<style>
  .tunnel-indicator {
    display: flex;
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
    background: var(--success, #4caf50);
  }
  .tunnel-indicator[data-status='connecting'] .tunnel-dot {
    background: var(--warning, #e0a500);
  }
  .tunnel-indicator[data-status='disconnected'] .tunnel-dot {
    background: var(--error, #e05555);
  }
</style>
