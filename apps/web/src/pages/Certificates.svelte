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
  import Panel from '$lib/components/ui/Panel.svelte';
  import Pill from '$lib/components/ui/Pill.svelte';
  import type { CertificateOverview, ExpiryStatus } from '$lib/api/types';

  // Literal keys, so the i18n test sees every one of them in use.
  const STATUS_KEY: Record<ExpiryStatus, string> = {
    ok: 'page.certificates.status.ok',
    warning: 'page.certificates.status.warning',
    critical: 'page.certificates.status.critical',
  };
  const STATUS_TONE: Record<ExpiryStatus, 'ok' | 'warn' | 'crit'> = {
    ok: 'ok',
    warning: 'warn',
    critical: 'crit',
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
    <Panel pad={0}><EmptyState framed={false} message={$t('page.certificates.loading')} /></Panel>
  {:else if data}
    <div data-section="infrastructure">
      <Panel title={$t('page.certificates.infra')} pad={0}>
        {#if data.infrastructure.length === 0}
          <EmptyState framed={false} message={$t('page.certificates.infra.empty')} />
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
                  <td data-status={c.status}>
                    <Pill tone={STATUS_TONE[c.status]}>{$t(STATUS_KEY[c.status])}</Pill>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </Panel>
    </div>

    <div data-section="agents">
      <Panel title={$t('page.certificates.agents')} pad={0}>
        {#if data.agents.length === 0}
          <EmptyState framed={false} message={$t('page.certificates.agents.empty')} />
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
                  <td data-status={a.status}>
                    <Pill tone={STATUS_TONE[a.status]}>{$t(STATUS_KEY[a.status])}</Pill>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </Panel>
    </div>
  {/if}
</div>

<style>
  .mono {
    font-family: var(--font-mono);
    font-size: 0.9em;
  }
  .subject {
    overflow-wrap: anywhere;
  }
</style>
