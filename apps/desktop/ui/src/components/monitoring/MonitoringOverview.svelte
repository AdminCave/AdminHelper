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
    monitoringServerSearch,
    setOverviewView,
    setServerSearch,
    setTab,
  } from '$lib/stores/monitoring';
  import { LayoutGrid, PanelLeft, TriangleAlert } from '@lucide/svelte';
  import MonSummaryCards from './MonSummaryCards.svelte';
  import MonServerList from './MonServerList.svelte';
  import MonServerGrid from './MonServerGrid.svelte';
  import MonServerDashboard from './MonServerDashboard.svelte';
  import Button from '../ui/Button.svelte';
  import Callout from '../ui/Callout.svelte';
  import EmptyState from '../ui/EmptyState.svelte';
  import SearchField from '../ui/SearchField.svelte';
  import Segmented from '../ui/Segmented.svelte';
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
  let viewOptions = $derived([
    { value: 'list', label: $t('monitoring.view.list'), icon: PanelLeft },
    { value: 'grid', label: $t('monitoring.view.grid'), icon: LayoutGrid },
  ]);
  let missingNames = $derived($serversWithoutChecks.map((s) => s.name).join(', '));

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

<div class="mon-overview">
  {#if $monitoringError}
    <div role="alert">
      <Callout tone="danger">
        {$t('error.monitoring', { message: $monitoringError })}
        {#snippet action()}
          <Button size="sm" variant="secondary" onclick={() => void loadMonitoring()}
            >{$t('action.retry')}</Button
          >
        {/snippet}
      </Callout>
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
      <Button size="sm" onclick={() => setTab('templates')}>{$t('monitoring.empty.cta')}</Button>
    </EmptyState>
  {:else if $monitoringChecks.length > 0}
    {#if $serversWithoutChecks.length > 0}
      <div class="mon-bulk-banner">
        <Callout tone="warning" icon={TriangleAlert}>
          <span class="mon-bulk-text"
            ><strong
              >{$t('monitoring.bulk.banner', {
                count: String($serversWithoutChecks.length),
              })}</strong
            ><span class="mon-bulk-names">: {missingNames}</span></span
          >
          {#snippet action()}
            <Button size="sm" data-action="bulk-assign" onclick={openBulkAssign}
              >{$t('monitoring.bulk.cta')}</Button
            >
          {/snippet}
        </Callout>
      </div>
    {/if}
    <MonSummaryCards />

    <div class="mon-overview-toolbar">
      <Segmented
        options={viewOptions}
        value={$overviewView}
        label={$t('monitoring.view.toggleLabel')}
        onChange={(v) => setOverviewView(v as 'list' | 'grid')}
      />
      <div class="mon-overview-search">
        <SearchField
          size="sm"
          value={$monitoringServerSearch}
          placeholder={$t('monitoring.serverList.search')}
          label={$t('monitoring.serverList.search')}
          oninput={(e) => setServerSearch((e.currentTarget as HTMLInputElement).value)}
          onClear={() => setServerSearch('')}
        />
      </div>
      <span class="mon-refresh-hint">{$t('monitoring.autoRefresh')}</span>
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
</div>

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
    <Button variant="secondary" onclick={() => (bulkOpen = false)} disabled={bulkBusy}>
      {$t('action.cancel')}
    </Button>
    <Button
      onclick={submitBulkAssign}
      loading={bulkBusy}
      disabled={bulkBusy || !bulkTemplateId || bulkSelected.length === 0}
    >
      {$t('monitoring.bulk.assign', { count: String(bulkSelected.length) })}
    </Button>
  {/snippet}
</Modal>

<style>
  .mon-overview {
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  .mon-bulk-text {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mon-bulk-names {
    color: var(--text-muted);
  }
  .mon-overview-toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px;
  }
  .mon-overview-search {
    width: 240px;
  }
  .mon-refresh-hint {
    margin-left: auto;
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 11.5px;
  }
  .mon-split {
    display: grid;
    grid-template-columns: 280px minmax(0, 1fr);
    gap: 18px;
    align-items: start;
  }
  .mon-split-sidebar {
    position: sticky;
    top: 12px;
    max-height: calc(100vh - 140px);
    overflow-y: auto;
  }
  .mon-split-main {
    min-width: 0;
  }
  @media (max-width: 1200px) {
    .mon-split {
      grid-template-columns: 210px minmax(0, 1fr);
    }
  }
  @media (max-width: 900px) {
    .mon-split {
      grid-template-columns: 1fr;
    }
    .mon-split-sidebar {
      position: static;
      max-height: none;
    }
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
    background: var(--surface);
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
