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
  import Button from '$lib/components/ui/Button.svelte';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import FormField from '$lib/components/ui/FormField.svelte';
  import Panel from '$lib/components/ui/Panel.svelte';
  import Pill from '$lib/components/ui/Pill.svelte';
  import SearchField from '$lib/components/ui/SearchField.svelte';
  import Select from '$lib/components/ui/Select.svelte';
  import type { AuditEntry } from '$lib/api/types';

  // Bound at one page worth of recent activity; the trail can grow large, so we
  // never fetch the whole table — operators narrow down via the filters.
  const PAGE_LIMIT = 200;

  let entries = $state<AuditEntry[]>([]);
  let loading = $state(false);
  let q = $state('');
  let action = $state('');
  // The Select shows a placeholder for an empty value, so "all actors" has a value of its own.
  const ALL = 'all';
  let actorType = $state(ALL);
  const actorOptions = $derived([
    { value: ALL, label: $t('page.audit.filter.allActors') },
    'user',
    'api_key',
    'anonymous',
    'system',
  ]);

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
        actorType: actorType === ALL ? undefined : actorType,
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
    actorType = ALL;
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

  <Panel>
    <form class="audit-filters" onsubmit={applyFilters}>
      <div class="grow">
        <FormField label={$t('page.audit.filter.search')}>
          <SearchField bind:value={q} placeholder={$t('page.audit.filter.search')} />
        </FormField>
      </div>
      <div class="grow">
        <FormField label={$t('page.audit.filter.action')}>
          <SearchField bind:value={action} placeholder={$t('page.audit.filter.action')} />
        </FormField>
      </div>
      <FormField label={$t('page.audit.filter.actorType')}>
        <Select bind:value={actorType} options={actorOptions} />
      </FormField>
      <div class="buttons">
        <Button type="submit" variant="primary">{$t('page.audit.filter.apply')}</Button>
        <Button variant="ghost" onclick={resetFilters}>{$t('page.audit.filter.reset')}</Button>
      </div>
    </form>
  </Panel>

  <Panel pad={0}>
    {#if loading}
      <EmptyState framed={false} message={$t('page.audit.loading')} />
    {:else if entries.length === 0}
      <EmptyState framed={false} message={$t('page.audit.empty')} />
    {:else}
      <table class="data-table">
        <thead>
          <tr>
            <th>{$t('page.audit.col.time')}</th>
            <th>{$t('page.audit.col.actor')}</th>
            <th>{$t('page.audit.col.action')}</th>
            <th>{$t('page.audit.col.object')}</th>
            <th>{$t('page.audit.col.detail')}</th>
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
                <Pill>{e.actorType}</Pill>
              </td>
              <td class="mono">{e.action}</td>
              <td>{objectLabel(e)}</td>
              <td class="detail">{e.detail ?? '–'}</td>
              <td class="mono">{e.sourceIp ?? '–'}</td>
              <td>
                <Pill tone={e.status === 'success' ? 'ok' : 'crit'}>{e.status}</Pill>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
      {#if entries.length === PAGE_LIMIT}
        <div class="audit-hint">{$t('page.audit.truncated', { n: PAGE_LIMIT })}</div>
      {/if}
    {/if}
  </Panel>
</div>

<style>
  .audit-filters {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
    align-items: flex-end;
  }
  .grow {
    flex: 1;
    min-width: 200px;
  }
  .buttons {
    display: flex;
    gap: var(--space-2);
  }
  .mono {
    font-family: var(--font-mono);
    font-size: 0.9em;
  }
  .detail {
    overflow-wrap: anywhere;
  }
  .audit-hint {
    padding: var(--space-3) var(--space-4);
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
</style>
