<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '$lib/i18n';
  import { frpConfig } from '$lib/stores/frp';
  import { showToast, showError } from '$lib/stores/notifications';
  import * as api from '$lib/api/frp';
  import Button from '$lib/components/ui/Button.svelte';
  import FrpConfigModal from '$modals/FrpConfigModal.svelte';
  import FrpConfigPreviewModal from '$modals/FrpConfigPreviewModal.svelte';
  import FrpStatusModal from '$modals/FrpStatusModal.svelte';

  let configModalOpen = $state(false);

  let previewOpen = $state(false);
  let previewTitle = $state('');
  let previewContent = $state('');

  let statusOpen = $state(false);

  onMount(() => {
    void load();
  });

  async function load() {
    try {
      await frpConfig.refresh();
    } catch (err) {
      showError(err);
    }
  }

  async function handleConfigClose() {
    configModalOpen = false;
  }

  async function showPreview(title: string, fetcher: () => Promise<string>) {
    try {
      const content = await fetcher();
      previewTitle = title;
      previewContent = content;
      previewOpen = true;
    } catch (err) {
      showError(err);
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
      // Revoking synchronously after click() can abort the download before the browser has read the
      // blob (especially larger ZIPs); defer it so the download starts first (4.146).
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      showToast($t('toast.frp.zipDownloaded'));
    } catch (err) {
      showError(err);
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
        <Button variant="ghost" onclick={() => (statusOpen = true)}>
          {$t('page.frp.status')}
        </Button>
      {/if}
    </div>
  </div>

  <div class="panel">
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
          <strong>mTLS:</strong>
          <span style="color:var(--success)">{$t('page.frp.mtlsActive')}</span>
        </div>
      </div>
    {:else}
      <p style="margin:0;color:var(--text-muted)">{$t('page.frp.noConfig')}</p>
    {/if}
  </div>
</div>

<FrpConfigModal open={configModalOpen} editing={$frpConfig} onClose={handleConfigClose} />
<FrpConfigPreviewModal
  open={previewOpen}
  title={previewTitle}
  content={previewContent}
  onClose={() => (previewOpen = false)}
/>
<FrpStatusModal open={statusOpen} onClose={() => (statusOpen = false)} />
