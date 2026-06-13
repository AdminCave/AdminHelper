<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import type { FrpConfig, FrpTunnel, Server } from '$lib/api/types';
  import { frpApi } from '$lib/api/frp';
  import { session } from '$lib/stores/session';
  import { reportError } from '$lib/stores/statusBar';
  import TunnelModal from '../TunnelModal.svelte';
  import { t } from '$lib/i18n';

  interface Props {
    server: Server;
  }
  let { server }: Props = $props();

  let tunnels = $state<FrpTunnel[]>([]);
  let configs = $state<FrpConfig[]>([]);
  let loading = $state(false);
  let modalOpen = $state(false);
  let editing = $state<FrpTunnel | null>(null);

  function errMsg(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  async function load(): Promise<void> {
    const s = $session;
    if (!s) return;
    loading = true;
    try {
      const [tun, cfg] = await Promise.all([frpApi.listTunnels(s), frpApi.listConfigs(s)]);
      tunnels = (Array.isArray(tun) ? tun : [])
        .filter((x) => x.serverId === server.id)
        .sort((a, b) => a.name.localeCompare(b.name));
      configs = Array.isArray(cfg) ? cfg : [];
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      loading = false;
    }
  }

  function openNew(): void {
    editing = null;
    modalOpen = true;
  }
  function openEdit(x: FrpTunnel): void {
    editing = x;
    modalOpen = true;
  }

  onMount(load);
</script>

<div class="tun-tab">
  {#if !loading && configs.length === 0}
    <p class="muted">{$t('infra.tun.noConfig')}</p>
  {/if}

  <div class="tun-toolbar">
    <button class="btn primary small" onclick={openNew} disabled={configs.length === 0}>
      + {$t('infra.tun.add')}
    </button>
  </div>

  {#if loading}
    <p class="muted">{$t('loading.generic')}</p>
  {:else if tunnels.length === 0}
    <p class="muted">{$t('infra.tun.empty')}</p>
  {:else}
    <div class="tun-list">
      {#each tunnels as x (x.id)}
        <div class="tun-row">
          <div class="tun-info">
            <div class="tun-name">{x.name}</div>
            <div class="tun-meta">
              {x.tunnelType.toUpperCase()} · {x.protocol.toUpperCase()} · {x.localIp}:{x.localPort}
            </div>
          </div>
          {#if !x.enabled}
            <span class="tun-badge">{$t('infra.tun.disabled')}</span>
          {/if}
          <button class="btn small" onclick={() => openEdit(x)}>{$t('action.edit')}</button>
        </div>
      {/each}
    </div>
  {/if}
</div>

<TunnelModal
  open={modalOpen}
  {editing}
  serverId={server.id}
  {configs}
  onClose={() => (modalOpen = false)}
  onSaved={load}
/>

<style>
  .tun-tab {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .tun-toolbar {
    display: flex;
    justify-content: flex-end;
  }
  .muted {
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .tun-list {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
  }
  .tun-row {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-2) var(--sp-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
  }
  .tun-info {
    flex: 1;
    min-width: 0;
  }
  .tun-name {
    font-size: var(--text-sm);
    font-weight: 600;
  }
  .tun-meta {
    font-size: var(--text-xs);
    color: var(--text-muted);
  }
  .tun-badge {
    font-size: var(--text-xs);
    color: var(--warning);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 0 var(--sp-2);
  }
</style>
