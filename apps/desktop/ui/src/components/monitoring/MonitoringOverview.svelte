<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import {
    monitoringChecks,
    monitoringError,
    monitoringHasLoaded,
    overviewView,
    loadMonitoring,
    setOverviewView,
    setTab,
  } from '$lib/stores/monitoring';
  import MonSummaryCards from './MonSummaryCards.svelte';
  import MonServerList from './MonServerList.svelte';
  import MonServerGrid from './MonServerGrid.svelte';
  import MonServerDashboard from './MonServerDashboard.svelte';
  import EmptyState from '../ui/EmptyState.svelte';
  import { t } from '$lib/i18n';

  // Skeleton from the very first paint until the FIRST load resolved —
  // hasLoaded (not the data, not `loading`) is the gate: the 30s auto-refresh
  // can't flicker the empty/error states away, and the cold-start window
  // before onMount's load kicks in shows the skeleton instead of a false
  // "no checks configured" flash.
  let firstLoad = $derived(!$monitoringHasLoaded);
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

<style>
  .mon-view-toggle {
    display: flex;
    gap: var(--sp-2);
    margin: var(--sp-4) 0;
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
