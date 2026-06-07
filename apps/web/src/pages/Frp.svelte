<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '$lib/i18n';
  import { frpConfig, frpTunnels } from '$lib/stores/frp';
  import { servers as serversStore } from '$lib/stores/servers';
  import { showToast } from '$lib/stores/notifications';
  import { extractAllTags } from '$lib/utils/tags';
  import { confirmDialog } from '$lib/components/ui/ConfirmDialog.svelte';
  import * as api from '$lib/api/frp';
  import Button from '$lib/components/ui/Button.svelte';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import FrpConfigModal from '$modals/FrpConfigModal.svelte';
  import TunnelModal from '$modals/TunnelModal.svelte';
  import FrpConfigPreviewModal from '$modals/FrpConfigPreviewModal.svelte';
  import FrpPkiModal from '$modals/FrpPkiModal.svelte';
  import FrpStatusModal from '$modals/FrpStatusModal.svelte';
  import type { FrpTunnel } from '$lib/api/types';

  let search = $state('');
  let tagFilter = $state('');

  let configModalOpen = $state(false);
  let tunnelModalOpen = $state(false);
  let editingTunnel = $state<FrpTunnel | null>(null);

  let previewOpen = $state(false);
  let previewTitle = $state('');
  let previewContent = $state('');

  let pkiOpen = $state(false);
  let statusOpen = $state(false);

  onMount(() => {
    void load();
  });

  async function load() {
    try {
      await Promise.all([
        frpConfig.refresh(),
        frpTunnels.refresh(),
        $serversStore.length === 0 ? serversStore.refresh() : Promise.resolve(),
      ]);
    } catch (err) {
      showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
    }
  }

  const allTags = $derived(extractAllTags($frpTunnels));

  const filtered = $derived.by(() => {
    const q = search.toLowerCase();
    return $frpTunnels.filter((tn) => {
      if (tagFilter && !(tn.tags ?? []).includes(tagFilter)) return false;
      if (!q) return true;
      const server = $serversStore.find((s) => s.id === tn.serverId);
      const fields = [
        tn.name,
        tn.tunnelType,
        tn.protocol,
        (tn.tags ?? []).join(' '),
        `${tn.localIp}:${tn.localPort}`,
        String(tn.visitorPort ?? ''),
        tn.customDomains ?? '',
        server?.name ?? '',
        server?.hostname ?? '',
      ].map((f) => f.toLowerCase());
      return fields.some((f) => f.includes(q));
    });
  });

  const grouped = $derived.by(() => {
    // eslint-disable-next-line svelte/prefer-svelte-reactivity -- transient builder inside $derived.by, not reactive state
    const map = new Map<string, FrpTunnel[]>();
    filtered.forEach((tn) => {
      const sid = tn.serverId || '__none__';
      if (!map.has(sid)) map.set(sid, []);
      map.get(sid)!.push(tn);
    });
    return [...map.entries()];
  });

  async function handleConfigClose() {
    configModalOpen = false;
  }

  function openTunnelCreate() {
    if (!$frpConfig) {
      showToast($t('page.frp.createConfigFirst'), 'error');
      return;
    }
    editingTunnel = null;
    tunnelModalOpen = true;
  }

  function openTunnelEdit(tn: FrpTunnel) {
    editingTunnel = tn;
    tunnelModalOpen = true;
  }

  async function handleTunnelClose() {
    tunnelModalOpen = false;
    editingTunnel = null;
  }

  async function removeTunnel(tn: FrpTunnel) {
    if (!(await confirmDialog($t('confirm.tunnel.delete'), { confirmLabel: $t('action.delete') })))
      return;
    try {
      await frpTunnels.remove(tn.id);
      showToast($t('toast.tunnel.deleted'));
    } catch (err) {
      showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
    }
  }

  async function showPreview(title: string, fetcher: () => Promise<string>) {
    try {
      const content = await fetcher();
      previewTitle = title;
      previewContent = content;
      previewOpen = true;
    } catch (err) {
      showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
    }
  }

  async function downloadBulkZip() {
    try {
      const blob = await api.getBulkZip();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'frp-configs.zip';
      a.click();
      URL.revokeObjectURL(url);
      showToast($t('toast.frp.zipDownloaded'));
    } catch (err) {
      showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
    }
  }
</script>

