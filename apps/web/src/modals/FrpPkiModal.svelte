<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t, language } from '$lib/i18n';
  import { showToast } from '$lib/stores/notifications';
  import { confirmDialog } from '$lib/components/ui/ConfirmDialog.svelte';
  import * as api from '$lib/api/frp';
  import type { FrpPkiStatus } from '$lib/api/types';

  interface Props {
    open: boolean;
    onClose: () => void;
  }

  let { open, onClose }: Props = $props();

  let status = $state<FrpPkiStatus | null>(null);
  let loading = $state(false);
  let clientName = $state('');

  const locale = $derived($language === 'de' ? 'de-DE' : 'en-GB');

  $effect(() => {
    if (open) {
      clientName = '';
      void refresh();
    } else {
      status = null;
    }
  });

  async function refresh() {
    loading = true;
    try {
      status = await api.pkiStatus();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    } finally {
      loading = false;
    }
  }

  function formatDate(iso: string | null | undefined): string {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleDateString(locale);
    } catch {
      return '';
    }
  }

  async function generateCA() {
    if (
      !(await confirmDialog($t('confirm.pki.regenerateCA'), { confirmLabel: $t('action.confirm') }))
    )
      return;
    try {
      const result = await api.pkiGenerateCA();
      showToast($t('toast.pki.caCreated', { date: formatDate(result.expiry) }));
      await refresh();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  async function generateServerCert() {
    try {
      const result = await api.pkiGenerateServerCert();
      showToast($t('toast.pki.serverCertCreated', { name: result.commonName }));
      await refresh();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  async function generateClientCert() {
    const nm = clientName.trim();
    if (!nm) {
      showToast($t('toast.pki.enterClientName'), 'error');
      return;
    }
    try {
      const result = await api.pkiGenerateClientCert(nm);
      showToast($t('toast.pki.clientCertCreated', { name: result.commonName }));
      clientName = '';
      await refresh();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  async function downloadFile(filename: string) {
    try {
      const blob = await api.pkiDownload(filename);
      triggerDownload(blob, filename);
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  async function downloadBundle(name: string) {
    try {
      const blob = await api.pkiDownloadBundle(name);
      triggerDownload(blob, `${name}-pki.zip`);
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  function triggerDownload(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }
</script>

<Modal {open} title={$t('frp.pki.title')} width="820px" {onClose}>
  {#if loading || !status}
    <p style="color:var(--text-muted)">{$t('state.loading')}</p>
  {:else}
    <div style="display:flex;flex-direction:column;gap:16px">
      <div style="background:var(--bg-elevated);padding:12px;border-radius:var(--radius-sm)">
        <h4 style="margin:0 0 8px">{$t('frp.pki.caTitle')}</h4>
        {#if status.caExists}
          <p style="margin:0;color:var(--text-muted)">
            {$t('frp.pki.caValidUntil')} <strong>{formatDate(status.caExpiry)}</strong>
          </p>
          <div style="display:flex;gap:8px;margin-top:8px">
            <button class="btn small" onclick={() => downloadFile('ca.crt')}>
              {$t('frp.pki.caDownload')}
            </button>
            <button class="btn small primary" onclick={generateCA}>
              {$t('frp.pki.caRegenerate')}
            </button>
          </div>
        {:else}
          <p style="margin:0;color:var(--text-muted)">{$t('frp.pki.caNotExist')}</p>
          <button class="btn small primary" style="margin-top:8px" onclick={generateCA}>
            {$t('frp.pki.caCreate')}
          </button>
        {/if}
      </div>

      <div style="background:var(--bg-elevated);padding:12px;border-radius:var(--radius-sm)">
        <h4 style="margin:0 0 8px">{$t('frp.pki.serverCertTitle')}</h4>
        {#if status.serverCertExists}
          <p style="margin:0;color:var(--text-muted)">
            {$t('frp.pki.caValidUntil')} <strong>{formatDate(status.serverCertExpiry)}</strong>
          </p>
          <div style="display:flex;gap:8px;margin-top:8px">
            <button class="btn small" onclick={() => downloadFile('frps.crt')}>frps.crt</button>
            <button class="btn small" onclick={() => downloadFile('frps.key')}>frps.key</button>
            {#if status.caExists}
              <button class="btn small primary" onclick={generateServerCert}>
                {$t('frp.pki.serverCertRegenerate')}
              </button>
            {/if}
          </div>
        {:else}
          <p style="margin:0;color:var(--text-muted)">{$t('frp.pki.serverCertNotExist')}</p>
          {#if status.caExists}
            <button class="btn small" style="margin-top:8px" onclick={generateServerCert}>
              {$t('frp.pki.serverCertGenerate')}
            </button>
          {/if}
        {/if}
      </div>

      <div style="background:var(--bg-elevated);padding:12px;border-radius:var(--radius-sm)">
        <h4 style="margin:0 0 8px">{$t('frp.pki.clientCertsTitle')}</h4>
        {#if status.clientCerts.length > 0}
          <table class="data-table" style="margin:0">
            <thead>
              <tr>
                <th>{$t('label.name')}</th>
                <th>{$t('frp.pki.expiry')}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {#each status.clientCerts as c (c.name)}
                <tr>
                  <td>{c.name}</td>
                  <td>{formatDate(c.expiry)}</td>
                  <td style="text-align:right;white-space:nowrap">
                    <button class="btn small ghost" onclick={() => downloadBundle(c.name)}
                      >ZIP</button
                    >
                    <button class="btn small ghost" onclick={() => downloadFile(`${c.name}.crt`)}
                      >crt</button
                    >
                    <button class="btn small ghost" onclick={() => downloadFile(`${c.name}.key`)}
                      >key</button
                    >
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {:else}
          <p style="margin:0;color:var(--text-muted)">{$t('frp.pki.clientCertsNone')}</p>
        {/if}
        {#if status.caExists}
          <div style="display:flex;gap:8px;margin-top:8px;align-items:center">
            <input
              type="text"
              placeholder={$t('frp.pki.clientNamePlaceholder')}
              style="flex:1"
              bind:value={clientName}
            />
            <button class="btn small" onclick={generateClientCert}>
              {$t('frp.pki.generate')}
            </button>
          </div>
        {/if}
      </div>
    </div>
  {/if}
  {#snippet footer()}
    <Button variant="primary" onclick={onClose}>{$t('action.close')}</Button>
  {/snippet}
</Modal>
