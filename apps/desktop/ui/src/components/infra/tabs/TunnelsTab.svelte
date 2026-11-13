<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errMsg } from '$lib/utils/errors';
  import { onMount } from 'svelte';
  import type { FrpConfig, FrpTunnel, Server } from '$lib/api/types';
  import { frpApi } from '$lib/api/frp';
  import { session } from '$lib/stores/session';
  import { reportError, showStatus } from '$lib/stores/statusBar';
  import { KeyRound, Pencil, Plus } from '@lucide/svelte';
  import { confirmDialog } from '../../ui/ConfirmDialog.svelte';
  import TunnelModal from '../TunnelModal.svelte';
  import Button from '../../ui/Button.svelte';
  import Panel from '../../ui/Panel.svelte';
  import Pill from '../../ui/Pill.svelte';
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
  let rotating = $state(false);

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

  async function rotateKey(): Promise<void> {
    const s = $session;
    if (!s) return;
    const ok = await confirmDialog($t('infra.tun.rotateConfirm', { name: server.name }), {
      confirmLabel: $t('infra.tun.rotate'),
    });
    if (!ok) return;
    rotating = true;
    try {
      await frpApi.rotateKey(s, server.id);
      showStatus($t('infra.tun.rotated', { name: server.name }));
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      rotating = false;
    }
  }

  onMount(load);
</script>

{#snippet toolbar()}
  <div class="tun-toolbar">
    <Button
      size="sm"
      iconLeft={Plus}
      data-action="tun-new"
      onclick={openNew}
      disabled={configs.length === 0}>{$t('infra.tun.add')}</Button
    >
    {#if $session?.isAdmin === true}
      <Button
        size="sm"
        variant="ghost"
        iconLeft={KeyRound}
        data-action="tun-rotate-key"
        onclick={rotateKey}
        disabled={rotating}>{$t('infra.tun.rotate')}</Button
      >
    {/if}
  </div>
{/snippet}

<Panel title={$t('infra.tab.tunnels')} action={toolbar} pad={6}>
  {#if !loading && configs.length === 0}
    <p class="muted">{$t('infra.tun.noConfig')}</p>
  {/if}

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
            <Pill tone="warn">{$t('infra.tun.disabled')}</Pill>
          {/if}
          <Button size="sm" variant="ghost" iconLeft={Pencil} onclick={() => openEdit(x)}
            >{$t('action.edit')}</Button
          >
        </div>
      {/each}
    </div>
  {/if}
</Panel>

<TunnelModal
  open={modalOpen}
  {editing}
  {server}
  {configs}
  onClose={() => (modalOpen = false)}
  onSaved={load}
/>

<style>
  .tun-toolbar {
    display: flex;
    gap: 6px;
  }
  .muted {
    margin: 0;
    padding: 10px;
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .tun-list {
    display: flex;
    flex-direction: column;
  }
  .tun-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 10px;
  }
  .tun-row + .tun-row {
    border-top: 1px solid var(--border);
  }
  .tun-info {
    flex: 1;
    min-width: 0;
  }
  .tun-name {
    overflow: hidden;
    color: var(--text-strong);
    font-size: var(--text-sm);
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .tun-meta {
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 12px;
  }
</style>
