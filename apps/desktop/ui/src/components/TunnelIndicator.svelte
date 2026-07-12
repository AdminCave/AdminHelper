<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { tunnel } from '$lib/stores/tunnel';
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
    background: var(--success);
  }
  .tunnel-indicator[data-status='connecting'] .tunnel-dot {
    background: var(--warning);
  }
  .tunnel-indicator[data-status='disconnected'] .tunnel-dot {
    background: var(--danger);
  }
</style>
