<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '$lib/i18n';
  import { formatDate } from '$lib/utils/datetime';
  import * as certificatesApi from '$lib/api/certificates';
  import { showError } from '$lib/stores/notifications';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import type { CertificateOverview, ExpiryStatus } from '$lib/api/types';

  // Literal keys, so the i18n test sees every one of them in use.
  const STATUS_KEY: Record<ExpiryStatus, string> = {
    ok: 'page.certificates.status.ok',
    warning: 'page.certificates.status.warning',
    critical: 'page.certificates.status.critical',
  };

  let data = $state<CertificateOverview | null>(null);
  let loading = $state(true);

  onMount(async () => {
    try {
      data = await certificatesApi.overview();
    } catch (err) {
      showError(err);
    } finally {
      loading = false;
    }
  });

  function daysText(days: number): string {
    return days < 0 ? $t('page.certificates.expired') : String(days);
  }
</script>

<div class="page active">
  <div class="page-header">
    <div>
      <div class="page-title">{$t('page.certificates.title')}</div>
      <div class="page-subtitle">{$t('page.certificates.subtitle')}</div>
    </div>
  </div>

  {#if loading}
    <div class="panel"><EmptyState message={$t('page.certificates.loading')} /></div>
  {:else if data}
    <div class="panel" data-section="infrastructure">
      <h3>{$t('page.certificates.infra')}</h3>
      {#if data.infrastructure.length === 0}
        <EmptyState message={$t('page.certificates.infra.empty')} />
      {:else}
        <table class="data-table">
          <thead>
            <tr>
              <th>{$t('page.certificates.col.name')}</th>
              <th>{$t('page.certificates.col.subject')}</th>
              <th>{$t('page.certificates.col.notAfter')}</th>
              <th>{$t('page.certificates.col.daysLeft')}</th>
              <th>{$t('page.certificates.col.status')}</th>
            </tr>
          </thead>
          <tbody>
            {#each data.infrastructure as c (c.name)}
              <tr>
                <td class="mono">{c.name}</td>
                <td class="subject">{c.subject}</td>
                <td>{formatDate(c.not_after)}</td>
                <td>{daysText(c.days_left)}</td>
                <td><span class="light {c.status}">{$t(STATUS_KEY[c.status])}</span></td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>

    <div class="panel" data-section="agents">
      <h3>{$t('page.certificates.agents')}</h3>
      {#if data.agents.length === 0}
        <EmptyState message={$t('page.certificates.agents.empty')} />
      {:else}
        <table class="data-table">
          <thead>
            <tr>
              <th>{$t('page.certificates.col.server')}</th>
              <th>{$t('page.certificates.col.notAfter')}</th>
              <th>{$t('page.certificates.col.daysLeft')}</th>
              <th>{$t('page.certificates.col.status')}</th>
            </tr>
          </thead>
          <tbody>
            {#each data.agents as a (a.fingerprint)}
              <tr>
                <td>{a.server_name ?? a.server_id}</td>
                <td>{formatDate(a.not_after)}</td>
                <td>{daysText(a.days_left)}</td>
                <td><span class="light {a.status}">{$t(STATUS_KEY[a.status])}</span></td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  {/if}
</div>

<style>
  .panel + .panel {
    margin-top: 16px;
  }
  h3 {
    margin: 0 0 8px;
  }
  .mono {
    font-family: var(--font-mono, monospace);
    font-size: 0.9em;
  }
  .subject {
    overflow-wrap: anywhere;
  }
  .light {
    font-weight: 600;
  }
  .light.warning {
    color: var(--warning);
  }
  .light.critical {
    color: var(--danger);
  }
</style>
