<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import {
    monitoringChecks,
    monitoringError,
    monitoringHasLoaded,
    monitoringTemplates,
    overviewView,
    serversWithoutChecks,
    assignTemplateToServers,
    loadMonitoring,
    loadTemplates,
    setOverviewView,
    setTab,
  } from '$lib/stores/monitoring';
  import MonSummaryCards from './MonSummaryCards.svelte';
  import MonServerList from './MonServerList.svelte';
  import MonServerGrid from './MonServerGrid.svelte';
  import MonServerDashboard from './MonServerDashboard.svelte';
  import EmptyState from '../ui/EmptyState.svelte';
  import Modal from '../ui/Modal.svelte';
  import { t } from '$lib/i18n';

  // Skeleton from the very first paint until the FIRST load resolved —
  // hasLoaded (not the data, not `loading`) is the gate: the 30s auto-refresh
  // can't flicker the empty/error states away, and the cold-start window
  // before onMount's load kicks in shows the skeleton instead of a false
  // "no checks configured" flash.
  let firstLoad = $derived(!$monitoringHasLoaded);

  // Bulk-assign CTA (T32): shipped built-ins first, then by name — the picker
  // should lead with the templates a fresh install actually has.
  let sortedTemplates = $derived(
    [...$monitoringTemplates].sort(
      (a, b) =>
        Number(Boolean(b.builtinSlug)) - Number(Boolean(a.builtinSlug)) ||
        a.name.localeCompare(b.name),
    ),
  );
  let bulkOpen = $state(false);
  let bulkBusy = $state(false);
  let bulkTemplateId = $state('');
  let bulkSelected = $state<string[]>([]);

  function openBulkAssign(): void {
    bulkSelected = $serversWithoutChecks.map((s) => s.id);
    bulkTemplateId = sortedTemplates[0]?.id ?? '';
    bulkOpen = true;
    // Refresh in the background; the picker updates reactively.
    void loadTemplates().then(() => {
      // Re-validate against the refreshed list: a stale selection (template
      // deleted, or the refresh failed and emptied the store) must not leave
      // the assign button armed with a dead ID.
      if (!sortedTemplates.some((tpl) => tpl.id === bulkTemplateId)) {
        bulkTemplateId = sortedTemplates[0]?.id ?? '';
      }
    });
  }

  async function submitBulkAssign(): Promise<void> {
    const targets = $serversWithoutChecks.filter((s) => bulkSelected.includes(s.id));
    if (!bulkTemplateId || targets.length === 0) return;
    bulkBusy = true;
    const ok = await assignTemplateToServers(bulkTemplateId, targets);
    bulkBusy = false;
    if (ok) {
      bulkOpen = false;
      void loadMonitoring();
    }
  }
</script>

