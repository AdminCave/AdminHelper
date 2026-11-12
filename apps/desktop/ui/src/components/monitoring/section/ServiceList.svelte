<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  import type { MonitorServiceEntry } from '$lib/api/types';

  export type ServiceState = 'failed' | 'active' | 'inactive';
  export type ServiceFilter = 'all' | ServiceState;

  export interface ServiceRow {
    unit: string;
    /** The unit's alias names (systemd), shown with it and found by the search. */
    aliases: string[];
    state: ServiceState;
    activeState: string | null;
    subState: string | null;
    sinceMs: number | null;
    restarts: number | null;
    memoryBytes: number | null;
    reason: string | null;
  }

  /** failed alone counts as failed; activating, deactivating and unknown as inactive. */
  export function stateOf(activeState: string | undefined): ServiceState {
    if (activeState === 'failed') return 'failed';
    if (activeState === 'active' || activeState === 'reloading' || activeState === 'refreshing') {
      return 'active';
    }
    return 'inactive';
  }

  /**
   * Why a unit last ended: systemd's result unless success, with the exit; an exit alone
   * when there is no result (Windows: a stopped service's exit code).
   */
  export function reasonOf(e: MonitorServiceEntry): string | null {
    if (e.result === 'success') return null;
    const parts = [e.result, e.exit].filter((p): p is string => !!p);
    return parts.length > 0 ? parts.join(', ') : null;
  }

  function count(value: string | undefined): number | null {
    return value !== undefined && /^\d+$/.test(value) ? Number(value) : null;
  }

  function time(value: string | undefined): number | null {
    const ms = value ? Date.parse(value) : Number.NaN;
    return Number.isNaN(ms) ? null : ms;
  }

  /**
   * One row per unit, the first entry winning. An alias is no row of its own (its state
   * is not its target's): its name goes with its target, and without one it is dropped.
   */
  export function serviceRows(entries: MonitorServiceEntry[]): ServiceRow[] {
    // Without a prototype: unit names are agent text, and "constructor" must not hit Object's.
    const aliases: Record<string, string[] | undefined> = Object.create(null);
    for (const e of entries) {
      if (e.enabled_state === 'alias' && e.alias_of) {
        aliases[e.alias_of] = [...(aliases[e.alias_of] ?? []), e.unit];
      }
    }
    const seen: Record<string, true | undefined> = Object.create(null);
    const rows: ServiceRow[] = [];
    for (const e of entries) {
      if (e.enabled_state === 'alias' || seen[e.unit]) continue;
      seen[e.unit] = true;
      rows.push({
        unit: e.unit,
        aliases: aliases[e.unit] ?? [],
        state: stateOf(e.active_state),
        activeState: e.active_state ?? null,
        subState: e.sub_state ?? null,
        sinceMs: time(e.since),
        restarts: count(e.restarts),
        memoryBytes: count(e.memory_bytes),
        reason: reasonOf(e),
      });
    }
    return rows;
  }

  export function filterRows(rows: ServiceRow[], filter: ServiceFilter): ServiceRow[] {
    return filter === 'all' ? rows : rows.filter((r) => r.state === filter);
  }
</script>