<div class="page active">
  <div class="page-header">
    <div>
      <div class="page-title">{$t('page.frp.title')}</div>
      <div class="page-subtitle">{$t('page.frp.subtitle')}</div>
    </div>
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <select class="filter-select" bind:value={tagFilter}>
        <option value="">{$t('label.allTags')}</option>
        {#each allTags as tag (tag)}
          <option value={tag}>{tag}</option>
        {/each}
      </select>
      <input
        type="search"
        class="search-input"
        placeholder={$t('action.searchDots')}
        bind:value={search}
      />
      <Button variant="ghost" onclick={() => (configModalOpen = true)}>
        {$frpConfig ? $t('page.frp.editConfig') : $t('page.frp.createConfig')}
      </Button>
      {#if $frpConfig}
        <Button variant="ghost" onclick={() => showPreview('frps.toml', api.getFrpsToml)}>
          frps.toml
        </Button>
        <Button variant="ghost" onclick={() => showPreview('visitor.toml', api.getVisitorToml)}>
          visitor.toml
        </Button>
        <Button variant="ghost" onclick={downloadBulkZip}>
          {$t('page.frp.bulkZip')}
        </Button>
        <Button variant="ghost" onclick={() => (pkiOpen = true)}>PKI</Button>
        <Button variant="ghost" onclick={() => (statusOpen = true)}>
          {$t('page.frp.status')}
        </Button>
      {/if}
      <Button variant="primary" onclick={openTunnelCreate}>
        {$t('page.frp.addTunnel')}
      </Button>
    </div>
  </div>

  <div class="panel" style="margin-bottom:12px">
    {#if $frpConfig}
      <div
        style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px 24px"
      >
        <div><strong>{$t('label.name')}:</strong> {$frpConfig.name}</div>
        <div><strong>{$t('modal.frpConfig.serverAddr')}:</strong> {$frpConfig.serverAddr}</div>
        <div><strong>{$t('modal.frpConfig.bindPort')}:</strong> {$frpConfig.bindPort}</div>
        {#if $frpConfig.vhostHttpsPort}
          <div><strong>HTTPS:</strong> {$frpConfig.vhostHttpsPort}</div>
        {/if}
        {#if $frpConfig.subdomainHost}
          <div><strong>Subdomain:</strong> {$frpConfig.subdomainHost}</div>
        {/if}
        {#if $frpConfig.dashboardPort}
          <div><strong>Dashboard:</strong> :{$frpConfig.dashboardPort}</div>
        {/if}
        <div>
          <strong>mTLS:</strong> <span style="color:#22c55e">{$t('page.frp.mtlsActive')}</span>
        </div>
      </div>
    {:else}
      <p style="margin:0;color:var(--text-muted)">{$t('page.frp.noConfig')}</p>
    {/if}
  </div>

  <div class="panel" style="display:flex;flex-direction:column;gap:12px">
    {#if filtered.length === 0}
      <EmptyState message={$t('page.frp.empty')} />
    {:else}
      {#each grouped as [sid, tunnels] (sid)}
        {@const server = $serversStore.find((s) => s.id === sid)}
        <div class="server-card">
          <div class="server-card-header" style="cursor:default">
            <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0">
              <div style="min-width:0">
                <strong>{server ? server.name : $t('page.frp.unknownServer')}</strong>
                {#if server}
                  <span style="color:var(--text-muted);font-size:13px;margin-left:8px">
                    {server.hostname}
                  </span>
                {/if}
              </div>
              <span style="color:var(--text-muted);font-size:12px;flex-shrink:0">
                {$t('page.frp.tunnelCount', { count: tunnels.length })}
              </span>
            </div>
            <div style="display:flex;gap:6px;flex-shrink:0">
              {#if server}
                <button
                  class="btn small ghost"
                  onclick={() =>
                    showPreview(`frpc.toml (${server.name})`, () => api.getFrpcToml(server.id))}
                >
                  frpc.toml
                </button>
              {/if}
            </div>
          </div>
          <div class="server-card-body">
            <table class="data-table" style="margin:0">
              <thead>
                <tr>
                  <th></th>
                  <th>{$t('label.type')}</th>
                  <th>{$t('label.name')}</th>
                  <th>{$t('monitor.cfg.target')}</th>
                  <th>Visitor / Domain</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {#each tunnels as tn (tn.id)}
                  <tr>
                    <td>
                      {#if tn.enabled}
                        <span style="color:#22c55e" title={$t('action.enable')}>&#x25CF;</span>
                      {:else}
                        <span style="color:#ef4444" title={$t('action.disable')}>&#x25CF;</span>
                      {/if}
                    </td>
                    <td>
                      {#if tn.tunnelType === 'stcp'}
                        <span class="badge badge-ssh">STCP</span>
                      {:else}
                        <span class="badge badge-web">HTTPS</span>
                      {/if}
                      <span class="badge">{tn.protocol.toUpperCase()}</span>
                    </td>
                    <td>
                      <strong>{tn.name}</strong>
                      {#if (tn.tags ?? []).length}
                        {#each tn.tags ?? [] as tag (tag)}
                          <span class="tag" style="font-size:10px;margin-left:4px">{tag}</span>
                        {/each}
                      {/if}
                    </td>
                    <td>{tn.localIp}:{tn.localPort}</td>
                    <td
                      style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                    >
                      {tn.visitorPort ? `Visitor :${tn.visitorPort}` : (tn.customDomains ?? '–')}
                    </td>
                    <td style="text-align:right;white-space:nowrap">
                      <button class="btn small" onclick={() => openTunnelEdit(tn)}>
                        {$t('action.edit')}
                      </button>
                      <button class="btn small ghost" onclick={() => removeTunnel(tn)}>
                        {$t('action.delete')}
                      </button>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        </div>
      {/each}
    {/if}
  </div>
</div>

<FrpConfigModal open={configModalOpen} editing={$frpConfig} onClose={handleConfigClose} />
{#if $frpConfig}
  <TunnelModal
    open={tunnelModalOpen}
    editing={editingTunnel}
    config={$frpConfig}
    onClose={handleTunnelClose}
  />
{/if}
<FrpConfigPreviewModal
  open={previewOpen}
  title={previewTitle}
  content={previewContent}
  onClose={() => (previewOpen = false)}
/>
<FrpPkiModal open={pkiOpen} onClose={() => (pkiOpen = false)} />
<FrpStatusModal open={statusOpen} onClose={() => (statusOpen = false)} />