{#if $monitoringError}
  <div class="mon-error-banner" role="alert">
    <span class="mon-error-text">{$t('error.monitoring', { message: $monitoringError })}</span>
    <button class="btn small" onclick={() => void loadMonitoring()}>{$t('action.retry')}</button>
  </div>
{/if}

{#if firstLoad}
  <div class="mon-skeleton" aria-hidden="true">
    <div class="mon-skeleton-cards">
      {#each [0, 1, 2, 3] as i (i)}
        <div class="mon-skeleton-block card"></div>
      {/each}
    </div>
    <div class="mon-skeleton-split">
      <div class="mon-skeleton-block sidebar"></div>
      <div class="mon-skeleton-block main"></div>
    </div>
  </div>
{:else if $monitoringChecks.length === 0 && !$monitoringError}
  <EmptyState message={$t('monitoring.empty.noChecks')}>
    <button class="btn primary small" onclick={() => setTab('templates')}>
      {$t('monitoring.empty.cta')}
    </button>
  </EmptyState>
{:else if $monitoringChecks.length > 0}
  {#if $serversWithoutChecks.length > 0}
    <div class="mon-bulk-banner">
      <span class="mon-bulk-text"
        >{$t('monitoring.bulk.banner', { count: String($serversWithoutChecks.length) })}</span
      >
      <button class="btn primary small" onclick={openBulkAssign}>
        {$t('monitoring.bulk.cta')}
      </button>
    </div>
  {/if}
  <MonSummaryCards />

  <div class="mon-view-toggle" role="group" aria-label={$t('monitoring.view.toggleLabel')}>
    <button
      class="btn small"
      class:primary={$overviewView === 'list'}
      aria-pressed={$overviewView === 'list'}
      onclick={() => setOverviewView('list')}>{$t('monitoring.view.list')}</button
    >
    <button
      class="btn small"
      class:primary={$overviewView === 'grid'}
      aria-pressed={$overviewView === 'grid'}
      onclick={() => setOverviewView('grid')}>{$t('monitoring.view.grid')}</button
    >
  </div>

  {#if $overviewView === 'grid'}
    <MonServerGrid />
  {:else}
    <div class="mon-split">
      <aside class="mon-split-sidebar">
        <MonServerList />
      </aside>
      <section class="mon-split-main">
        <MonServerDashboard />
      </section>
    </div>
  {/if}
{/if}

<Modal
  open={bulkOpen}
  title={$t('monitoring.bulk.title')}
  width="480px"
  onClose={() => {
    if (!bulkBusy) bulkOpen = false;
  }}
>
  {#if sortedTemplates.length === 0}
    <div class="mon-bulk-empty">{$t('monitoring.bulk.noTemplates')}</div>
  {:else}
    <label class="field">
      <span class="field-label">{$t('monitoring.bulk.template')}</span>
      <select bind:value={bulkTemplateId}>
        {#each sortedTemplates as tpl (tpl.id)}
          <option value={tpl.id}>{tpl.name}</option>
        {/each}
      </select>
    </label>
    <div class="mon-bulk-servers">
      {#each $serversWithoutChecks as srv (srv.id)}
        <label class="mon-bulk-server">
          <input type="checkbox" value={srv.id} bind:group={bulkSelected} />
          <span>{srv.name}</span>
        </label>
      {/each}
    </div>
  {/if}

  {#snippet footer()}
    <button class="btn" onclick={() => (bulkOpen = false)} disabled={bulkBusy}>
      {$t('action.cancel')}
    </button>
    <button
      class="btn primary"
      onclick={submitBulkAssign}
      disabled={bulkBusy || !bulkTemplateId || bulkSelected.length === 0}
    >
      {$t('monitoring.bulk.assign', { count: String(bulkSelected.length) })}
    </button>
  {/snippet}
</Modal>

<style>
  .mon-view-toggle {
    display: flex;
    gap: var(--sp-2);
    margin: var(--sp-4) 0;
  }
  .mon-bulk-banner {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-3) var(--sp-4);
    margin-bottom: var(--sp-4);
    border: 1px solid var(--warning);
    border-radius: var(--radius-md);
    background: color-mix(in srgb, var(--warning) 10%, transparent);
    font-size: 13px;
  }
  .mon-bulk-text {
    flex: 1;
    min-width: 0;
  }
  .mon-bulk-servers {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    margin-top: var(--sp-3);
    max-height: 260px;
    overflow-y: auto;
  }
  .mon-bulk-server {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    font-size: 13px;
  }
  .mon-bulk-empty {
    color: var(--text-muted);
    font-size: 13px;
  }
  /* Same local form styling as the other monitoring modals (MaintenanceModal
     et al.) — the global .field is the uppercase filter-bar variant. */
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .field-label {
    font-size: 12px;
    color: var(--text-muted);
  }
  .field select {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-2) var(--sp-3);
    font-size: 13px;
    font-family: inherit;
  }
  .mon-error-banner {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-3) var(--sp-4);
    margin-bottom: var(--sp-4);
    border: 1px solid var(--danger);
    border-radius: var(--radius-md);
    background: color-mix(in srgb, var(--danger) 10%, transparent);
    font-size: 13px;
  }
  .mon-error-text {
    flex: 1;
    min-width: 0;
  }
  .mon-skeleton {
    display: flex;
    flex-direction: column;
    gap: var(--sp-4);
  }
  .mon-skeleton-cards {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: var(--sp-4);
  }
  .mon-skeleton-split {
    display: grid;
    grid-template-columns: 280px 1fr;
    gap: var(--sp-4);
  }
  .mon-skeleton-block {
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--bg-panel);
    animation: mon-skeleton-pulse 1.2s ease-in-out infinite;
  }
  .mon-skeleton-block.card {
    height: 72px;
  }
  .mon-skeleton-block.sidebar {
    height: 320px;
  }
  .mon-skeleton-block.main {
    height: 320px;
  }
  @keyframes mon-skeleton-pulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.45;
    }
  }
</style>