<script lang="ts">
  import { monitoringApi } from '$lib/api/monitoring';
  import type { MonitorServiceInventory } from '$lib/api/types';
  import { ageText, bytesText, epochAgeText } from '$lib/models/monitoringText';
  import { currentSession } from '$lib/stores/session';
  import { errMsg, errStatus } from '$lib/utils/errors';
  import { t } from '$lib/i18n';
  import EmptyState from '../../ui/EmptyState.svelte';
  import Pill from '../../ui/Pill.svelte';
  import Segmented from '../../ui/Segmented.svelte';
  import CrossTable, { type CrossColumn } from '../cross/CrossTable.svelte';

  interface Props {
    serverId: string;
  }

  let { serverId }: Props = $props();

  // undefined while the answer for this server is out.
  let inventory = $state<MonitorServiceInventory | undefined>(undefined);
  let noAgent = $state(false);
  let error = $state<string | null>(null);
  let filter = $state<ServiceFilter>('all');
  let gen = 0;

  $effect(() => {
    const id = serverId;
    const g = ++gen;
    inventory = undefined;
    noAgent = false;
    error = null;
    const auth = currentSession();
    if (!auth) return;
    monitoringApi.fetchServerServices(auth, id).then(
      (inv) => {
        if (g === gen) inventory = inv;
      },
      (err: unknown) => {
        if (g !== gen) return;
        if (errStatus(err) === 404) noAgent = true;
        else error = errMsg(err);
      },
    );
  });

  const rows = $derived(inventory ? serviceRows(inventory.services) : []);
  const shown = $derived(filterRows(rows, filter));

  // Spelled out: the i18n "no unused keys" guard only sees quoted keys.
  const FILTER_KEY = {
    all: 'monitoring.services.list.filter.all',
    failed: 'monitoring.services.list.filter.failed',
    inactive: 'monitoring.services.list.filter.inactive',
    active: 'monitoring.services.list.filter.active',
  } as const;
  const FILTERS: ServiceFilter[] = ['all', 'failed', 'inactive', 'active'];
  const TONE = { failed: 'crit', active: 'ok', inactive: 'muted' } as const;

  const filterOptions = $derived(
    FILTERS.map((f) => ({
      value: f,
      label: $t(FILTER_KEY[f], { count: filterRows(rows, f).length }),
    })),
  );

  function stateText(r: ServiceRow): string {
    const parts = [r.activeState, r.subState].filter((p): p is string => p !== null);
    return parts.length > 0 ? parts.join(' · ') : '—';
  }

  function nameText(r: ServiceRow): string {
    return [r.unit, ...r.aliases].join(' ');
  }

  const columns: CrossColumn<ServiceRow>[] = $derived([
    {
      key: 'name',
      label: $t('monitoring.services.list.col.name'),
      text: nameText,
      sort: (r) => r.unit,
      cell: nameCell,
    },
    {
      key: 'state',
      label: $t('monitoring.services.list.col.state'),
      text: stateText,
      cell: stateCell,
    },
    {
      key: 'since',
      label: $t('monitoring.services.list.col.since'),
      text: (r) => (r.sinceMs === null ? '—' : (epochAgeText($t, r.sinceMs / 1000) ?? '—')),
      sort: (r) => r.sinceMs,
    },
    {
      key: 'restarts',
      label: $t('monitoring.services.list.col.restarts'),
      text: (r) => (r.restarts === null ? '—' : String(r.restarts)),
      sort: (r) => r.restarts,
      numeric: true,
    },
    {
      key: 'memory',
      label: $t('monitoring.services.list.col.memory'),
      text: (r) => (r.memoryBytes === null ? '—' : bytesText(r.memoryBytes)),
      sort: (r) => r.memoryBytes,
      numeric: true,
    },
    {
      key: 'reason',
      label: $t('monitoring.services.list.col.reason'),
      text: (r) => r.reason ?? '—',
      sort: (r) => r.reason,
    },
  ]);
</script>

{#snippet nameCell(r: ServiceRow)}
  <span class="svc-unit">{r.unit}</span>
  {#if r.aliases.length > 0}
    <span class="svc-aliases"
      >{$t('monitoring.services.list.aliases', { names: r.aliases.join(', ') })}</span
    >
  {/if}
{/snippet}

{#snippet stateCell(r: ServiceRow)}
  <span data-state={r.state}><Pill tone={TONE[r.state]}>{stateText(r)}</Pill></span>
{/snippet}

<div class="svc-list">
  {#if error !== null}
    <EmptyState framed={false} message={$t('monitoring.services.list.error', { error })} />
  {:else if noAgent}
    <EmptyState framed={false} message={$t('monitoring.services.list.noAgent')} />
  {:else if !inventory}
    <p class="svc-muted">{$t('monitoring.detail.loading')}</p>
  {:else if rows.length === 0}
    <EmptyState framed={false} message={$t('monitoring.services.list.empty')} />
  {:else}
    <p class="svc-muted">
      {$t('monitoring.services.list.reported', { age: ageText($t, inventory.reportedAt) })}
    </p>
    <Segmented
      options={filterOptions}
      value={filter}
      label={$t('monitoring.services.list.filter')}
      onChange={(v) => (filter = v as ServiceFilter)}
    />
    <CrossTable
      rows={shown}
      {columns}
      rowKey={(r) => r.unit}
      label={$t('monitoring.services.list.title')}
      emptyText={$t('monitoring.services.list.noneInState')}
      sortKey="name"
    />
  {/if}
</div>

<style>
  .svc-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    min-width: 0;
  }
  .svc-muted {
    margin: 0;
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .svc-unit {
    font-family: var(--font-mono);
  }
  .svc-aliases {
    display: block;
    color: var(--text-muted);
    font-size: var(--text-xs);
  }
</style>
