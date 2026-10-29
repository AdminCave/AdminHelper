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
  import type { FrpSupervisorStatus } from '$lib/api/frp';
  import { formatDateTime } from '$lib/utils/datetime';
  import Button from '$lib/components/ui/Button.svelte';
  import FrpConfigModal from '$modals/FrpConfigModal.svelte';
  import FrpConfigPreviewModal from '$modals/FrpConfigPreviewModal.svelte';
  import FrpStatusModal from '$modals/FrpStatusModal.svelte';

  const SUPERVISOR_REFRESH_MS = 30_000;

  // The codes the server sends (supervisor_status.py). A text comes from a known code only; any
  // other value gets the generic text, so nothing the server sends is shown or used as a key.
  const STATE_TEXT = new Map([
    ['waiting', 'page.frp.supervisor.state.waiting'],
    ['running', 'page.frp.supervisor.state.running'],
    ['degraded', 'page.frp.supervisor.state.degraded'],
    ['stopped', 'page.frp.supervisor.state.stopped'],
    ['crashloop', 'page.frp.supervisor.state.crashloop'],
    ['missing', 'page.frp.supervisor.state.missing'],
    ['unreadable', 'page.frp.supervisor.state.unreadable'],
  ]);
  const REASON_TEXT = new Map([
    ['none', 'page.frp.supervisor.reason.none'],
    ['config_missing', 'page.frp.supervisor.reason.config_missing'],
    ['token_invalid', 'page.frp.supervisor.reason.token_invalid'],
    ['tls_not_forced', 'page.frp.supervisor.reason.tls_not_forced'],
    ['cert_paths', 'page.frp.supervisor.reason.cert_paths'],
    ['cert_missing', 'page.frp.supervisor.reason.cert_missing'],
    ['cert_expired', 'page.frp.supervisor.reason.cert_expired'],
    ['cert_key_mismatch', 'page.frp.supervisor.reason.cert_key_mismatch'],
    ['verify_failed', 'page.frp.supervisor.reason.verify_failed'],
    ['input_unreadable', 'page.frp.supervisor.reason.input_unreadable'],
    ['input_unstable', 'page.frp.supervisor.reason.input_unstable'],
    ['processes_left', 'page.frp.supervisor.reason.processes_left'],
  ]);
  const EVENT_TEXT = new Map([
    ['started', 'page.frp.supervisor.event.started'],
    ['applied', 'page.frp.supervisor.event.applied'],
    ['rejected', 'page.frp.supervisor.event.rejected'],
    ['stopped', 'page.frp.supervisor.event.stopped'],
    ['crashed', 'page.frp.supervisor.event.crashed'],
    ['copy_changed', 'page.frp.supervisor.event.copy_changed'],
    ['start_refused', 'page.frp.supervisor.event.start_refused'],
  ]);
  const STATE_COLOR = new Map([
    ['running', 'var(--success)'],
    ['degraded', 'var(--warning)'],
    ['crashloop', 'var(--danger)'],
    ['unreadable', 'var(--danger)'],
  ]);

  let configModalOpen = $state(false);

  let previewOpen = $state(false);
  let previewTitle = $state('');
  let previewContent = $state('');

  let statusOpen = $state(false);

  let supervisor = $state<FrpSupervisorStatus | null>(null);
  let supervisorLoaded = $state(false);
  // A slow response must not overwrite a newer one.
  let supervisorGen = 0;

  onMount(() => {
    void load();
    let timer: ReturnType<typeof setInterval> | undefined;
    // Only while the tab is visible: through the client's 401 -> refresh -> retry, a hidden tab
    // left open on this page would otherwise keep the session alive for as long as it stays open.
    function poll() {
      clearInterval(timer);
      timer = undefined;
      if (document.visibilityState === 'hidden') return;
      void refreshSupervisor();
      timer = setInterval(() => void refreshSupervisor(), SUPERVISOR_REFRESH_MS);
    }
    poll();
    document.addEventListener('visibilitychange', poll);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', poll);
    };
  });

  async function load() {
    try {
      await frpConfig.refresh();
    } catch (err) {
      showError(err);
    }
  }

  async function refreshSupervisor() {
    const gen = ++supervisorGen;
    let result: FrpSupervisorStatus | null = null;
    try {
      result = await api.supervisorStatus();
    } catch {
      // Network, 403, or 404 from a server without the route: the block turns neutral, no toast
      // every 30 s, and an earlier answer is not left standing as if it were current.
    }
    if (gen !== supervisorGen) return;
    supervisor = result;
    supervisorLoaded = true;
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

  // The text carries the FRP credentials (auth token, dashboard password, STCP secret keys); it
  // goes with the preview instead of staying until the page is left. Opening fetches it again.
  function closePreview() {
    previewOpen = false;
    previewContent = '';
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

  <div class="panel" style="margin-top:var(--sp-4)">
    <div style="font-weight:600;margin-bottom:var(--sp-2)">{$t('page.frp.supervisor.title')}</div>
    {#if !supervisorLoaded}
      <p style="margin:0;color:var(--text-muted)">{$t('state.loading')}</p>
    {:else if !supervisor}
      <p style="margin:0;color:var(--text-muted)" data-testid="frps-unavailable">
        {$t('page.frp.supervisor.unavailable')}
      </p>
    {:else}
      <div
        style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px 24px"
      >
        <div>
          <strong>{$t('page.frp.supervisor.label.state')}:</strong>
          <span
            data-testid="frps-state"
            style="color:{STATE_COLOR.get(supervisor.state) ?? 'inherit'}"
          >
            {$t(STATE_TEXT.get(supervisor.state) ?? 'page.frp.supervisor.state.unknown')}
          </span>
        </div>
        {#if supervisor.reason}
          <div>
            <strong>{$t('page.frp.supervisor.label.reason')}:</strong>
            <span data-testid="frps-reason">
              {$t(REASON_TEXT.get(supervisor.reason) ?? 'page.frp.supervisor.reason.unknown')}
            </span>
          </div>
        {/if}
        {#if supervisor.since}
          <div>
            <strong>{$t('page.frp.supervisor.label.since')}:</strong>
            <span data-testid="frps-since">{formatDateTime(supervisor.since)}</span>
          </div>
        {/if}
        {#if supervisor.lastEvent}
          <div>
            <strong>{$t('page.frp.supervisor.label.lastEvent')}:</strong>
            <span data-testid="frps-event">
              {$t(EVENT_TEXT.get(supervisor.lastEvent) ?? 'page.frp.supervisor.event.unknown')}
            </span>
            <span data-testid="frps-event-at" style="color:var(--text-muted)">
              {formatDateTime(supervisor.lastEventAt)}
            </span>
          </div>
        {/if}
      </div>
      {#if supervisor.stale}
        <p style="margin:var(--sp-2) 0 0;color:var(--warning)" data-testid="frps-stale">
          {$t('page.frp.supervisor.stale')}
        </p>
      {/if}
    {/if}
  </div>
</div>

<FrpConfigModal open={configModalOpen} editing={$frpConfig} onClose={handleConfigClose} />
<FrpConfigPreviewModal
  open={previewOpen}
  title={previewTitle}
  content={previewContent}
  onClose={closePreview}
/>
<FrpStatusModal open={statusOpen} onClose={() => (statusOpen = false)} />
