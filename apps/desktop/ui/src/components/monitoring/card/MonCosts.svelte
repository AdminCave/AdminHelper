<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  import type { MonitorCollectorCost } from '$lib/api/types';

  /** Braked: the agent's self-throttle runs it only once in `factor` runs. */
  export function isBraked(c: MonitorCollectorCost): boolean {
    return (c.factor ?? 1) > 1 || c.throttled === true;
  }

  /** Costliest first: CPU time, then duration, unknown values last, then by name. */
  export function byCost(a: MonitorCollectorCost, b: MonitorCollectorCost): number {
    const cpu = (b.cpuMs ?? -1) - (a.cpuMs ?? -1);
    if (cpu !== 0) return cpu;
    const duration = (b.durationMs ?? -1) - (a.durationMs ?? -1);
    return duration !== 0 ? duration : a.collector.localeCompare(b.collector);
  }
</script>

<script lang="ts">
  import { monitoringApi } from '$lib/api/monitoring';
  import type { MonitorServerCosts } from '$lib/api/types';
  import { currentSession } from '$lib/stores/session';
  import { errMsg } from '$lib/utils/errors';
  import { currentLocale, t } from '$lib/i18n';
  import EmptyState from '../../ui/EmptyState.svelte';
  import MonCard from './MonCard.svelte';

  interface Props {
    serverId: string;
  }

  let { serverId }: Props = $props();

  // undefined while the first answer for this server is out: no card until then.
  let costs = $state<MonitorServerCosts | undefined>(undefined);
  let error = $state<string | null>(null);
  let gen = 0;

  $effect(() => {
    const id = serverId;
    const g = ++gen;
    costs = undefined;
    error = null;
    const auth = currentSession();
    if (!auth) return;
    monitoringApi.fetchServerCosts(auth, id).then(
      (c) => {
        if (g === gen) costs = c;
      },
      (err: unknown) => {
        if (g === gen) error = errMsg(err);
      },
    );
  });

  const rows = $derived(costs ? [...costs.collectors].sort(byCost) : []);
  const braked = $derived(rows.filter(isBraked).length);
  const timeouts = $derived(rows.reduce((sum, c) => sum + Math.round(c.timeouts ?? 0), 0));

  const summary = $derived(
    [
      $t('monitoring.costs.collectors', { count: rows.length }),
      braked > 0 ? $t('monitoring.costs.brakedCount', { count: braked }) : null,
      timeouts > 0 ? $t('monitoring.costs.timeoutCount', { count: timeouts }) : null,
    ]
      .filter((part) => part !== null)
      .join(' · '),
  );

  function number(value: number, digits: number): string {
    return value.toLocaleString(currentLocale(), { maximumFractionDigits: digits });
  }

  function ms(value: number | null): string {
    if (value === null) return '—';
    return value < 1000 ? `${number(value, 0)} ms` : `${number(value / 1000, 1)} s`;
  }

  function brake(c: MonitorCollectorCost): string {
    if (c.factor === null && c.throttled === null) return '—';
    if ((c.factor ?? 1) > 1) return $t('monitoring.costs.onceIn', { factor: c.factor ?? 1 });
    return isBraked(c) ? $t('monitoring.costs.braked') : $t('monitoring.costs.notBraked');
  }
</script>

{#if error !== null}
  <MonCard title={$t('monitoring.costs.title')} status={null} defaultOpen={false}>
    <EmptyState framed={false} message={$t('monitoring.costs.error', { error })} />
  </MonCard>
{:else if costs && rows.length > 0}
  <MonCard title={$t('monitoring.costs.title')} status={null} {summary} defaultOpen={false}>
    <div class="costs">
      <p class="costs-intro">{$t('monitoring.costs.intro', { window: costs.window })}</p>
      <div class="costs-scroll">
        <table class="costs-table" aria-label={$t('monitoring.costs.title')}>
          <thead>
            <tr>
              <th scope="col">{$t('monitoring.costs.col.collector')}</th>
              <th scope="col" class="numeric">{$t('monitoring.costs.col.duration')}</th>
              <th scope="col" class="numeric">{$t('monitoring.costs.col.cpu')}</th>
              <th scope="col" class="numeric">{$t('monitoring.costs.col.timeouts')}</th>
              <th scope="col">{$t('monitoring.costs.col.braked')}</th>
            </tr>
          </thead>
          <tbody>
            {#each rows as c (c.collector)}
              <tr data-collector={c.collector} class:braked={isBraked(c)}>
                <td>{c.collector}</td>
                <td class="numeric">{ms(c.durationMs)}</td>
                <td class="numeric">{ms(c.cpuMs)}</td>
                <td class="numeric">{c.timeouts === null ? '—' : number(c.timeouts, 0)}</td>
                <td>{brake(c)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  </MonCard>
{/if}

<style>
  .costs {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
  }
  .costs-intro {
    margin: 0;
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .costs-scroll {
    overflow-x: auto;
  }
  .costs-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  .costs-table th,
  .costs-table td {
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--border-faint);
    text-align: left;
    vertical-align: middle;
  }
  .costs-table thead th {
    color: var(--text-subtle);
    font-weight: 500;
    white-space: nowrap;
  }
  .costs-table .numeric {
    font-family: var(--font-mono);
    text-align: right;
  }
  .costs-table tr.braked td:last-child {
    color: var(--warning);
  }
</style>
