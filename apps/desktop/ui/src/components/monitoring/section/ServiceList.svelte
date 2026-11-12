<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  import type { MonitorServiceEntry, MonitorServiceLog } from '$lib/api/types';

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
    /** The redacted error lines of a failed unit, if the agent sent any. */
    log: MonitorServiceLog | null;
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

  // The keys are unit names, i.e. agent text: only own keys, so "constructor" finds nothing.
  function logOf(logs: Record<string, MonitorServiceLog>, unit: string): MonitorServiceLog | null {
    const log = Object.hasOwn(logs, unit) ? logs[unit] : undefined;
    return log && log.lines.length > 0 ? log : null;
  }

  /**
   * One row per unit, the first entry winning. An alias is no row of its own (its state
   * is not its target's): its name goes with its target, and without one it is dropped.
   * Error lines go with a failed unit only.
   */
  export function serviceRows(
    entries: MonitorServiceEntry[],
    logs: Record<string, MonitorServiceLog> = {},
  ): ServiceRow[] {
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
      const state = stateOf(e.active_state);
      rows.push({
        unit: e.unit,
        aliases: aliases[e.unit] ?? [],
        state,
        activeState: e.active_state ?? null,
        subState: e.sub_state ?? null,
        sinceMs: time(e.since),
        restarts: count(e.restarts),
        memoryBytes: count(e.memory_bytes),
        reason: reasonOf(e),
        log: state === 'failed' ? logOf(logs, e.unit) : null,
      });
    }
    return rows;
  }

  export function filterRows(rows: ServiceRow[], filter: ServiceFilter): ServiceRow[] {
    return filter === 'all' ? rows : rows.filter((r) => r.state === filter);
  }
</script>

<script lang="ts">
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import { SvelteSet } from 'svelte/reactivity';
  import { monitoringApi } from '$lib/api/monitoring';
  import type { MonitorServiceInventory } from '$lib/api/types';
  import { ageText, bytesText, epochAgeText } from '$lib/models/monitoringText';
  import { currentSession } from '$lib/stores/session';
  import { errMsg, errStatus } from '$lib/utils/errors';
  import { t } from '$lib/i18n';
  import Button from '../../ui/Button.svelte';
  import EmptyState from '../../ui/EmptyState.svelte';
  import Pill from '../../ui/Pill.svelte';
  import Segmented from '../../ui/Segmented.svelte';
  import Switch from '../../ui/Switch.svelte';
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
  // The switch's own state: it flips on click and goes back if saving fails.
  let logLines = $state(false);
  let saving = $state(false);
  let saveError = $state<string | null>(null);
  const expanded = new SvelteSet<string>();
  let gen = 0;

  $effect(() => {
    const id = serverId;
    const g = ++gen;
    inventory = undefined;
    noAgent = false;
    error = null;
    saving = false;
    saveError = null;
    expanded.clear();
    const auth = currentSession();
    if (!auth) return;
    monitoringApi.fetchServerServices(auth, id).then(
      (inv) => {
        if (g !== gen) return;
        inventory = inv;
        logLines = inv.logLines;
      },
      (err: unknown) => {
        if (g !== gen) return;
        if (errStatus(err) === 404) noAgent = true;
        else error = errMsg(err);
      },
    );
  });

  const rows = $derived(inventory ? serviceRows(inventory.services, inventory.logs) : []);
  const shown = $derived(filterRows(rows, filter));

  async function setLogLines(on: boolean): Promise<void> {
    const auth = currentSession();
    if (!auth) {
      logLines = !on;
      return;
    }
    const g = gen;
    saving = true;
    saveError = null;
    try {
      const inv = await monitoringApi.setServiceLogLines(auth, serverId, on);
      if (g !== gen) return;
      inventory = inv;
      logLines = inv.logLines;
    } catch (err) {
      if (g !== gen) return;
      logLines = !on;
      saveError = errMsg(err);
    } finally {
      if (g === gen) saving = false;
    }
  }

  function toggleLog(unit: string): void {
    if (expanded.has(unit)) expanded.delete(unit);
    else expanded.add(unit);
  }

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
      cell: reasonCell,
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

<!-- The lines are agent text: interpolated as text, never as HTML. -->
{#snippet reasonCell(r: ServiceRow)}
  <span>{r.reason ?? '—'}</span>
  {#if r.log}
    {@const open = expanded.has(r.unit)}
    <Button
      size="sm"
      variant="ghost"
      iconLeft={open ? ChevronDown : ChevronRight}
      aria-expanded={open}
      onclick={() => toggleLog(r.unit)}
      >{$t('monitoring.services.logs.toggle', { count: r.log.lines.length })}</Button
    >
    {#if open}
      <div class="svc-log">
        <pre class="svc-log-lines">{r.log.lines.join('\n')}</pre>
        <p class="svc-muted">
          {$t('monitoring.services.logs.hint', { age: ageText($t, r.log.collectedAt) })}
        </p>
      </div>
    {/if}
  {/if}
{/snippet}

<div class="svc-list">
  {#if error !== null}
    <EmptyState framed={false} message={$t('monitoring.services.list.error', { error })} />
  {:else if noAgent}
    <EmptyState framed={false} message={$t('monitoring.services.list.noAgent')} />
  {:else if !inventory}
    <p class="svc-muted">{$t('monitoring.detail.loading')}</p>
  {:else}
    <div class="svc-options">
      <Switch
        size="sm"
        bind:checked={logLines}
        disabled={saving}
        label={$t('monitoring.services.logs.switch')}
        onChange={(on) => void setLogLines(on)}
      />
      <p class="svc-muted">{$t('monitoring.services.logs.switchHint')}</p>
      {#if saveError !== null}
        <p class="svc-error" role="alert">
          {$t('monitoring.services.logs.saveError', { error: saveError })}
        </p>
      {/if}
    </div>
    {#if rows.length === 0}
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
  .svc-options {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .svc-error {
    margin: 0;
    color: var(--danger);
    font-size: var(--text-sm);
  }
  .svc-log {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin-top: var(--space-1);
  }
  .svc-log-lines {
    max-height: 16rem;
    margin: 0;
    padding: var(--space-2);
    overflow: auto;
    border: 1px solid var(--border-faint);
    border-radius: var(--radius-sm);
    background: var(--surface-inset);
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
</style>
