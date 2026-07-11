<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '$lib/i18n';
  import { formatDateTime } from '$lib/utils/datetime';
  import * as auditApi from '$lib/api/audit';
  import { showError } from '$lib/stores/notifications';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import type { AuditEntry } from '$lib/api/types';

  // Bound at one page worth of recent activity; the trail can grow large, so we
  // never fetch the whole table — operators narrow down via the filters.
  const PAGE_LIMIT = 200;

  let entries = $state<AuditEntry[]>([]);
  let loading = $state(false);
  let q = $state('');
  let action = $state('');
  let actorType = $state('');

  // Sequence guard: rapid applyFilters/resetFilters can leave several list
  // requests in flight; a stale response must not overwrite a newer one.
  let loadGen = 0;

  onMount(() => {
    load();
  });

  async function load() {
    const gen = ++loadGen;
    loading = true;
    try {
      const result = await auditApi.list({
        q: q.trim() || undefined,
        action: action.trim() || undefined,
        actorType: actorType || undefined,
        limit: PAGE_LIMIT,
      });
      if (gen !== loadGen) return;
      entries = result;
    } catch (err) {
      if (gen !== loadGen) return;
      showError(err);
    } finally {
      if (gen === loadGen) loading = false;
    }
  }

  function applyFilters(e: Event) {
    e.preventDefault();
    load();
  }

  function resetFilters() {
    q = '';
    action = '';
    actorType = '';
    load();
  }

  function objectLabel(e: AuditEntry): string {
    if (e.objectLabel && e.objectType) return `${e.objectType}: ${e.objectLabel}`;
    if (e.objectLabel) return e.objectLabel;
    if (e.objectType) return e.objectType;
    return '–';
  }
</script>

<div class="page active">
  <div class="page-header">
    <div>
      <div class="page-title">{$t('page.audit.title')}</div>
      <div class="page-subtitle">{$t('page.audit.subtitle')}</div>
    </div>
  </div>

  <form class="audit-filters panel" onsubmit={applyFilters}>
    <input
      type="text"
      bind:value={q}
      placeholder={$t('page.audit.filter.search')}
      aria-label={$t('page.audit.filter.search')}
    />
    <input
      type="text"
      bind:value={action}
      placeholder={$t('page.audit.filter.action')}
      aria-label={$t('page.audit.filter.action')}
    />
    <select bind:value={actorType} aria-label={$t('page.audit.filter.actorType')}>
      <option value="">{$t('page.audit.filter.allActors')}</option>
      <option value="user">user</option>
      <option value="api_key">api_key</option>
      <option value="anonymous">anonymous</option>
      <option value="system">system</option>
    </select>
    <button class="btn small primary" type="submit">{$t('page.audit.filter.apply')}</button>
    <button class="btn small ghost" type="button" onclick={resetFilters}>
      {$t('page.audit.filter.reset')}
    </button>
  </form>

  <div class="panel">
    {#if loading}
      <EmptyState message={$t('page.audit.loading')} />
    {:else if entries.length === 0}
      <EmptyState message={$t('page.audit.empty')} />
    {:else}
      <table class="data-table">
        <thead>
          <tr>
            <th>{$t('page.audit.col.time')}</th>
            <th>{$t('page.audit.col.actor')}</th>
            <th>{$t('page.audit.col.action')}</th>
            <th>{$t('page.audit.col.object')}</th>
            <th>{$t('page.audit.col.ip')}</th>
            <th>{$t('page.audit.col.status')}</th>
          </tr>
        </thead>
        <tbody>
          {#each entries as e (e.id)}
            <tr>
              <td class="mono">{formatDateTime(e.timestamp)}</td>
              <td>
                <strong>{e.actorLabel ?? '–'}</strong>
                <span class="badge">{e.actorType}</span>
              </td>
              <td class="mono">{e.action}</td>
              <td>{objectLabel(e)}</td>
              <td class="mono">{e.sourceIp ?? '–'}</td>
              <td>
                <span class="status" class:status-bad={e.status !== 'success'}>{e.status}</span>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
      {#if entries.length === PAGE_LIMIT}
        <div class="audit-hint">{$t('page.audit.truncated', { n: PAGE_LIMIT })}</div>
      {/if}
    {/if}
  </div>
</div>

<style>
  .audit-filters {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    margin-bottom: 16px;
  }
  .audit-filters input,
  .audit-filters select {
    padding: 6px 10px;
  }
  .audit-filters input {
    flex: 1;
    min-width: 160px;
  }
  .mono {
    font-family: var(--font-mono, monospace);
    font-size: 0.9em;
  }
  .status-bad {
    color: var(--danger, #d23);
    font-weight: 600;
  }
  .audit-hint {
    padding: 10px 4px 0;
    font-size: 0.85em;
    opacity: 0.7;
  }
</style>
